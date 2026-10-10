with c as (select * from mimiciv_icu.icustays where stay_id=any(%s)), events as (
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime) as endtime,'vaso' as kind,'inputevents' as source
 from mimiciv_icu.inputevents r join c using(stay_id)
 where r.itemid in (221906,221289,221662,221749,222315) and r.amount>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime),'dobutamine','inputevents'
 from mimiciv_icu.inputevents r join c using(stay_id) where r.itemid=221653 and r.amount>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.charttime,r.charttime,'imv','chartevents_device_or_mode'
 from mimiciv_icu.chartevents r join c using(stay_id)
 where (r.itemid=226732 and r.value='Endotracheal tube')
   or (r.itemid=223849 and r.value in ('(S) CMV','APRV','APRV/Biphasic+ApnPress','APRV/Biphasic+ApnVol','APV (cmv)','Ambient','Apnea Ventilation','CMV','CMV/ASSIST','CMV/ASSIST/AutoFlow','CMV/AutoFlow','CPAP/PPS','CPAP/PSV','CPAP/PSV+Apn TCPL','CPAP/PSV+ApnPres','CPAP/PSV+ApnVol','MMV','MMV/AutoFlow','MMV/PSV','MMV/PSV/AutoFlow','P-CMV','PCV+','PCV+/PSV','PCV+Assist','PRES/AC','PRVC/AC','PRVC/SIMV','PSV/SBT','SIMV','SIMV/AutoFlow','SIMV/PRES','SIMV/PSV','SIMV/PSV/AutoFlow','SIMV/VOL','SYNCHRON MASTER','SYNCHRON SLAVE','VOL/AC'))
   or (r.itemid=229314 and r.value in ('APRV','APV (cmv)','Ambient','(S) CMV','P-CMV','SIMV','APV (simv)','P-SIMV','VS','ASV'))
 union all
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime),'rrt','procedureevents'
 from mimiciv_icu.procedureevents r join c using(stay_id)
 where r.itemid in (225441,225802,225803,225805,225809,225955) and r.value>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.starttime,coalesce(r.endtime,r.starttime),'rrt','inputevents_crrt'
 from mimiciv_icu.inputevents r join c using(stay_id) where r.itemid in (227536,227525) and r.amount>0
 and r.statusdescription is distinct from 'Rewritten'
 union all
 select r.stay_id,r.charttime,r.charttime,'rrt','chartevents_flow_output'
 from mimiciv_icu.chartevents r join c using(stay_id)
 where (r.itemid in (226499,224154,224191,225806,225807,228004,228005,228006,224144,224153,226457) and r.valuenum>0)
 or (r.itemid=225965 and r.value='In use'))
select r.stay_id,r.kind,r.source,
 extract(epoch from(r.starttime-c.intime))/60 as start_minute,
 extract(epoch from(r.endtime-c.intime))/60 as end_minute
from events r join c using(stay_id)
where r.starttime<=least(c.outtime,c.intime+interval '192h') and r.endtime>=c.intime;
