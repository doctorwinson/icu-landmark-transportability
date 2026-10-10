# Fixed-model, hospital-cluster calibration intervals; no model or label selection.
args <- commandArgs(FALSE)
here <- dirname(normalizePath(sub('^--file=','',args[grepl('^--file=',args)][1]),winslash='/'))
base <- file.path(dirname(here),'imv_full_revision_20261007')
source(file.path(dirname(here),'rebuild_20261006/R/02_common.R'))
out <- file.path(here,'results');dir.create(out,showWarnings=FALSE)
b <- readRDS(file.path(base,'local_only/predictions.rds'))
d <- b$external_data;y <- d$composite_deterioration_7d
cal <- function(y,p) {
 z <- qlogis(pmin(pmax(p,1e-6),1-1e-6))
 fit <- suppressWarnings(glm.fit(cbind(1,z),y,family=binomial()))
 if(!isTRUE(fit$converged)||any(!is.finite(fit$coefficients))) return(c(intercept=NA,slope=NA,citl=NA))
 a <- uniroot(function(a)sum(plogis(z+a))-sum(y),c(-40,40))$root
 c(intercept=unname(fit$coefficients[1]),slope=unname(fit$coefficients[2]),citl=a)
}
blocks <- unname(split(seq_along(y),d$hospital));K<-length(blocks)
set.seed(20261007)
indices <- replicate(2000,unlist(blocks[sample.int(K,K,TRUE)],use.names=FALSE),simplify=FALSE)
rows<-list()
for(nm in names(b$external)) {
 p<-b$external[[nm]];pt<-cal(y,p)
 vals<-t(vapply(indices,function(ix)cal(y[ix],p[ix]),numeric(3)))
 for(j in seq_along(pt)) {
  x<-vals[,j];x<-x[is.finite(x)]
  rows[[length(rows)+1]]<-data.frame(model=nm,parameter=names(pt)[j],estimate=pt[j],lower=quantile(x,.025,names=FALSE),upper=quantile(x,.975,names=FALSE),valid_replicates=length(x),replicates=2000)
 }
 message('Calibration CI: ',nm)
}
write.csv(bind_rows(rows),file.path(out,'calibration_ci.csv'),row.names=FALSE)
rr<-readRDS(file.path(base,'local_only/recalibration_holdout.rds'))
details<-jsonlite::fromJSON(file.path(base,'results/recalibration_details.json'))
jsonlite::write_json(list(n_fit=details$n_fit,events_fit=sum(y)-sum(rr$y),n_holdout=length(rr$y),events_holdout=sum(rr$y),updating_coefficients=details$parameters,shared_hospitals=details$shared_hospitals),file.path(out,'recalibration_reporting.json'),pretty=TRUE,auto_unbox=TRUE,digits=16)

# Smooth descriptive calibration: 3-df natural spline, fixed full-assessment knots.
# The bands quantify assessment-sample variation, not refitting or labeling uncertainty.
curves<-list()
for(ds in c('internal','external')) {
 dat<-b[[paste0(ds,'_data')]];yy<-dat$composite_deterioration_7d;pp<-b[[ds]]$tuned_xgboost
 z<-qlogis(pmin(pmax(pp,1e-6),1-1e-6));bas<-splines::ns(z,df=3)
 grid<-seq(quantile(pp,.01),quantile(pp,.99),length.out=80)
 xx<-cbind(1,bas);gx<-cbind(1,predict(bas,qlogis(grid)))
 fitcurve<-function(ix) {
  fit<-suppressWarnings(glm.fit(xx[ix,,drop=FALSE],yy[ix],family=binomial()))
  if(!isTRUE(fit$converged)||any(!is.finite(fit$coefficients)))return(rep(NA_real_,length(grid)))
  plogis(drop(gx%*%fit$coefficients))
 }
 grp<-if(ds=='external')dat$hospital else dat$subject_id
 bl<-unname(split(seq_along(yy),grp));set.seed(20261008)
 vals<-replicate(1000,fitcurve(unlist(bl[sample.int(length(bl),length(bl),TRUE)],use.names=FALSE)))
 curves[[ds]]<-data.frame(dataset=ds,predicted=grid,observed=fitcurve(seq_along(yy)),lower=apply(vals,1,quantile,.025,na.rm=TRUE),upper=apply(vals,1,quantile,.975,na.rm=TRUE),valid_replicates=rowSums(is.finite(vals)),replicates=1000)
}
write.csv(bind_rows(curves),file.path(out,'smooth_calibration.csv'),row.names=FALSE)
