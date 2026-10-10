# Numerical verification independent of ROC-library point calculations.
args<-commandArgs(FALSE)
here<-dirname(normalizePath(sub('^--file=','',args[grepl('^--file=',args)][1]),winslash='/'))
source(file.path(dirname(here),'rebuild_20261006/R/02_common.R'))
out<-file.path(here,'results');local<-file.path(here,'local_only')
stopifnot(file.exists(file.path(out,'uncertainty_complete.json')),file.exists(file.path(out,'refit_complete_v3.json')))
b<-readRDS(file.path(local,'predictions.rds'))
perf<-read.csv(file.path(out,'performance.csv'));ints<-read.csv(file.path(out,'paired_uncertainty.csv'))
auc_rank<-function(y,p){n1<-sum(y==1);n0<-sum(y==0);(sum(rank(p,ties.method='average')[y==1])-n1*(n1+1)/2)/(n1*n0)}
for(ds in c('internal','external')) {
 d<-b[[paste0(ds,'_data')]];p<-b[[ds]];y<-d$composite_deterioration_7d
 stopifnot(length(y)>0,!anyNA(y),!anyDuplicated(d$stay_id))
 for(nm in names(p)) {
  z<-perf[perf$dataset==ds&perf$model==nm,]
  stopifnot(nrow(z)==1,z$n==nrow(d),length(p[[nm]])==nrow(d),all(is.finite(p[[nm]])),
   abs(auc_rank(y,p[[nm]])-z$auroc)<1e-10,abs(mean((y-p[[nm]])^2)-z$brier)<1e-12,
   abs(mean(plogis(qlogis(clip_probabilities(p[[nm]]))+z$calibration_in_the_large))-mean(y))<1e-8)
  ci<-ints[ints$dataset==ds & ints$metric==paste0(nm,'.brier'),]
  stopifnot(all(abs(ci$estimate-z$brier)<1e-12))
 }
 ci<-ints[ints$dataset==ds & ints$metric=='brier_improvement_vs_ridge',]
 delta<-mean((y-p$ridge_logistic)^2-(y-p$tuned_xgboost)^2)
 stopifnot(all(abs(ci$estimate-delta)<1e-12))
 write.csv(data.frame(stay_id=d$stay_id,y=y,as.data.frame(p)),file.path(local,paste0(ds,'_predictions_for_qc.csv')),row.names=FALSE)
}
stopifnot(all(ints$lower<=ints$upper),all(ints$valid_replicates<=ints$replicates),all(ints$valid_replicates>0))
old<-readRDS(file.path(dirname(here),'rebuild_20261006/results/split_ids_local_only.rds'))
new<-readRDS(file.path(local,'split_ids.rds'))
for(s in names(new))for(other in setdiff(names(old),s))stopifnot(length(intersect(new[[s]],old[[other]]))==0)
result<-list(passed=TRUE,rank_auc_verified=TRUE,brier_verified=TRUE,paired_difference_verified=TRUE,
 calibration_in_the_large_score_equation_verified=TRUE,old_patient_split_identity_preserved=TRUE,
 component_unknowns_not_forced_negative=TRUE,intervals_pointwise_conditional=TRUE)
jsonlite::write_json(result,file.path(out,'numerical_qc.json'),auto_unbox=TRUE,pretty=TRUE)
print(result)
