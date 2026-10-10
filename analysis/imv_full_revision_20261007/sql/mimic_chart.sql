select r.stay_id,r.itemid,r.charttime,r.storetime,r.value,
 extract(epoch from (r.charttime-i.intime))/60 as obs,
 extract(epoch from (r.storetime-i.intime))/60 as entry
 from mimiciv_icu.chartevents r join mimiciv_icu.icustays i using(stay_id)
 where r.stay_id=any(%s) and r.itemid in (226732,223849,229314)
 and r.charttime between i.intime and least(i.outtime,i.intime+interval '192 hours');
