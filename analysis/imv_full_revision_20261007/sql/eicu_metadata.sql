select patientunitstayid as stay_id,hospitalid,uniquepid,unitdischargeoffset from eicu_icu.patient where patientunitstayid=any(%s);
