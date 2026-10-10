with ranked as (
 select i.*, row_number() over(partition by i.subject_id order by i.intime,i.stay_id) as rn
 from mimiciv_icu.icustays i)
select i.subject_id,i.hadm_id,i.stay_id,i.intime,i.outtime,a.admittime,a.dischtime,a.deathtime,
 p.gender,a.race,least(90,p.anchor_age+extract(year from i.intime)::integer-p.anchor_year) as age
from ranked i join mimiciv_hosp.patients p using(subject_id)
join mimiciv_hosp.admissions a using(hadm_id)
where i.rn=1 and p.anchor_age+extract(year from i.intime)::integer-p.anchor_year>=18
 and i.outtime>=i.intime+interval '24h'
 and (a.deathtime is null or a.deathtime>i.intime+interval '24h')
order by i.intime,i.stay_id;
