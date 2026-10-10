"""Build a timestamp-audited raw predictor layer, with no bdmcc dependency.

This stage deliberately does not certify the infection/organ-support cohort.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import os
import pandas as pd
import numpy as np
import psycopg2
import raw_feature_queries as Q

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[1]/'data/raw_timestamp_rebuild_20261006'
DATA.mkdir(parents=True,exist_ok=True)
AUDIT=HERE/'raw_feature_audit';AUDIT.mkdir(exist_ok=True)
SQL=HERE/'sql';SQL.mkdir(exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--source',choices=['mimic','eicu','both'],default='both')
args=parser.parse_args()

def aggregate_sql(query):
    bounds=','.join("('%s',%s,%s)"%(k,*v) for k,v in Q.LIMITS.items())
    return """with raw as (%s), bounds(variable,low,high) as (values %s), checked as (
      select r.*, r.value between b.low and b.high as valid,
        r.available_minute between r.minute and 1440 as in_time
      from raw r join bounds b using(variable))
      select stay_id,variable,count(*) as n_raw,
        count(*) filter(where valid and in_time) as n_used,
        count(*) filter(where valid and available_minute>1440) as n_late,
        count(*) filter(where valid and available_minute is null) as n_unknown_time,
        count(*) filter(where not valid or value is null) as n_invalid,
        (array_agg(value order by minute,available_minute,source,record_key) filter(where valid and in_time))[1] as first_value,
        min(value) filter(where valid and in_time) as min_value,
        max(value) filter(where valid and in_time) as max_value,
        sum(value) filter(where valid and in_time) as sum_value,
        min(minute) filter(where valid and in_time) as first_measurement_minute,
        max(minute) filter(where valid and in_time) as last_measurement_minute,
        max(available_minute) filter(where valid and in_time) as last_available_minute,
        bool_or(source like '%%%%no_separate_entry_timestamp%%%%') as observation_time_proxy
      from checked group by stay_id,variable order by stay_id,variable"""%(query,bounds)

def fetch(c,name,query,ids=None):
    sql=aggregate_sql(query) if name.endswith('_features') else query
    assert not re.search(r'\b(create|drop|insert|update|delete|alter|truncate)\b',re.sub(r'--[^\n]*','',sql),re.I)
    (SQL/(name+'.sql')).write_text(sql+';\n',encoding='utf-8')
    print(name,flush=True)
    with c.cursor() as cur:
        cur.execute(sql,tuple([ids]*sql.count('%s')) if ids is not None else None)
        frame=pd.DataFrame(cur.fetchall(),columns=[x.name for x in cur.description])
    for col in frame:
        if frame[col].dtype=='object' and len(frame[col].dropna()) and type(frame[col].dropna().iloc[0]).__name__=='Decimal':
            frame[col]=pd.to_numeric(frame[col])
    frame.to_parquet(DATA/(name+'.parquet'),index=False)
    print(name,'rows',len(frame),flush=True)
    return frame

def vendor_urine():
    path=HERE/'source_audit/eicu_pivoted_uo_upstream.sql'
    if not path.exists():
        raise FileNotFoundError('Restore the reviewed upstream SQL snapshot; see THIRD_PARTY_NOTICES.md')
    source=path.read_text(encoding='utf-8')
    # Reuse the published path classification, not its downstream aggregation.
    match=re.search(r'(case\s+when.*?end)\s+as cellpath_is_uo',source,re.S|re.I)
    if not match:raise ValueError('Upstream UO structure changed; review before use')
    case=match.group(1).replace('%','%%')
    return """select patientunitstayid as stay_id,'urine' as variable,cellvaluenumeric as value,
      intakeoutputoffset::numeric as minute,greatest(intakeoutputoffset,intakeoutputentryoffset)::numeric as available_minute,
      cellpath as source,intakeoutputid::text as record_key
      from eicu_icu.intakeoutput where patientunitstayid=any(%s)
        and intakeoutputoffset between 0 and 1440 and cellvaluenumeric>=0
        and ("""+case+")=1"

M_GCS="""with x as (select ce.stay_id,ce.charttime,ce.itemid,min(ce.valuenum) as value,
 max(greatest(ce.charttime,ce.storetime)) as available_time
 from mimiciv_icu.chartevents ce join mimiciv_icu.icustays i using(stay_id)
 where ce.stay_id=any(%s) and ce.charttime between i.intime and i.intime+interval '24h'
 and ce.storetime is not null and ce.storetime<=i.intime+interval '24h'
 and ((ce.itemid=220739 and ce.valuenum between 1 and 4)
   or (ce.itemid=223900 and ce.valuenum between 1 and 5)
   or (ce.itemid=223901 and ce.valuenum between 1 and 6))
 group by ce.stay_id,ce.charttime,ce.itemid), g as (
 select stay_id,charttime,sum(value) as value,max(available_time) as available_time
 from x group by stay_id,charttime having count(distinct itemid)=3)
 select g.stay_id,'gcs' as variable,g.value,
 extract(epoch from(g.charttime-i.intime))/60 as minute,
 extract(epoch from(g.available_time-i.intime))/60 as available_minute,
 'three_same_time_gcs_components' as source,g.charttime::text as record_key
 from g join mimiciv_icu.icustays i using(stay_id)"""

for name,db in [('mimic','mimic4_v22'),('eicu','eicu')]:
    if args.source not in ['both',name]:continue
    if (AUDIT/(name+'_complete.json')).exists():
        raise SystemExit(name+' already completed; do not overwrite a frozen extraction')
    c=psycopg2.connect(host=os.getenv('PGHOST','localhost'),port=int(os.getenv('PGPORT','5432')),
                       user=os.environ['PGUSER'],dbname=os.getenv(name.upper()+'_DB',db),connect_timeout=5,
                       application_name='study1_timestamp_raw_features')
    c.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
    try:
        with c.cursor() as cur:
            cur.execute("set local statement_timeout='30min'")
            cur.execute("set local work_mem='128MB'")
            cur.execute('show transaction_read_only');assert cur.fetchone()[0]=='on'
        cohort=fetch(c,name+'_raw_candidates',Q.MIMIC_COHORT if name=='mimic' else Q.EICU_COHORT)
        ids=cohort.stay_id.astype(int).tolist()
        queries={'chart':Q.M_CHART,'lab':Q.M_LAB,'urine':Q.M_URINE,'gcs':M_GCS} if name=='mimic' else {
            'lab':Q.E_LAB,'nursing':Q.E_NURSING,'vital':Q.E_VITAL,'urine':vendor_urine()}
        chunks=[fetch(c,name+'_'+key+'_features',query,ids) for key,query in queries.items()]
        long=pd.concat(chunks,ignore_index=True)
        assert not long.duplicated(['stay_id','variable']).any()
        used=long[long.n_used>0]
        assert used.last_available_minute.le(1440).all()
        assert used.first_measurement_minute.ge(0).all()
        assert used.last_measurement_minute.le(1440).all()
        base=cohort.set_index('stay_id').copy()
        wanted=['heart_rate','sbp','dbp','map','resp_rate','spo2','temp','ph','hco3','lactate',
                'creatinine','bun','wbc','hemoglobin','platelet','inr','tbil']
        for variable in wanted:
            part=long[long.variable==variable].set_index('stay_id')
            prefix=('vs_24h_' if variable in wanted[:7] else 'lab_24h_')+variable
            for field,stat in [('first','first_value'),('min','min_value'),('max','max_value')]:
                base[prefix+'_'+field]=part[stat].reindex(base.index)
            base[prefix+'_measured_by24']=part.n_used.gt(0).reindex(base.index,fill_value=False).astype(int)
        gcs=long[long.variable=='gcs'].set_index('stay_id')
        base['gcs']=gcs.min_value.reindex(base.index)
        urine=long[long.variable=='urine'].set_index('stay_id')
        base['urine_output_24h']=urine.sum_value.reindex(base.index)
        base.loc[base.urine_output_24h<0,'urine_output_24h']=np.nan
        base['gcs_measured_by24']=base.gcs.notna().astype(int)
        base['urine_measured_by24']=base.urine_output_24h.notna().astype(int)
        if name=='mimic':
            wt=long[long.variable=='weight'].set_index('stay_id').first_value
            ht=long[long.variable=='height'].set_index('stay_id').first_value
            base['bmi_audit_only']=wt.reindex(base.index)/(ht.reindex(base.index)/100)**2
            base.loc[~base.bmi_audit_only.between(5,100),'bmi_audit_only']=np.nan
        else:
            base['bmi_audit_only']=base.admissionweight/(base.admissionheight/100)**2
            base.loc[~base.bmi_audit_only.between(5,100),'bmi_audit_only']=np.nan
        base.reset_index().to_parquet(DATA/(name+'_raw_predictors.parquet'),index=False)
        long.to_parquet(DATA/(name+'_feature_lineage.parquet'),index=False)
        quality=long.groupby('variable')[['n_raw','n_used','n_late','n_unknown_time','n_invalid']].sum()
        quality.to_csv(AUDIT/(name+'_timing_quality.csv'))
        jsonout={'status':'PREDICTOR_LAYER_ONLY_NOT_FINAL_SEPSIS_COHORT','database':db,'read_only':True,
                 'raw_candidate_stays':len(base),'used_source_tables_only':True,
                 'bmi_observed':int(base.bmi_audit_only.notna().sum()),
                 'bmi_primary_predictor':False,'charlson_primary_predictor':False,'legacy_tags_used':False,
                 'first24_observation_and_available_time_checks_pass':True,
                 'eicu_monitor_entry_time_known':False if name=='eicu' else None,
                 'sql_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SQL.glob(name+'*.sql')},
                 'files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob(name+'*.parquet')}}
        (AUDIT/(name+'_complete.json')).write_text(json.dumps(jsonout,indent=2),encoding='utf-8')
        print(json.dumps(jsonout),flush=True)
    finally:
        c.rollback();c.close()
