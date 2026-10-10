with x as (
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
 group by stay_id;
