# Refit only after full-cohort reconciliation. Prior files remain read-only.
args <- commandArgs(FALSE)
here <- dirname(normalizePath(sub('^--file=', '', args[grepl('^--file=', args)][1]), winslash='/'))
base <- file.path(dirname(here),'rebuild_20261006')
root <- dirname(dirname(here))
source(file.path(base,'R/02_common.R'))
suppressPackageStartupMessages(library(glmnet))
save_json <- function(x,p) jsonlite::write_json(x,p,pretty=TRUE,auto_unbox=TRUE,null='null',digits=16)
out <- file.path(here,'results'); local <- file.path(here,'local_only')
data <- file.path(root,'data/imv_revision_20261007')
stopifnot(file.exists(file.path(out,'full_cohort_qc.json')))
qc <- jsonlite::fromJSON(file.path(out,'full_cohort_qc.json'))
stopifnot(isTRUE(qc$passed), file.exists(file.path(here,'prefit_lock_v3.json')))
if(file.exists(file.path(out,'refit_complete_v3.json'))) stop('Completed analysis exists; no silent overwrite')
M <- as.data.frame(arrow::read_parquet(file.path(data,'study1_bdmcc24_dataset.parquet')))
target <- 'composite_deterioration_7d'
cols <- jsonlite::fromJSON(file.path(base,'feature_whitelist.json'))
cats <- c('gender','race'); nums <- setdiff(cols,cats)
old <- readRDS(file.path(base,'results/split_ids_local_only.rds'))
assign_split <- function(d) {
 z <- rep(NA_character_,nrow(d))
 for(s in names(old)) z[d$stay_id %in% old[[s]]] <- s
 new <- which(is.na(z))
 if(length(new)) {
  u <- vapply(d$subject_id[new], function(id) strtoi(substr(digest::digest(paste0('imv_revision_20261007:',id),algo='sha256',serialize=FALSE),1,7),16L)/16^7, numeric(1))
  z[new] <- ifelse(u<.70,'train',ifelse(u<.85,'valid','test'))
 }
 z
}
M$split <- assign_split(M)
stopifnot(!anyNA(M$split),!anyDuplicated(M$subject_id),!anyNA(M[[target]]),all(cols%in%names(M)))
write.csv(M[c('stay_id','subject_id','split')],file.path(local,'split_membership.csv'),row.names=FALSE)
spl <- lapply(c('train','valid','test'),function(s)M$stay_id[M$split==s]);names(spl)<-c('train','valid','test')
saveRDS(spl,file.path(local,'split_ids.rds'))
tr<-M[M$split=='train',];va<-M[M$split=='valid',];dev<-M[M$split!='test',];te<-M[M$split=='test',]
stopifnot(length(unique(tr[[target]]))==2,length(unique(va[[target]]))==2,length(unique(te[[target]]))==2)
write.csv(M |> group_by(split) |> summarise(n=n(),events=sum(.data[[target]])),file.path(out,'split_counts.csv'),row.names=FALSE)
mat <- function(pp,d,cc=cols)transform_preprocessor(pp,d[,cc,drop=FALSE])$matrix
pre<-fit_preprocessor(tr,cats,nums); xtr<-mat(pre,tr);xva<-mat(pre,va)
cfg<-yaml::read_yaml(file.path(base,'R/config.yaml'))
baseline<-as.list(c(cfg$models$xgboost,list(min_child_weight=1,alpha=0,gamma=0)))
grid<-read.csv(file.path(base,'results/tuning_leaderboard.csv'))
grid<-grid[order(grid$candidate),c(names(baseline),'candidate')]
stopifnot(nrow(grid)==64)
rec<-list()
for(i in seq_len(nrow(grid))) {
 pp<-as.list(grid[i,names(baseline)])
 fit<-fit_xgb_model(xtr,tr[[target]],pp,xva,va[[target]],50,20261006)
 a<-compute_binary_metrics(tr[[target]],predict_xgb_model(fit,xtr));b<-compute_binary_metrics(va[[target]],predict_xgb_model(fit,xva))
 rec[[i]]<-cbind(grid[i,],best_iteration=fit$best_iteration,valid_auprc=b$auprc,valid_auroc=b$auroc,valid_brier=b$brier,gap=a$auroc-b$auroc)
 if(i%%8==0) message('Tuning ',i,'/64')
}
leader<-bind_rows(rec) |> arrange(desc(valid_auprc),desc(valid_auroc),valid_brier,gap)
write.csv(leader,file.path(out,'tuning_leaderboard.csv'),row.names=FALSE)
best<-as.list(leader[1,names(baseline)]);best$nrounds<-as.integer(leader$best_iteration[1])
lambda_grid<-10^seq(2,-6,length.out=81);glmnet.control(fdev=0,devmax=1)
ridgepath<-glmnet(xtr,tr[[target]],family='binomial',alpha=0,lambda=lambda_grid,standardize=TRUE,thresh=1e-10,maxit=1000000)
stopifnot(ridgepath$jerr==0,length(ridgepath$lambda)==81)
vp<-predict(ridgepath,newx=xva,s=lambda_grid,type='response')
loss<-apply(vp,2,function(p){p<-clip_probabilities(p);-mean(va[[target]]*log(p)+(1-va[[target]])*log1p(-p))})
li<-which(loss<=min(loss)+1e-12)[1];lam<-lambda_grid[li]
write.csv(data.frame(lambda=lambda_grid,logloss=loss,selected=seq_along(loss)==li),file.path(out,'ridge_selection.csv'),row.names=FALSE)
pre<-fit_preprocessor(dev,cats,nums);xd<-mat(pre,dev);xt<-mat(pre,te)
models<-list(tuned_xgboost=fit_xgb_model(xd,dev[[target]],best),baseline_xgboost=fit_xgb_model(xd,dev[[target]],baseline),
 ridge_logistic=glmnet(xd,dev[[target]],family='binomial',alpha=0,lambda=lambda_grid,standardize=TRUE,thresh=1e-10,maxit=1000000),
 historical_weighted_lr=fit_logistic_model(xd,dev[[target]],class_weight='balanced'))
stopifnot(models$ridge_logistic$jerr==0)
# Save final fits before loading external data for model evaluation.
saveRDS(list(models=models,preprocessor=pre,lambda=lam,best=best),file.path(local,'fitted_before_external.rds'))
predict_all<-function(d){x<-mat(pre,d);list(tuned_xgboost=predict_xgb_model(models$tuned_xgboost,x),baseline_xgboost=predict_xgb_model(models$baseline_xgboost,x),ridge_logistic=clip_probabilities(as.numeric(predict(models$ridge_logistic,newx=x,s=lam,type='response'))),historical_weighted_lr=predict_logistic_model(models$historical_weighted_lr,x))}
E<-as.data.frame(arrow::read_parquet(file.path(data,'study1_eicu_bdmcc24_dataset.parquet')))
meta<-as.data.frame(arrow::read_parquet(file.path(local,'eicu_metadata.parquet')))
E$hospital<-meta$hospitalid[match(E$stay_id,meta$stay_id)]
stopifnot(!anyNA(E$hospital),!anyNA(E[[target]]))
pi<-predict_all(te);pe<-predict_all(E)
bundle<-list(internal=pi,external=pe,internal_data=te,external_data=E,development_rate=mean(dev[[target]]))
saveRDS(bundle,file.path(local,'predictions.rds'))
point<-list()
for(ds in c('internal','external')) {
 d<-if(ds=='internal')te else E;p<-if(ds=='internal')pi else pe
 for(nm in names(p))point[[length(point)+1]]<-cbind(dataset=ds,model=nm,as.data.frame(compute_binary_metrics(d[[target]],p[[nm]])),calibration_in_the_large=calibration_in_the_large(d[[target]],p[[nm]]))
}
write.csv(bind_rows(point),file.path(out,'performance.csv'),row.names=FALSE)
components<-c('vaso_7d_post_window','imv_7d_post_window','rrt_7d_post_window','death_7d_post_window',target)
cc<-list()
for(ds in c('internal','external')) {
 d<-if(ds=='internal')te else E;p<-if(ds=='internal')pi$tuned_xgboost else pe$tuned_xgboost
 for(cmp in components) {
  k<-!is.na(d[[cmp]])
  cc[[length(cc)+1]]<-data.frame(dataset=ds,component=cmp,total=nrow(d),assessable=sum(k),unknown=sum(!k),events=sum(d[[cmp]][k]),event_rate=mean(d[[cmp]][k]),auroc=safe_auc(d[[cmp]][k],p[k]),auprc=safe_auprc(d[[cmp]][k],p[k]))
 }
}
write.csv(bind_rows(cc),file.path(out,'components.csv'),row.names=FALSE)
high<-names(which(colMeans(is.na(dev[,cols]))>.20));high<-intersect(unique(c(high,paste0(sub('_(first|min|max)$','',high),'_measured_by24'))),cols)
drops<-list(without_measurement_indicators=grep('_measured_by24$',cols,value=TRUE),low_missing=high,organ_support_refit=character())
sens<-list();senspred<-list()
for(nm in names(drops)) {
 cc<-setdiff(cols,drops[[nm]]);targ<-if(nm=='organ_support_refit')'organ_support_7d' else target
 dd<-dev[!is.na(dev[[targ]]),];catc<-intersect(cats,cc);pp<-fit_preprocessor(dd,catc,setdiff(cc,catc))
 fit<-fit_xgb_model(mat(pp,dd,cc),dd[[targ]],best)
 for(ds in c('internal','external')) {
  d<-if(ds=='internal')te else E;p<-predict_xgb_model(fit,mat(pp,d,cc));k<-!is.na(d[[targ]])
  sens[[length(sens)+1]]<-cbind(analysis=nm,dataset=ds,features=length(cc),unknown=sum(!k),as.data.frame(compute_binary_metrics(d[[targ]][k],p[k])))
  senspred[[paste(nm,ds,sep='_')]]<-list(y=d[[targ]],p=p)
 }
}
for(ds in c('internal','external')) {
 d<-if(ds=='internal')te else E;p<-if(ds=='internal')pi$tuned_xgboost else pe$tuned_xgboost;k<-!is.na(d$organ_support_7d)
 sens[[length(sens)+1]]<-cbind(analysis='organ_support_fixed_composite',dataset=ds,features=length(cols),unknown=sum(!k),as.data.frame(compute_binary_metrics(d$organ_support_7d[k],p[k])))
}
write.csv(bind_rows(sens),file.path(out,'sensitivity.csv'),row.names=FALSE)
saveRDS(senspred,file.path(local,'sensitivity_predictions.rds'))
# Scenarios include all eligibility-qualified unknown outcomes, with fixed predictions.
scenarios<-list()
for(ds in c('mimic','eicu')) {
 d<-as.data.frame(arrow::read_parquet(file.path(data,paste0(ds,'_eligible_with_unknown_outcomes.parquet'))))
 if(ds=='mimic')d<-d[assign_split(d)=='test',]
 p<-predict_all(d)$tuned_xgboost
 for(value in c(0,1)) {
  y<-d[[target]];unknown<-is.na(y);y[unknown]<-value
  scenarios[[length(scenarios)+1]]<-cbind(dataset=ds,unknown_encoding=value,n_unknown=sum(unknown),as.data.frame(compute_binary_metrics(y,p)))
 }
}
write.csv(bind_rows(scenarios),file.path(out,'unknown_outcome_scenarios.csv'),row.names=FALSE)
set.seed(20261006);uid<-unique(as.character(E$uniquepid));rids<-sample(uid,floor(length(uid)/2));ii<-which(E$uniquepid%in%rids);jj<-which(!E$uniquepid%in%rids)
rf<-glm(y~logits,data=data.frame(y=E[[target]][ii],logits=qlogis(clip_probabilities(pe$tuned_xgboost[ii]))),family=binomial())
rp<-plogis(coef(rf)[1]+coef(rf)[2]*qlogis(clip_probabilities(pe$tuned_xgboost[jj])))
write.csv(bind_rows(cbind(model='raw',as.data.frame(compute_binary_metrics(E[[target]][jj],pe$tuned_xgboost[jj]))),cbind(model='recalibrated',as.data.frame(compute_binary_metrics(E[[target]][jj],rp)))),file.path(out,'recalibration.csv'),row.names=FALSE)
saveRDS(list(y=E[[target]][jj],raw=pe$tuned_xgboost[jj],updated=rp,hospital=E$hospital[jj],patient=E$uniquepid[jj]),file.path(local,'recalibration_holdout.rds'))
save_json(list(n_fit=length(ii),n_holdout=length(jj),parameters=as.list(coef(rf)),shared_hospitals=length(intersect(E$hospital[ii],E$hospital[jj]))),file.path(out,'recalibration_details.json'))
sh<-predict(models$tuned_xgboost,xgb.DMatrix(xt),predcontrib=TRUE);sh<-sh[,seq_len(ncol(sh)-1),drop=FALSE]
imp<-data.frame(predictor=colnames(xt),mean_abs_shap=colMeans(abs(sh))) |> arrange(desc(mean_abs_shap))
write.csv(imp,file.path(out,'shap_importance.csv'),row.names=FALSE)
save_json(list(n_mimic=nrow(M),n_eicu=nrow(E),best_params=best,ridge_lambda=lam,seed=20261006,features=cols,encoded_features=ncol(xd),high_missing_dropped=high,old_split_preserved=TRUE,new_stays_assigned_without_outcomes=TRUE,external_not_used_for_selection=TRUE,status='MODELS_REFITTED_UNCERTAINTY_PENDING'),file.path(out,'refit_complete_v3.json'))
writeLines(capture.output(sessionInfo()),file.path(out,'R_sessionInfo.txt'))
message('Refitting completed; cluster intervals are a separate step.')
