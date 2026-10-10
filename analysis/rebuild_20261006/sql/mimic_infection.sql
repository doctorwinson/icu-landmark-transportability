with candidate as (select * from mimiciv_icu.icustays where stay_id=any(%s)),
 abx as (
 select distinct c.stay_id,pr.starttime,po.ordertime,c.intime,
   po.ordertime is not null and po.ordertime<=c.intime+interval '24h' as order_known_by24
 from candidate c join mimiciv_hosp.prescriptions pr using(hadm_id)
 left join mimiciv_hosp.poe po on po.poe_id=pr.poe_id and po.poe_seq=pr.poe_seq
 where pr.starttime between c.intime-interval '78h' and c.intime+interval '24h'
 and pr.drug_type is distinct from 'BASE'
 and pr.route is not null and upper(pr.route) not in ('OU','OS','OD','AU','AS','AD','TP','TOP','OPHTH','OTIC')
 and lower(pr.route) !~ '(ear|eye)'
 and lower(pr.drug) !~ '(cream|desensitization|ophth oint|gel)'
 and (lower(pr.drug) ~ 'adoxa|ala\-tet|alodox|amikacin|amikin|amoxicill|amphotericin|ampicillin|ancef|anidulafungin|augmentin|avelox|avidoxy|axetil|azactam|azithromycin|aztreonam|bactocill|bactrim|bactroban|bethkis|biaxin|bicillin\ l\-a|cayston|cedax|cefaclor|cefadroxil|cefazolin|cefdinir|cefditoren|cefepime|cefotan|cefotaxime|cefotetan|cefoxitin|cefpirome|cefpodoxime|cefprozil|ceftaroline|ceftazidime|ceftibuten|ceftin|ceftriaxone|cefuroxime|cephalexin|cephalothin|cephapririn|chloramphenicol|cipro|ciprofloxacin|claforan|clarithromycin|clavulanate|cleocin|clindamycin|cubicin|dicloxacillin|dirithromycin|doryx|doxycy|duricef|dynacin|ery\-tab|eryc|eryped|erythrocin|erythromycin|factive|flagyl|fortaz|furadantin|garamycin|gentamicin|kanamycin|keflex|kefzol|ketek|levaquin|levofloxacin|lincocin|linezolid|macrobid|macrodantin|maxipime|mefoxin|meropenem|methicillin|metronidazole|minocin|minocycline|monodox|monurol|morgidox|moxatag|moxifloxacin|mupirocin|myrac|nafcillin|neomycin|nicazel\ doxy\ 30|nitrofurantoin|norfloxacin|noroxin|ocudox|ofloxacin|omnicef|oracea|oraxyl|oxacillin|panixine|pc\ pen\ vk|pce\ dispertab|pediazole|penicillin|periostat|pfizerpen|piperacillin|primsol|proquin|raniclor|rifadin|rifampin|rocephin|septra\ ds|septra|smz\-tmp|solodyn|spectracef|streptomycin|sulfadiazine|sulfamethoxazole|sulfatrim|sulfisoxazole|suprax|synercid|tazicef|tazobactam|tetracycline|timentin|tobramycin|trimethoprim|unasyn|vancocin|vancomycin|vantin|vibativ|vibra\-tabs|vibramycin|zinacef|zithromax|zosyn|zyvox')), cultures as (
 select distinct c.stay_id,m.charttime from candidate c join mimiciv_hosp.microbiologyevents m using(hadm_id)
 where m.charttime between c.intime-interval '78h' and c.intime+interval '24h'
 and lower(m.test_name) like '%%culture%%' and lower(m.test_name) not like '%%screen%%'), pairs as (
 select a.stay_id,a.order_known_by24,a.starttime as antibiotic_time,b.charttime as culture_time,
 least(a.starttime,b.charttime) as suspicion_time,
 greatest(a.starttime,b.charttime,a.ordertime) as evidence_complete_time
 from abx a join cultures b using(stay_id)
 where ((a.starttime<=b.charttime and b.charttime<=a.starttime+interval '24h')
 or (b.charttime<a.starttime and a.starttime<=b.charttime+interval '72h'))
 and least(a.starttime,b.charttime)>=a.intime-interval '6h')
select c.stay_id,count(p.stay_id)>0 as paired_infection_events_by24,
 coalesce(bool_or(p.order_known_by24),false) as paired_with_order_known_by24,
 min(p.suspicion_time) filter(where p.order_known_by24) as infection_evidence_time,
 min(p.evidence_complete_time) filter(where p.order_known_by24) as evidence_complete_time
from candidate c left join pairs p using(stay_id) group by c.stay_id order by c.stay_id;
