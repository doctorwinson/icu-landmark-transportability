"""Raw-source predictor queries. Every returned numeric measurement carries both times."""

MIMIC_COHORT = """with ranked as (
 select i.*, row_number() over(partition by i.subject_id order by i.intime,i.stay_id) as rn
 from mimiciv_icu.icustays i)
select i.subject_id,i.hadm_id,i.stay_id,i.intime,i.outtime,a.admittime,a.dischtime,a.deathtime,
 p.gender,a.race,least(90,p.anchor_age+extract(year from i.intime)::integer-p.anchor_year) as age
from ranked i join mimiciv_hosp.patients p using(subject_id)
join mimiciv_hosp.admissions a using(hadm_id)
where i.rn=1 and p.anchor_age+extract(year from i.intime)::integer-p.anchor_year>=18
 and i.outtime>=i.intime+interval '24h'
 and (a.deathtime is null or a.deathtime>i.intime+interval '24h')
order by i.intime,i.stay_id"""

EICU_COHORT = """with ranked as (
 select *,row_number() over(partition by patienthealthsystemstayid
   order by -hospitaladmitoffset,patientunitstayid) as rn
 from eicu_icu.patient)
select patientunitstayid as stay_id,patienthealthsystemstayid as hadm_id,uniquepid,gender,ethnicity as race,
 case when age like '>%%' then 90 when age ~ '^[0-9]+$' then least(90,age::integer) end as age,
 hospitaladmitoffset,hospitaldischargeoffset,unitdischargeoffset,hospitaldischargeyear,
 hospitaldischargestatus,admissionheight,admissionweight
from ranked where rn=1 and (case when age like '>%%' then 90
 when age ~ '^[0-9]+$' then age::integer else null end)>=18
 and unitdischargeoffset>=1440
 and (hospitaldischargestatus is distinct from 'Expired' or hospitaldischargeoffset>1440)
order by patientunitstayid"""

M_CHART_MAP = {
220045:('heart_rate',1,0),220050:('sbp',1,0),220179:('sbp',1,0),
220051:('dbp',1,0),220180:('dbp',1,0),220052:('map',1,0),220181:('map',1,0),
220210:('resp_rate',1,0),224690:('resp_rate',1,0),220277:('spo2',1,0),
223761:('temp',5/9,-32*5/9),223762:('temp',1,0),
226512:('weight',1,0),224639:('weight',1,0),226531:('weight',0.45359237,0),
226730:('height',1,0),226707:('height',2.54,0),
220739:('gcs_eye',1,0),223900:('gcs_verbal',1,0),223901:('gcs_motor',1,0)
}
M_LAB_MAP = {50820:'ph',50882:'hco3',50813:'lactate',50912:'creatinine',51006:'bun',
             51301:'wbc',51222:'hemoglobin',51265:'platelet',51237:'inr',50885:'tbil',
             50821:'pao2',50816:'fio2'}
E_LAB_MAP = {'pH':'ph','bicarbonate':'hco3','lactate':'lactate','creatinine':'creatinine',
             'BUN':'bun','WBC x 1000':'wbc','Hgb':'hemoglobin','platelets x 1000':'platelet',
             'PT - INR':'inr','total bilirubin':'tbil','paO2':'pao2','FiO2':'fio2'}
E_NURSING_MAP = [('Glasgow coma score','GCS Total','gcs',1,0),
 ('Score (Glasgow Coma Scale)','Value','gcs',1,0),
 ('Temperature','Temperature (C)','temp',1,0)]

def values(mapping):
 return ','.join("(%s,'%s',%.12g,%.12g)"%(key,*val) for key,val in mapping.items())

M_CHART = """with mapping(itemid,variable,multiplier,addition) as (values %s)
select ce.stay_id,mp.variable,ce.valuenum*mp.multiplier+mp.addition as value,
 extract(epoch from (ce.charttime-i.intime))/60 as minute,
 case when ce.storetime is not null then greatest(extract(epoch from (ce.storetime-i.intime))/60,
  extract(epoch from (ce.charttime-i.intime))/60) end as available_minute,
 ce.itemid::text as source,ce.charttime::text||':'||ce.itemid::text as record_key
from mimiciv_icu.chartevents ce join mimiciv_icu.icustays i using(stay_id)
join mapping mp using(itemid)
where ce.stay_id=any(%%s) and ce.charttime between i.intime and i.intime+interval '24h'
 and ce.valuenum is not null""" % values(M_CHART_MAP)

M_LAB = """with mapping(itemid,variable) as (values %s)
select i.stay_id,mp.variable,le.valuenum as value,
 extract(epoch from (le.charttime-i.intime))/60 as minute,
 case when le.storetime is not null then greatest(extract(epoch from (le.storetime-i.intime))/60,
  extract(epoch from (le.charttime-i.intime))/60) end as available_minute,
 le.itemid::text as source,le.labevent_id::text as record_key
from mimiciv_hosp.labevents le join mimiciv_icu.icustays i on le.hadm_id=i.hadm_id
join mapping mp using(itemid)
where i.stay_id=any(%%s) and le.charttime between i.intime and i.intime+interval '24h'
 and le.valuenum is not null""" % ','.join("(%s,'%s')"%v for v in M_LAB_MAP.items())

M_URINE = """select oe.stay_id,'urine' as variable,
 case when oe.itemid=227488 then -oe.value else oe.value end as value,
 extract(epoch from (oe.charttime-i.intime))/60 as minute,
 case when oe.storetime is not null then greatest(extract(epoch from (oe.storetime-i.intime))/60,
 extract(epoch from (oe.charttime-i.intime))/60) end as available_minute,
 oe.itemid::text as source,oe.charttime::text||':'||oe.itemid::text as record_key
from mimiciv_icu.outputevents oe join mimiciv_icu.icustays i using(stay_id)
where oe.stay_id=any(%s) and oe.charttime between i.intime and i.intime+interval '24h'
 and oe.itemid in (226559,226560,226561,226584,226563,226564,226565,226567,226557,226558,227488,227489)
 and oe.value>=0"""

E_LAB = """with mapping(labname,variable) as (values %s)
select le.patientunitstayid as stay_id,mp.variable,le.labresult as value,
 le.labresultoffset::numeric as minute,
 case when le.labresultrevisedoffset is not null then greatest(le.labresultoffset,le.labresultrevisedoffset)::numeric end as available_minute,
 le.labname as source,le.labid::text as record_key
from eicu_icu.lab le join mapping mp using(labname)
where le.patientunitstayid=any(%%s) and le.labresultoffset between 0 and 1440
 and le.labresult is not null""" % ','.join("('%s','%s')"%v for v in E_LAB_MAP.items())

E_NURSING = """with mapping(label,name,variable,multiplier,addition) as (values %s)
select n.patientunitstayid as stay_id,m.variable,
 case when trim(n.nursingchartvalue) ~ '^[+-]?[0-9]+(\\.[0-9]+)?$'
 then trim(n.nursingchartvalue)::numeric*m.multiplier+m.addition end as value,
 n.nursingchartoffset::numeric as minute,greatest(n.nursingchartoffset,n.nursingchartentryoffset)::numeric as available_minute,
 n.nursingchartcelltypevalname as source,n.nursingchartid::text as record_key
from eicu_icu.nursecharting n join mapping m
 on n.nursingchartcelltypevallabel=m.label and n.nursingchartcelltypevalname=m.name
where n.patientunitstayid=any(%%s) and n.nursingchartoffset between 0 and 1440""" % ','.join("('%s','%s','%s',%.12g,%.12g)"%v for v in E_NURSING_MAP)

E_VITAL = """select p.patientunitstayid as stay_id,v.variable,v.value,
 p.observationoffset::numeric as minute,p.observationoffset::numeric as available_minute,
 'vitalperiodic_no_separate_entry_timestamp' as source,p.vitalperiodicid::text as record_key
from eicu_icu.vitalperiodic p cross join lateral(values
 ('heart_rate',p.heartrate::numeric),('resp_rate',p.respiration::numeric),('spo2',p.sao2::numeric),
 ('sbp',p.systemicsystolic::numeric),('dbp',p.systemicdiastolic::numeric),('map',p.systemicmean::numeric)) v(variable,value)
where p.patientunitstayid=any(%s) and p.observationoffset between 0 and 1440 and v.value is not null
union all
select p.patientunitstayid,v.variable,v.value,p.observationoffset,p.observationoffset,
 'vitalaperiodic_no_separate_entry_timestamp',p.vitalaperiodicid::text
from eicu_icu.vitalaperiodic p cross join lateral(values
 ('sbp',p.noninvasivesystolic::numeric),('dbp',p.noninvasivediastolic::numeric),('map',p.noninvasivemean::numeric)) v(variable,value)
where p.patientunitstayid=any(%s) and p.observationoffset between 0 and 1440 and v.value is not null"""

LIMITS = {'heart_rate':(1,300),'resp_rate':(1,100),'spo2':(1,100),'sbp':(20,300),
 'dbp':(10,200),'map':(10,250),'temp':(25,45),'weight':(20,400),'height':(100,250),
 'gcs_eye':(1,4),'gcs_verbal':(1,5),'gcs_motor':(1,6),'gcs':(3,15),'ph':(6.5,8.0),
 'hco3':(1,60),'lactate':(0,50),'creatinine':(0.1,30),'bun':(0,300),'wbc':(0,500),
 'hemoglobin':(1,25),'platelet':(0,2000),'inr':(0.3,30),'tbil':(0,100),'pao2':(10,800),
 'fio2':(.21,100),'urine':(-10000,10000)}
