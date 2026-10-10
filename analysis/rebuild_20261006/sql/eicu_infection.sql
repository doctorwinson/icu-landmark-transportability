select p.patientunitstayid as stay_id,
 coalesce(bool_or(d.diagnosisoffset between 0 and 1440),false) as documented_sepsis_by24,
 min(d.diagnosisoffset) filter(where d.diagnosisoffset between 0 and 1440) as infection_evidence_minute
from eicu_icu.patient p left join eicu_icu.diagnosis d
 on d.patientunitstayid=p.patientunitstayid and lower(d.diagnosisstring) ~ '(sepsis|septic shock)'
 and lower(d.diagnosisstring) !~ '(rule out|ruled out|no sepsis)'
where p.patientunitstayid=any(%s) group by p.patientunitstayid order by p.patientunitstayid;
