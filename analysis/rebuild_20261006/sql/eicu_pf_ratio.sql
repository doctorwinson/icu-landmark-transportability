with x as (
 select patientunitstayid as stay_id,labresultoffset,
 min(labresult) filter(where labname='paO2') as pao2,max(labresult) filter(where labname='FiO2') as fio2
 from eicu_icu.lab where patientunitstayid=any(%s) and labname in ('paO2','FiO2')
 and labresultoffset between 0 and 1440 and labresultrevisedoffset is not null and labresultrevisedoffset<=1440
 group by patientunitstayid,labresultoffset)
 select stay_id,min(pao2/(case when fio2>1 then fio2/100 else fio2 end)) as pf_ratio
 from x where pao2 between 10 and 800 and (fio2 between .21 and 1 or fio2 between 21 and 100)
 group by stay_id;
