with ranked as (
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
order by patientunitstayid;
