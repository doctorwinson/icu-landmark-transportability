"""Raw support-event evidence and same-sample oxygenation for the amended cohort."""
from pathlib import Path
import json
import re
import os
import argparse
import pandas as pd
import psycopg2

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[1]/'data/raw_timestamp_rebuild_20261006'
SQL=HERE/'sql';SQL.mkdir(exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--source',choices=['mimic','eicu','both'],default='both')
parser.add_argument('--only-pf',action='store_true')
args=parser.parse_args()
src=HERE/'source_audit/mimic_ventilation_upstream.sql'
if not src.exists():
 raise FileNotFoundError('Restore the reviewed upstream SQL snapshot; see THIRD_PARTY_NOTICES.md')
txt=src.read_text()
match=re.search(r'OR ventilator_mode IN\s*\((.*?)\)\s*OR ventilator_mode_hamilton IN\s*\((.*?)\)\s*THEN',txt,re.S)
assert match
regular=re.findall(r"'([^']*)'",match.group(1))
hamilton=re.findall(r"'([^']*)'",match.group(2))
quoted=lambda arr:','.join("'"+x.replace("'","''")+"'" for x in arr)
M="""with c as (select * from mimiciv_icu.icustays where stay_id=any(%s)), events as (
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime) as endtime,'vaso' as kind,'inputevents' as source
 from mimiciv_icu.inputevents r join c using(stay_id)
 where r.itemid in (221906,221289,221662,221749,222315) and r.amount>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime),'dobutamine','inputevents'
 from mimiciv_icu.inputevents r join c using(stay_id) where r.itemid=221653 and r.amount>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.charttime,r.charttime,'imv','chartevents_device_or_mode'
 from mimiciv_icu.chartevents r join c using(stay_id)
 where (r.itemid=226732 and r.value='Endotracheal tube')
   or (r.itemid=223849 and r.value in ("""+quoted(regular)+"""))
   or (r.itemid=229314 and r.value in ("""+quoted(hamilton)+"""))
 union all
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime),'rrt','procedureevents'
 from mimiciv_icu.procedureevents r join c using(stay_id)
 where r.itemid in (225441,225802,225803,225805,225809,225955) and r.value>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime),'rrt','inputevents_crrt'
 from mimiciv_icu.inputevents r join c using(stay_id) where r.itemid in (227536,227525) and r.amount>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.charttime,r.charttime,'rrt','chartevents_flow_output'
 from mimiciv_icu.chartevents r join c using(stay_id)
 where (r.itemid in (226499,224154,224191,225806,225807,228004,228005,228006,224144,224153,226457) and r.valuenum>0)
 or (r.itemid=225965 and r.value='In use'))
select r.stay_id,r.kind,r.source,
 extract(epoch from(r.starttime-c.intime))/60 as start_minute,
 extract(epoch from(r.endtime-c.intime))/60 as end_minute
from events r join c using(stay_id)
where r.starttime<=least(c.outtime,c.intime+interval '192h') and r.endtime>=c.intime"""

E="""with c as (select * from eicu_icu.patient where patientunitstayid=any(%s)), events as (
 select r.patientunitstayid,r.infusionoffset as start_minute,r.infusionoffset as end_minute,
 case when lower(r.drugname) ~ 'dobutamine' then 'dobutamine' else 'vaso' end as kind,'infusiondrug_positive_rate' as source
 from eicu_icu.infusiondrug r join c using(patientunitstayid)
 where lower(r.drugname) ~ '(norepinephrine|noradrenaline|levophed|epinephrine|adrenaline|dopamine|phenylephrine|neosynephrine|neo-synephrine|vasopressin|dobutamine)'
 and case when trim(r.drugrate) ~ '^[0-9]+(\\.[0-9]+)?$' then trim(r.drugrate)::numeric>0 else false end
 union all
 select r.patientunitstayid,r.ventstartoffset,
 case when r.ventendoffset>r.ventstartoffset then r.ventendoffset else greatest(r.ventstartoffset,r.respcarestatusoffset) end,
 'imv','respiratorycare_vent_start_with_invasive_airway'
 from eicu_icu.respiratorycare r join c using(patientunitstayid)
 where lower(trim(r.airwaytype)) in ('oral ett','nasal ett','tracheostomy','double-lumen tube','cricothyrotomy')
 and r.ventstartoffset is not null
 union all
 select r.patientunitstayid,r.priorventstartoffset,r.priorventendoffset,'imv','respiratorycare_prior_interval'
 from eicu_icu.respiratorycare r join c using(patientunitstayid)
 where lower(trim(r.airwaytype)) in ('oral ett','nasal ett','tracheostomy','double-lumen tube','cricothyrotomy')
 and r.priorventendoffset>r.priorventstartoffset
 union all
 select r.patientunitstayid,r.respchartoffset,r.respchartoffset,'imv','respiratorycharting_invasive_device_or_mode'
 from eicu_icu.respiratorycharting r join c using(patientunitstayid)
 where (r.respchartvaluelabel='Endotracheal Tube Placement' and lower(trim(r.respchartvalue)) in ('oral endotracheal','nasal endotracheal'))
 or (r.respchartvaluelabel in ('Mechanical Ventilator Mode','Ventilator Support Mode')
 and lower(trim(r.respchartvalue)) in ('ac/cmv','cmv','simv','simv+','apv','pressure control','pcv w/assist','aprv'))
 union all
 select r.patientunitstayid,r.treatmentoffset,r.treatmentoffset,'imv','treatment_explicit_controlled_ventilation_or_reintubation'
 from eicu_icu.treatment r join c using(patientunitstayid)
 where lower(trim(r.treatmentstring))='pulmonary|radiologic procedures / bronchoscopy|reintubation'
 or (split_part(lower(trim(r.treatmentstring)),'|',3)='mechanical ventilation'
 and split_part(lower(trim(r.treatmentstring)),'|',4) in
 ('assist controlled','volume controlled','pressure controlled','synchronized intermittent','volume assured'))
 union all
 select r.patientunitstayid,r.treatmentoffset,r.treatmentoffset,'rrt','treatment_dialysis'
 from eicu_icu.treatment r join c using(patientunitstayid)
 where split_part(lower(trim(r.treatmentstring)),'|',1)='renal'
 and split_part(lower(trim(r.treatmentstring)),'|',2)='dialysis'
 and split_part(lower(trim(r.treatmentstring)),'|',3) in
 ('hemodialysis','c v v h d','c v v h','c a v h d','peritoneal dialysis','sled','ultrafiltration (fluid removal only)')
 union all
 select r.patientunitstayid,r.intakeoutputoffset,r.intakeoutputoffset,'rrt','intakeoutput_dialysis_positive_cell'
 from eicu_icu.intakeoutput r join c using(patientunitstayid)
 where r.cellpath like 'flowsheet|Flowsheet Cell Labels|I&O|Dialysis (ml)|%%' and r.cellvaluenumeric>0)
select e.patientunitstayid as stay_id,e.kind,e.source,e.start_minute,e.end_minute
from events e join c using(patientunitstayid)
where e.start_minute<=least(11520,c.unitdischargeoffset) and e.end_minute>=0"""

M_PF="""with x as (
 select i.stay_id,le.specimen_id,
 min(le.valuenum) filter(where le.itemid=50821) as pao2,
 max(le.valuenum) filter(where le.itemid=50816) as fio2,
 bool_or(le.itemid=52033 and upper(trim(le.value)) in ('ART.','ARTERIAL')) as arterial
 from mimiciv_hosp.labevents le join mimiciv_icu.icustays i on le.hadm_id=i.hadm_id
 where i.stay_id=any(%s) and le.itemid in (52033,50816,50821)
 and le.charttime between i.intime and i.intime+interval '24h'
 and le.storetime is not null and le.storetime<=i.intime+interval '24h'
 group by i.stay_id,le.specimen_id)
 select stay_id,min(pao2/(case when fio2>1 then fio2/100 else fio2 end)) as pf_ratio
 from x where arterial and pao2 between 10 and 800 and (fio2 between .21 and 1 or fio2 between 21 and 100)
 group by stay_id"""
E_PF="""with x as (
 select patientunitstayid as stay_id,labresultoffset,
 min(labresult) filter(where labname='paO2') as pao2,max(labresult) filter(where labname='FiO2') as fio2
 from eicu_icu.lab where patientunitstayid=any(%s) and labname in ('paO2','FiO2')
 and labresultoffset between 0 and 1440 and labresultrevisedoffset is not null and labresultrevisedoffset<=1440
 group by patientunitstayid,labresultoffset)
 select stay_id,min(pao2/(case when fio2>1 then fio2/100 else fio2 end)) as pf_ratio
 from x where pao2 between 10 and 800 and (fio2 between .21 and 1 or fio2 between 21 and 100)
 group by stay_id"""

for name,db,support,pf in [('mimic','mimic4_v22',M,M_PF),('eicu','eicu',E,E_PF)]:
    if args.source not in ['both',name]:continue
    cp=DATA/(name+'_raw_candidates.parquet')
    if not cp.exists():raise SystemExit('Wait for raw candidate export: '+name)
    ids=pd.read_parquet(cp).stay_id.astype(int).tolist()
    c=psycopg2.connect(host=os.getenv('PGHOST','localhost'),port=int(os.getenv('PGPORT','5432')),
                      user=os.environ['PGUSER'],dbname=os.getenv(name.upper()+'_DB',db),application_name='study1_raw_support_rebuild')
    c.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
    try:
        with c.cursor() as cur:
            cur.execute("set local statement_timeout='30min'")
            cur.execute("set local enable_nestloop=off")
            cur.execute('show transaction_read_only');assert cur.fetchone()[0]=='on'
            for key,sql in [('support_evidence',support),('pf_ratio',pf)]:
                if args.only_pf and key!='pf_ratio':continue
                print(name,key,flush=True)
                (SQL/(name+'_'+key+'.sql')).write_text(sql+';\n',encoding='utf-8')
                cur.execute(sql,(ids,))
                frame=pd.DataFrame(cur.fetchall(),columns=[d.name for d in cur.description])
                for col in frame:
                    if frame[col].dtype=='object' and len(frame[col].dropna()) and type(frame[col].dropna().iloc[0]).__name__=='Decimal':frame[col]=pd.to_numeric(frame[col])
                frame.to_parquet(DATA/(name+'_'+key+'.parquet'),index=False)
                print(name,key,len(frame),flush=True)
    finally:c.rollback();c.close()
