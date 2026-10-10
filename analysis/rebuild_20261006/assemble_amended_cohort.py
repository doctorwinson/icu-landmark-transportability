"""Assemble the explicitly amended record-based sepsis cohorts from raw layers."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[1]/'data/raw_timestamp_rebuild_20261006'
OUT=HERE.parents[1]/'data/amended_cohort_20261006'
OUT.mkdir(exist_ok=True)
AUDIT=HERE/'cohort_audit';AUDIT.mkdir(exist_ok=True)

def grade_low(x,mild,severe):
    return pd.Series(np.select([x<severe,x<mild],[2,1],default=0),index=x.index)
def grade_high(x,mild,severe):
    return pd.Series(np.select([x>=severe,x>=mild],[2,1],default=0),index=x.index)

report={}
feature_columns=None
for name in ['mimic','eicu']:
    for suffix in ['raw_predictors','infection_evidence','support_evidence','pf_ratio']:
        if not (DATA/(name+'_'+suffix+'.parquet')).exists():raise SystemExit('Missing layer: '+name+'_'+suffix)
    df=pd.read_parquet(DATA/(name+'_raw_predictors.parquet')).set_index('stay_id')
    inf=pd.read_parquet(DATA/(name+'_infection_evidence.parquet')).set_index('stay_id')
    ev=pd.read_parquet(DATA/(name+'_support_evidence.parquet'))
    pf=pd.read_parquet(DATA/(name+'_pf_ratio.parquet')).set_index('stay_id')
    df['pf_ratio_audit']=pf.pf_ratio.reindex(df.index)
    df['infection_flag']=inf['paired_with_order_known_by24' if name=='mimic' else 'documented_sepsis_by24'].reindex(df.index).fillna(False)
    df['baseline_support']=False
    for kind in ['vaso','imv','rrt']:
        q=ev[ev.kind==kind]
        prior=q[(q.start_minute<=1440)&(q.end_minute>=0)].stay_id.unique()
        df.loc[df.index.isin(prior),'baseline_support']=True
        first=q[q.start_minute>1440].groupby('stay_id').start_minute.min()
        df[kind+'_7d_post_window']=df.index.isin(first.index).astype(int)
    dobutamine=ev[(ev.kind=='dobutamine')&(ev.start_minute<=1440)&(ev.end_minute>=0)].stay_id.unique()
    # Truncation at 2 preserves the binary SOFA>=2 threshold but not the full score.
    org=pd.DataFrame(index=df.index)
    org['respiration']=grade_low(df.pf_ratio_audit,400,300)
    org['coagulation']=grade_low(df.lab_24h_platelet_min,150,100)
    org['liver']=grade_high(df.lab_24h_tbil_max,1.2,2)
    org['cardiovascular']=(df.vs_24h_map_min<70).astype(int)
    org.loc[df.index.isin(dobutamine),'cardiovascular']=2
    vaso_before24=ev[(ev.kind=='vaso')&(ev.start_minute<=1440)&(ev.end_minute>=0)].stay_id.unique()
    org.loc[df.index.isin(vaso_before24),'cardiovascular']=2
    org['cns']=grade_low(df.gcs,15,13)
    org['renal']=grade_high(df.lab_24h_creatinine_max,1.2,2)
    org_without_urine=org.copy()
    org.loc[df.urine_output_24h<500,'renal']=2
    df['observed_organ_dysfunction_ge2']=org.sum(axis=1)>=2
    df['organ_screen_without_urine']=org_without_urine.sum(axis=1)>=2
    if name=='mimic':
        df['index_time']=df.intime
        df['uniquepid']=df.subject_id.astype(str)
        df['death_7d_post_window']=((df.deathtime>df.intime+pd.Timedelta(hours=24)) &
                                   (df.deathtime<=df.intime+pd.Timedelta(hours=192))).astype(int)
    else:
        anchor=pd.Timestamp('2000-01-01')
        df['index_time']=anchor;df['intime']=anchor
        df['outtime']=anchor+pd.to_timedelta(df.unitdischargeoffset,unit='m')
        df['admittime']=anchor+pd.to_timedelta(df.hospitaladmitoffset,unit='m')
        df['death_7d_post_window']=((df.hospitaldischargestatus=='Expired') &
                                   (df.hospitaldischargeoffset>1440)&(df.hospitaldischargeoffset<=11520)).astype(int)
    components=['vaso_7d_post_window','imv_7d_post_window','rrt_7d_post_window','death_7d_post_window']
    df['composite_deterioration_7d']=df[components].max(axis=1)
    chosen=df[df.infection_flag & df.observed_organ_dysfunction_ge2 & ~df.baseline_support].copy()
    chosen['window_end']=chosen.intime+pd.Timedelta(hours=24)
    chosen['completed_window']=1;chosen['support_free_during_window']=1
    race=chosen.race.fillna('').str.upper()
    chosen['race']=np.select([race.str.contains('WHITE|CAUCASIAN'),race.str.contains('BLACK|AFRICAN'),
      race.str.contains('ASIAN'),race.str.contains('HISPANIC|LATINO'),
      race.str.contains('UNKNOWN|UNABLE|DECLIN|UNOBTAIN')|race.eq('')],
      ['White','Black','Asian','Hispanic','Unknown'],default='Other')
    sex=chosen.gender.fillna('').str.upper()
    chosen['gender']=np.select([sex.isin(['M','MALE']),sex.isin(['F','FEMALE'])],['Male','Female'],default='Unknown')
    assert not chosen.index.duplicated().any() and len(chosen)>0
    assert (chosen.outtime>=chosen.window_end).all()
    cols=['age','gender','race','gcs','urine_output_24h','gcs_measured_by24','urine_measured_by24']
    cols += [x for x in chosen if x.startswith(('vs_24h_','lab_24h_'))]
    if feature_columns is None:feature_columns=cols
    assert cols==feature_columns
    # The full audit frame is retained locally; the model uses the explicit whitelist.
    filename='study1_bdmcc24_dataset.parquet' if name=='mimic' else 'study1_eicu_bdmcc24_dataset.parquet'
    chosen.reset_index().to_parquet(OUT/filename,index=False)
    if name=='mimic':assert chosen.subject_id.is_unique
    report[name]={'raw_candidates':len(df),'infection_by24':int(df.infection_flag.sum()),
       'infection_and_observed_organ_dysfunction':int((df.infection_flag&df.observed_organ_dysfunction_ge2).sum()),
       'final_n':len(chosen),'unique_patients':chosen.uniquepid.nunique(),
       'excluded_early_support_after_infection_organ_screen':int((df.infection_flag&df.observed_organ_dysfunction_ge2&df.baseline_support).sum()),
       'events':{x:int(chosen[x].sum()) for x in components+['composite_deterioration_7d']},
       'pf_ratio_nonmissing':int(chosen.pf_ratio_audit.notna().sum()),
       'urine_nonmissing':int(chosen.urine_output_24h.notna().sum()),
       'bmi_audit_observed':int(chosen.bmi_audit_only.notna().sum()),
       'eligible_without_urine_screen':int(chosen.organ_screen_without_urine.sum()),
       'data_sha256':hashlib.sha256((OUT/filename).read_bytes()).hexdigest()}
    org.loc[chosen.index].reset_index().to_parquet(OUT/(name+'_organ_screen_audit.parquet'),index=False)
    sources=ev[ev.stay_id.isin(chosen.index)].groupby(['kind','source']).agg(
        records=('stay_id','size'),stays=('stay_id','nunique'))
    sources.to_csv(AUDIT/(name+'_support_sources.csv'))
    chosen[cols].isna().mean().rename('missing_fraction').to_csv(AUDIT/(name+'_predictor_missingness.csv'))
    print(name,json.dumps(report[name]),flush=True)
(AUDIT/'cohort_counts.json').write_text(json.dumps(report,indent=2,default=int),encoding='utf-8')
(HERE/'feature_whitelist.json').write_text(json.dumps(feature_columns,indent=2),encoding='utf-8')
assert not any(x in feature_columns for x in ['bmi','bmi_audit_only','weight','charlson','sepsis_to_icu_hours','observed_organ_dysfunction_ge2'])
assert not any(x.endswith('_tag') or x.startswith('icd_') for x in feature_columns)
(AUDIT/'status.json').write_text(json.dumps({'status':'AMENDED_RECORD_BASED_COHORT_REQUIRES_CLINICAL_REVIEW',
  'protocol_sha256':hashlib.sha256((HERE/'PROTOCOL_AMENDMENT.md').read_bytes()).hexdigest(),
  'raw_predictor_count':len(feature_columns),'no_bdmcc_tables':True,
  'infection_definitions_nonidentical':True,'bmi_charlson_legacy_tags_excluded':True},indent=2),encoding='utf-8')
