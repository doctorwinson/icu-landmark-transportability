with raw as (with x as (select ce.stay_id,ce.charttime,ce.itemid,min(ce.valuenum) as value,
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
 from g join mimiciv_icu.icustays i using(stay_id)), bounds(variable,low,high) as (values ('heart_rate',1,300),('resp_rate',1,100),('spo2',1,100),('sbp',20,300),('dbp',10,200),('map',10,250),('temp',25,45),('weight',20,400),('height',100,250),('gcs_eye',1,4),('gcs_verbal',1,5),('gcs_motor',1,6),('gcs',3,15),('ph',6.5,8.0),('hco3',1,60),('lactate',0,50),('creatinine',0.1,30),('bun',0,300),('wbc',0,500),('hemoglobin',1,25),('platelet',0,2000),('inr',0.3,30),('tbil',0,100),('pao2',10,800),('fio2',0.21,100),('urine',-10000,10000)), checked as (
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
