"""Read-only reconstruction of infection evidence with explicit source differences."""
from pathlib import Path
import json
import re
import hashlib
import os
import pandas as pd
import psycopg2

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[1]/'data/raw_timestamp_rebuild_20261006'
AUDIT=HERE/'inclusion_audit';AUDIT.mkdir(exist_ok=True)
SQL=HERE/'sql';SQL.mkdir(exist_ok=True)
source=HERE/'source_audit/mimic_antibiotic_upstream.sql'
url='https://raw.githubusercontent.com/MIT-LCP/mimic-code/main/mimic-iv/concepts/medication/antibiotic.sql'
if not source.exists():
    raise FileNotFoundError('Restore the reviewed upstream SQL snapshot; see THIRD_PARTY_NOTICES.md')
patterns=re.findall(r"LOWER\(drug\) LIKE '([^']+)'",source.read_text(),re.I)
assert len(patterns)>50
antibiotic="lower(pr.drug) ~ '"+'|'.join(re.escape(p.strip('%')).replace("'","''") for p in sorted(set(patterns)))+"'"

M="""with candidate as (select * from mimiciv_icu.icustays where stay_id=any(%s)),
 abx as (
 select distinct c.stay_id,pr.starttime,po.ordertime,c.intime,
   po.ordertime is not null and po.ordertime<=c.intime+interval '24h' as order_known_by24
 from candidate c join mimiciv_hosp.prescriptions pr using(hadm_id)
 left join mimiciv_hosp.poe po on po.poe_id=pr.poe_id and po.poe_seq=pr.poe_seq
 where pr.starttime between c.intime-interval '78h' and c.intime+interval '24h'
 and pr.drug_type is distinct from 'BASE'
 and pr.route is not null and upper(pr.route) not in ('OU','OS','OD','AU','AS','AD','TP','TOP','OPHTH','OTIC')
 and lower(pr.route) !~ '(ear|eye)'
 and lower(pr.drug) !~ '(cream|desensitization|ophth oint|gel)'
 and ("""+antibiotic+""")), cultures as (
 select distinct c.stay_id,m.charttime from candidate c join mimiciv_hosp.microbiologyevents m using(hadm_id)
 where m.charttime between c.intime-interval '78h' and c.intime+interval '24h'
 and lower(m.test_name) like '%%culture%%' and lower(m.test_name) not like '%%screen%%'), pairs as (
 select a.stay_id,a.order_known_by24,a.starttime as antibiotic_time,b.charttime as culture_time,
 least(a.starttime,b.charttime) as suspicion_time,
 greatest(a.starttime,b.charttime,a.ordertime) as evidence_complete_time
 from abx a join cultures b using(stay_id)
 where ((a.starttime<=b.charttime and b.charttime<=a.starttime+interval '24h')
 or (b.charttime<a.starttime and a.starttime<=b.charttime+interval '72h'))
 and least(a.starttime,b.charttime)>=a.intime-interval '6h')
select c.stay_id,count(p.stay_id)>0 as paired_infection_events_by24,
 coalesce(bool_or(p.order_known_by24),false) as paired_with_order_known_by24,
 min(p.suspicion_time) filter(where p.order_known_by24) as infection_evidence_time,
 min(p.evidence_complete_time) filter(where p.order_known_by24) as evidence_complete_time
from candidate c left join pairs p using(stay_id) group by c.stay_id order by c.stay_id"""

E="""select p.patientunitstayid as stay_id,
 coalesce(bool_or(d.diagnosisoffset between 0 and 1440),false) as documented_sepsis_by24,
 min(d.diagnosisoffset) filter(where d.diagnosisoffset between 0 and 1440) as infection_evidence_minute
from eicu_icu.patient p left join eicu_icu.diagnosis d
 on d.patientunitstayid=p.patientunitstayid and lower(d.diagnosisstring) ~ '(sepsis|septic shock)'
 and lower(d.diagnosisstring) !~ '(rule out|ruled out|no sepsis)'
where p.patientunitstayid=any(%s) group by p.patientunitstayid order by p.patientunitstayid"""

for name,db,sql in [('mimic','mimic4_v22',M),('eicu','eicu',E)]:
    cp=DATA/(name+'_raw_candidates.parquet')
    if not cp.exists():
        print(name,'raw candidate list not yet available; rerun after predictor extraction',flush=True)
        continue
    ids=pd.read_parquet(cp).stay_id.astype(int).tolist()
    c=psycopg2.connect(host=os.getenv('PGHOST','localhost'),port=int(os.getenv('PGPORT','5432')),
                      user=os.environ['PGUSER'],dbname=os.getenv(name.upper()+'_DB',db),application_name='study1_infection_reconstruction')
    c.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
    try:
        with c.cursor() as cur:
            cur.execute("set local statement_timeout='20min'")
            cur.execute("set local enable_nestloop=off")
            cur.execute('show transaction_read_only');assert cur.fetchone()[0]=='on'
            print(name,'infection evidence query',flush=True)
            cur.execute(sql,(ids,))
            frame=pd.DataFrame(cur.fetchall(),columns=[x.name for x in cur.description])
        frame.to_parquet(DATA/(name+'_infection_evidence.parquet'),index=False)
        columns=['paired_infection_events_by24','paired_with_order_known_by24'] if name=='mimic' else ['documented_sepsis_by24']
        report=dict(database=db,read_only=True,n_raw_candidates=len(frame),
                    flags={col:int(frame[col].sum()) for col in columns},
                    status='INFECTION_EVIDENCE_ONLY_NOT_FINAL_SEPSIS_COHORT',
                    source_definition='antimicrobial-order/culture pair' if name=='mimic' else 'documented sepsis diagnosis',
                    sql_sha256=hashlib.sha256(sql.encode()).hexdigest(),
                    upstream_drug_dictionary_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        (AUDIT/(name+'_infection.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        (SQL/(name+'_infection.sql')).write_text(sql+';\n',encoding='utf-8')
        print(json.dumps(report),flush=True)
    finally:c.rollback();c.close()
