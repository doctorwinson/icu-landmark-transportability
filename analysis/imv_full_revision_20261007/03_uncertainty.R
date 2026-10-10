args<-commandArgs(FALSE)
here<-dirname(normalizePath(sub('^--file=','',args[grepl('^--file=',args)][1]),winslash='/'))
source(file.path(dirname(here),'rebuild_20261006/R/02_common.R'))
out<-file.path(here,'results');local<-file.path(here,'local_only')
save_json<-function(x,p)jsonlite::write_json(x,p,pretty=TRUE,auto_unbox=TRUE,null='null',digits=16)
b<-readRDS(file.path(local,'predictions.rds'));E<-b$external_data;I<-b$internal_data
target<-'composite_deterioration_7d';thresholds<-c(.05,.10,.15)
hu<-unique(as.character(E$hospital));parent<-seq_along(hu)
find<-function(i){while(parent[i]!=i)i<-parent[i];i}
for(hs in split(as.character(E$hospital),as.character(E$uniquepid))) {
 ix<-unique(match(hs,hu));if(length(ix)>1)for(j in ix[-1])parent[find(j)]<-find(ix[1])
}
connected<-vapply(match(as.character(E$hospital),hu),find,integer(1))
save_json(list(stays=nrow(E),patients=length(unique(E$uniquepid)),hospitals=length(hu),connected_blocks=length(unique(connected)),largest_hospital_fraction=max(table(E$hospital))/nrow(E)),file.path(out,'cluster_structure.json'))
write.csv(data.frame(stay_id=E$stay_id,hospital=E$hospital,patient=E$uniquepid,connected=connected),file.path(local,'cluster_membership.csv'),row.names=FALSE)
metric<-function(y,p)c(auroc=safe_auc(y,p),auprc=safe_auprc(y,p),brier=mean((y-p)^2))
measure<-function(ix,y,p) {
 y<-y[ix];p<-lapply(p,function(z)z[ix]);x<-p$tuned_xgboost;r<-p$ridge_logistic
 z<-unlist(lapply(p,function(q)metric(y,q)))
 br<-function(q)mean((y-q)^2)
 z<-c(z,auc_xgb_minus_ridge=safe_auc(y,x)-safe_auc(y,r),brier_improvement_vs_ridge=br(r)-br(x),brier_improvement_vs_baseline=br(p$baseline_xgboost)-br(x),brier_improvement_vs_sample_prevalence=br(mean(y))-br(x),brier_improvement_vs_development_prevalence=br(b$development_rate)-br(x))
 for(t in thresholds) {
  nb<-function(q)mean((q>=t)*(y-(1-y)*t/(1-t)))
  all<-mean(y)-(1-mean(y))*t/(1-t)
  a<-c(xgb=nb(x),ridge=nb(r),all=all,increment_vs_all=nb(x)-all,increment_vs_none=nb(x),increment_vs_ridge=nb(x)-nb(r))
  names(a)<-paste0('nb_',formatC(t,format='f',digits=2),'_',names(a));z<-c(z,a)
 }
 z
}
bootstrap<-function(y,groups,fun,B=2000) {
 blocks<-unname(split(seq_along(y),as.character(groups)));K<-length(blocks);set.seed(20261007)
 pt<-fun(seq_along(y));v<-matrix(NA_real_,B,length(pt),dimnames=list(NULL,names(pt)))
 for(j in seq_len(B)) {
  ix<-unlist(blocks[sample.int(K,K,TRUE)],use.names=FALSE)
  v[j,]<-fun(ix)
  if(j%%500==0)message('Bootstrap ',j,'/',B)
 }
 q<-function(x,p)if(any(is.finite(x)))quantile(x[is.finite(x)],p,names=FALSE) else NA_real_
 data.frame(metric=names(pt),estimate=unname(pt),lower=apply(v,2,q,.025),upper=apply(v,2,q,.975),valid_replicates=colSums(is.finite(v)),replicates=B,clusters=K)
}
allci<-list()
for(s in c('hospital','patient','connected')) {
 g<-switch(s,hospital=E$hospital,patient=E$uniquepid,connected=connected)
 message('External ',s)
 allci[[s]]<-cbind(dataset='external',scheme=s,bootstrap(E[[target]],g,function(ix)measure(ix,E[[target]],b$external)))
 write.csv(bind_rows(allci),file.path(out,'paired_uncertainty.csv'),row.names=FALSE)
}
allci$internal<-cbind(dataset='internal',scheme='patient',bootstrap(I[[target]],I$subject_id,function(ix)measure(ix,I[[target]],b$internal)))
write.csv(bind_rows(allci),file.path(out,'paired_uncertainty.csv'),row.names=FALSE)
work<-list();dca<-list()
for(ds in c('internal','external')) {
 d<-if(ds=='internal')I else E;p<-b[[ds]];y<-d[[target]]
 for(nm in c('tuned_xgboost','ridge_logistic')) {
  dca[[length(dca)+1]]<-cbind(dataset=ds,model=nm,decision_curve(y,p[[nm]],seq(.01,.5,.01)))
  for(t in thresholds) {
   flag<-p[[nm]]>=t;tp<-sum(flag&y==1);fp<-sum(flag&y==0);fn<-sum(!flag&y==1)
   work[[length(work)+1]]<-data.frame(dataset=ds,model=nm,threshold=t,n=length(y),flagged=sum(flag),flagged_fraction=mean(flag),tp=tp,fp=fp,fn=fn,sensitivity=tp/sum(y),ppv=if(sum(flag))tp/sum(flag) else NA_real_,unflagged_events=fn,unflagged_event_rate=if(sum(!flag))fn/sum(!flag) else NA_real_,reviews_per_captured_event=if(tp)sum(flag)/tp else NA_real_)
  }
 }
}
write.csv(bind_rows(work),file.path(out,'threshold_workload.csv'),row.names=FALSE)
write.csv(bind_rows(dca),file.path(out,'dca.csv'),row.names=FALSE)
component_ci<-list();sens_ci<-list();sp<-readRDS(file.path(local,'sensitivity_predictions.rds'))
for(ds in c('internal','external')) {
 d<-if(ds=='internal')I else E;g<-if(ds=='internal')I$subject_id else E$hospital;p<-b[[ds]]$tuned_xgboost
 for(cmp in c('vaso_7d_post_window','imv_7d_post_window','rrt_7d_post_window','death_7d_post_window','organ_support_7d')) {
  y<-d[[cmp]];keep<-!is.na(y)
  # Resample whole clusters first; unknown component labels are omitted within each replicate.
  fun<-function(ix){k<-ix[keep[ix]];c(auroc=safe_auc(y[k],p[k]),auprc=safe_auprc(y[k],p[k]))}
  message('Component ',ds,' ',cmp)
  component_ci[[length(component_ci)+1]]<-cbind(dataset=ds,component=cmp,bootstrap(d[[target]],g,fun,1000))
 }
 for(nm in c('without_measurement_indicators','low_missing','organ_support_refit')) {
  z<-sp[[paste(nm,ds,sep='_')]]
  fun<-function(ix){k<-ix[!is.na(z$y[ix])];metric(z$y[k],z$p[k])}
  sens_ci[[length(sens_ci)+1]]<-cbind(dataset=ds,analysis=nm,bootstrap(d[[target]],g,fun,1000))
 }
}
write.csv(bind_rows(component_ci),file.path(out,'component_ci.csv'),row.names=FALSE)
write.csv(bind_rows(sens_ci),file.path(out,'sensitivity_ci.csv'),row.names=FALSE)
rr<-readRDS(file.path(local,'recalibration_holdout.rds'))
rc<-bootstrap(rr$y,rr$hospital,function(ix)c(brier_improvement=mean((rr$y[ix]-rr$raw[ix])^2-(rr$y[ix]-rr$updated[ix])^2)))
write.csv(rc,file.path(out,'recalibration_paired_ci.csv'),row.names=FALSE)
dl<-lapply(setdiff(names(b$external),'tuned_xgboost'),function(nm)cbind(comparator=nm,as.data.frame(delong_roc_test(E[[target]],b$external$tuned_xgboost,b$external[[nm]]))))
write.csv(bind_rows(dl),file.path(out,'delong_descriptive_only.csv'),row.names=FALSE)
save_json(list(status='COMPLETE_CONDITIONAL_EXPLORATORY_INTERVALS',main_bootstrap=2000,component_sensitivity_bootstrap=1000,pointwise=TRUE,multiplicity_adjusted=FALSE,label_uncertainty_in_intervals=FALSE,training_uncertainty_in_intervals=FALSE),file.path(out,'uncertainty_complete.json'))
