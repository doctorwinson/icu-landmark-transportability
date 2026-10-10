# R-only diagnostic figures from the revised model bundle; no old images reused.
# Contract: show discrimination, raw calibration and screening utility in the
# record-assessable cohort, without implying verified IMV onset or deployment readiness.
args<-commandArgs(FALSE)
here<-dirname(normalizePath(sub('^--file=','',args[grepl('^--file=',args)][1]),winslash='/'))
source(file.path(dirname(here),'rebuild_20261006/R/02_common.R'))
out<-file.path(here,'results');fig<-file.path(out,'figures');dir.create(fig,recursive=TRUE,showWarnings=FALSE)
base<-file.path(dirname(here),'imv_full_revision_20261007')
b<-readRDS(file.path(base,'local_only/predictions.rds'))
smooth<-read.csv(file.path(dirname(here),'manuscript_review_revision_20261007/results/smooth_calibration.csv'))
theme_set(theme_bw(base_size=10,base_family='sans')+theme(panel.grid.minor=element_blank(),plot.title=element_text(face='bold'),legend.position='bottom'))
colors<-c('Tuned XGBoost'='#285678','Ridge logistic'='#B36F35','Screen all'='#777777','Screen none'='#BBBBBB')
save_plot<-function(p,name,w=10,h=7.5){
 ggsave(file.path(fig,paste0(name,'.png')),p,width=w,height=h,dpi=320,bg='white')
 ggsave(file.path(fig,paste0(name,'.pdf')),p,width=w,height=h,device=cairo_pdf,bg='white')
}
for(ds in c('internal','external')) {
 d<-b[[paste0(ds,'_data')]];y<-d$composite_deterioration_7d;p<-b[[ds]]
 curves<-list();prs<-list();cals<-list();dc<-list()
 for(nm in c('tuned_xgboost','ridge_logistic')) {
  label<-if(nm=='tuned_xgboost')'Tuned XGBoost' else 'Ridge logistic'
  curves[[nm]]<-cbind(model=label,build_roc_curve_df(y,p[[nm]]))
  prs[[nm]]<-cbind(model=label,build_pr_curve_df(y,p[[nm]]))
  cals[[nm]]<-cbind(model=label,calibration_group_table(y,p[[nm]],groups=10))
  z<-decision_curve(y,p[[nm]],seq(.01,.5,.01));dc[[nm]]<-data.frame(threshold=z$threshold,nb=z$net_benefit_model,model=label)
 }
 dc$all<-data.frame(threshold=z$threshold,nb=z$net_benefit_all,model='Screen all')
 dc$none<-data.frame(threshold=z$threshold,nb=0,model='Screen none')
 a<-ggplot(bind_rows(curves),aes(fpr,tpr,color=model))+geom_abline(slope=1,intercept=0,linetype=2,color='grey70')+geom_line(linewidth=.7)+scale_color_manual(values=colors)+coord_cartesian(xlim=c(0,1),ylim=c(0,1))+labs(title='A  Discrimination',subtitle=sprintf('XGBoost AUROC %.3f; ridge %.3f',safe_auc(y,p$tuned_xgboost),safe_auc(y,p$ridge_logistic)),x='False-positive rate',y='True-positive rate',color=NULL)
 pr<-ggplot(bind_rows(prs),aes(recall,precision,color=model))+geom_hline(yintercept=mean(y),linetype=2,color='grey60')+geom_line(linewidth=.65)+scale_color_manual(values=colors)+coord_cartesian(xlim=c(0,1),ylim=c(0,1))+labs(title='B  Precision-recall',subtitle=sprintf('XGBoost AUPRC %.3f; prevalence %.1f%%',safe_auprc(y,p$tuned_xgboost),100*mean(y)),x='Recall',y='Precision',color=NULL)
 sc<-smooth[smooth$dataset==ds,]
 cal<-ggplot(sc,aes(predicted,observed))+geom_abline(slope=1,intercept=0,linetype=2,color='grey70')+geom_ribbon(aes(ymin=lower,ymax=upper),fill=colors[1],alpha=.18)+geom_line(color=colors[1],linewidth=.75)+geom_rug(data=data.frame(predicted=p$tuned_xgboost),aes(x=predicted),inherit.aes=FALSE,sides='b',alpha=.12)+coord_cartesian(xlim=c(0,max(sc$predicted)),ylim=c(0,min(1,max(sc$upper))))+labs(title='C  XGBoost raw calibration',subtitle='3-df spline; pointwise 95% cluster-bootstrap interval',x='Predicted risk (rug: risk distribution)',y='Estimated observed proportion')
 dd<-ggplot(bind_rows(dc),aes(threshold,nb,color=model))+geom_line(linewidth=.7)+scale_color_manual(values=colors)+labs(title='D  Decision curves',subtitle='Fixed primary/secondary thresholds: 5%, 10%, 15%',x='Threshold probability',y='Net benefit',color=NULL)
 a<-a+theme(legend.position='none');pr<-pr+theme(legend.position='none');cal<-cal+theme(legend.position='none')
 dd<-dd+guides(color=guide_legend(nrow=2))
 save_plot(dd+labs(title=NULL,subtitle=NULL),paste0(ds,'_dca_full_range'),8,5)
 # Round only for range selection so the 15% endpoint is not lost to floating-point error.
 dc_data <- bind_rows(dc)
 in_window <- round(dc_data$threshold, 8) >= .05 & round(dc_data$threshold, 8) <= .15
 dd<-dd+coord_cartesian(xlim=c(.05,.15),ylim=range(dc_data$nb[in_window]))+labs(subtitle='Illustrative thresholds only: 5% to 15%')
 plot<-(a+pr)/(cal+dd)+plot_layout(guides='collect')
 save_plot(plot,paste0(ds,'_diagnostics'))
}
imp<-read.csv(file.path(base,'results/shap_importance.csv'))
dict<-c(vs_24h_spo2='Oxygen saturation',urine_output_24h='Recorded urine output',lab_24h_bun='Blood urea nitrogen',vs_24h_resp_rate='Respiratory rate',lab_24h_creatinine='Creatinine',vs_24h_heart_rate='Heart rate',lab_24h_ph='pH',vs_24h_temp='Temperature',lab_24h_lactate='Lactate',lab_24h_platelet='Platelets',vs_24h_dbp='Diastolic blood pressure')
clinical<-function(x){x<-sub('^numeric__','',x);if(x%in%names(dict))return(unname(dict[x]));for(k in names(dict)){if(startsWith(x,paste0(k,'_'))){s<-substring(x,nchar(k)+2);s<-switch(s,min='minimum',max='maximum',first='first',measured_by24='measurement available',s);return(paste0(dict[k],' (',s,')'))}};gsub('_',' ',x)}
imp$predictor<-vapply(imp$predictor,clinical,character(1))
p<-ggplot(head(imp,15),aes(reorder(predictor,mean_abs_shap),mean_abs_shap))+geom_col(fill=colors[1])+coord_flip()+labs(x=NULL,y='Mean absolute SHAP (log-odds)')
save_plot(p,'shap_top15',10,6)
# The cohort flowchart is maintained separately from these statistical diagnostics.
