with c as (select * from eicu_icu.patient where patientunitstayid=any(%s)), events as (
 select r.patientunitstayid,r.infusionoffset as start_minute,r.infusionoffset as end_minute,
 case when lower(r.drugname) ~ 'dobutamine' then 'dobutamine' else 'vaso' end as kind,'infusiondrug_positive_rate' as source
 from eicu_icu.infusiondrug r join c using(patientunitstayid)
 where lower(r.drugname) ~ '(norepinephrine|noradrenaline|levophed|epinephrine|adrenaline|dopamine|phenylephrine|neosynephrine|neo-synephrine|vasopressin|dobutamine)'
 and case when trim(r.drugrate) ~ '^[0-9]+(\.[0-9]+)?$' then trim(r.drugrate)::numeric>0 else false end
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
where e.start_minute<=least(11520,c.unitdischargeoffset) and e.end_minute>=0;
