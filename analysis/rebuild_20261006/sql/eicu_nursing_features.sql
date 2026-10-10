with raw as (with mapping(label,name,variable,multiplier,addition) as (values ('Glasgow coma score','GCS Total','gcs',1,0),('Score (Glasgow Coma Scale)','Value','gcs',1,0),('Temperature','Temperature (C)','temp',1,0))
select n.patientunitstayid as stay_id,m.variable,
 case when trim(n.nursingchartvalue) ~ '^[+-]?[0-9]+(\.[0-9]+)?$'
 then trim(n.nursingchartvalue)::numeric*m.multiplier+m.addition end as value,
 n.nursingchartoffset::numeric as minute,greatest(n.nursingchartoffset,n.nursingchartentryoffset)::numeric as available_minute,
 n.nursingchartcelltypevalname as source,n.nursingchartid::text as record_key
from eicu_icu.nursecharting n join mapping m
 on n.nursingchartcelltypevallabel=m.label and n.nursingchartcelltypevalname=m.name
where n.patientunitstayid=any(%s) and n.nursingchartoffset between 0 and 1440), bounds(variable,low,high) as (values ('heart_rate',1,300),('resp_rate',1,100),('spo2',1,100),('sbp',20,300),('dbp',10,200),('map',10,250),('temp',25,45),('weight',20,400),('height',100,250),('gcs_eye',1,4),('gcs_verbal',1,5),('gcs_motor',1,6),('gcs',3,15),('ph',6.5,8.0),('hco3',1,60),('lactate',0,50),('creatinine',0.1,30),('bun',0,300),('wbc',0,500),('hemoglobin',1,25),('platelet',0,2000),('inr',0.3,30),('tbil',0,100),('pao2',10,800),('fio2',0.21,100),('urine',-10000,10000)), checked as (
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
        bool_or(source like '%%no_separate_entry_timestamp%%') as observation_time_proxy
      from checked group by stay_id,variable order by stay_id,variable;
