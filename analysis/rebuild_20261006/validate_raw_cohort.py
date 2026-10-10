"""Fail-fast, aggregate-only QC and a pre-fit input/source freeze manifest."""
from pathlib import Path
import hashlib
import itertools
import os
import json
import pandas as pd
import numpy as np
import psycopg2
import raw_feature_queries as Q

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
RAW=ROOT/'data/raw_timestamp_rebuild_20261006'
DATA=ROOT/'data/amended_cohort_20261006'
OUT=HERE/'cohort_audit'
features=json.loads((HERE/'feature_whitelist.json').read_text())
assert len(features)==len(set(features))==75
for s in itertools.product(range(5),repeat=6):
 assert (sum(s)>=2)==(sum(min(x,2) for x in s)>=2)
checks={}
for name,filename in [('mimic','study1_bdmcc24_dataset.parquet'),('eicu','study1_eicu_bdmcc24_dataset.parquet')]:
 d=pd.read_parquet(DATA/filename).set_index('stay_id')
 l=pd.read_parquet(RAW/(name+'_feature_lineage.parquet'))
 ev=pd.read_parquet(RAW/(name+'_support_evidence.parquet'))
 raw=pd.read_parquet(RAW/(name+'_raw_candidates.parquet')).set_index('stay_id')
 assert d.index.is_unique and set(d.index)<=set(raw.index)
 assert d.infection_flag.all() and d.observed_organ_dysfunction_ge2.all() and (~d.baseline_support).all()
 assert all(x in d for x in features)
 assert not np.isinf(d[[x for x in features if x not in ['gender','race']]].to_numpy(dtype=float)).any()
 used=l[l.stay_id.isin(d.index)&(l.n_used>0)]
 assert used.first_measurement_minute.ge(0).all()
 assert used.last_measurement_minute.le(1440).all()
 assert used.last_available_minute.le(1440).all()
 assert used.last_available_minute.ge(used.last_measurement_minute).all()
 for key in ['vaso','imv','rrt']:
  z=ev[(ev.kind==key)&ev.stay_id.isin(d.index)]
  assert not ((z.start_minute<=1440)&(z.end_minute>=0)).any()
  assert (z.start_minute<=11520).all()
  assert d[key+'_7d_post_window'].sum()==z.stay_id.nunique()
 parts=['vaso_7d_post_window','imv_7d_post_window','rrt_7d_post_window','death_7d_post_window']
 assert d.composite_deterioration_7d.equals(d[parts].max(axis=1))
 assert ((d[parts].sum(axis=1)>0)==(d.composite_deterioration_7d==1)).all()
 if name=='mimic':assert d.subject_id.is_unique
 wanted=['heart_rate','sbp','dbp','map','resp_rate','spo2','temp','ph','hco3','lactate','creatinine','bun','wbc','hemoglobin','platelet','inr','tbil']
 for variable in wanted:
  prefix=('vs_24h_' if variable in wanted[:7] else 'lab_24h_')+variable
  valid=d[prefix+'_first'].notna()
  assert (valid.astype(int)==d[prefix+'_measured_by24']).all()
  assert (d.loc[valid,prefix+'_min']<=d.loc[valid,prefix+'_first']).all()
  assert (d.loc[valid,prefix+'_first']<=d.loc[valid,prefix+'_max']).all()
 checks[name]={'n':len(d),'passed':True,'baseline_support_records_remaining':0,
  'predictor_records_after_landmark_used':0,'outcome_components_overlap_allowed':True,
  'no_urine_screen_n':int(d.organ_screen_without_urine.sum()),
  'no_urine_screen_events':int(d.loc[d.organ_screen_without_urine,'composite_deterioration_7d'].sum()),
  'entry_time_proxy_records':int(used.loc[used.observation_time_proxy,'n_used'].sum()),
  'bmi_is_audit_only':True}

# Check every mapped chart/lab ID against this installation's dictionary.
c=psycopg2.connect(host=os.getenv('PGHOST','localhost'),port=int(os.getenv('PGPORT','5432')),
                  user=os.environ['PGUSER'],dbname=os.getenv('MIMIC_DB','mimic4_v22'),application_name='study1_dictionary_QC')
c.set_session(readonly=True,autocommit=False)
try:
 with c.cursor() as cur:
  cur.execute('select itemid,label from mimiciv_icu.d_items where itemid=any(%s)',(list(Q.M_CHART_MAP),))
  chart=[dict(zip(['itemid','label'],r)) for r in cur.fetchall()]
  cur.execute('select itemid,label from mimiciv_hosp.d_labitems where itemid=any(%s)',(list(Q.M_LAB_MAP)+[52033],))
  lab=[dict(zip(['itemid','label'],r)) for r in cur.fetchall()]
finally:c.rollback();c.close()
(HERE/'source_audit/used_mimic_item_dictionary.json').write_text(json.dumps({'chart':chart,'lab':lab},indent=2),encoding='utf-8')
chart_ids={int(r['itemid']) for r in chart};lab_ids={int(r['itemid']) for r in lab}
assert set(Q.M_CHART_MAP)<=chart_ids
assert set(Q.M_LAB_MAP)<=lab_ids
assert 52033 in lab_ids
entries=json.loads((HERE/'source_audit/eicu_entry_missing.json').read_text())
assert all(x['missing_entry']==0 for x in entries)
files=list(HERE.glob('*.py'))+list((HERE/'R').glob('*'))+list((HERE/'sql').glob('*.sql'))
files += [HERE/'PROTOCOL_AMENDMENT.md',HERE/'feature_whitelist.json']
files += list(DATA.glob('*.parquet'))+list(RAW.glob('*.parquet'))
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
(OUT/'prefit_qc.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
(OUT/'prefit_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(checks,indent=2))
print('PASS: time boundaries, event reconciliation, predictor whitelist, source IDs and capped-score threshold equivalence.')
