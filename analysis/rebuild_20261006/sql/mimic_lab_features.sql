with raw as (with mapping(itemid,variable) as (values (50820,'ph'),(50882,'hco3'),(50813,'lactate'),(50912,'creatinine'),(51006,'bun'),(51301,'wbc'),(51222,'hemoglobin'),(51265,'platelet'),(51237,'inr'),(50885,'tbil'),(50821,'pao2'),(50816,'fio2'))
select i.stay_id,mp.variable,le.valuenum as value,
 extract(epoch from (le.charttime-i.intime))/60 as minute,
 case when le.storetime is not null then greatest(extract(epoch from (le.storetime-i.intime))/60,
  extract(epoch from (le.charttime-i.intime))/60) end as available_minute,
 le.itemid::text as source,le.labevent_id::text as record_key
from mimiciv_hosp.labevents le join mimiciv_icu.icustays i on le.hadm_id=i.hadm_id
join mapping mp using(itemid)
where i.stay_id=any(%s) and le.charttime between i.intime and i.intime+interval '24h'
 and le.valuenum is not null), bounds(variable,low,high) as (values ('heart_rate',1,300),('resp_rate',1,100),('spo2',1,100),('sbp',20,300),('dbp',10,200),('map',10,250),('temp',25,45),('weight',20,400),('height',100,250),('gcs_eye',1,4),('gcs_verbal',1,5),('gcs_motor',1,6),('gcs',3,15),('ph',6.5,8.0),('hco3',1,60),('lactate',0,50),('creatinine',0.1,30),('bun',0,300),('wbc',0,500),('hemoglobin',1,25),('platelet',0,2000),('inr',0.3,30),('tbil',0,100),('pao2',10,800),('fio2',0.21,100),('urine',-10000,10000)), checked as (
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
