"""Full-screen, read-only IMV revision. No performance inputs or DB writes."""
from pathlib import Path
import hashlib
import json
import re
import os
import numpy as np
import pandas as pd
import psycopg2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / 'data/raw_timestamp_rebuild_20261006'
OLD = ROOT / 'data/amended_cohort_20261006'
LOCAL = HERE / 'local_only'
OUT = HERE / 'results'
DATA = ROOT / 'data/imv_revision_20261007'
for path in (LOCAL, OUT, DATA, HERE / 'sql'):
    path.mkdir(parents=True, exist_ok=True)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def freeze():
    paths = [HERE / 'PLAN.md', Path(__file__)] + sorted(RAW.glob('*.parquet'))
    hashes = {str(p): sha(p) for p in paths}
    lock = HERE / 'input_lock_v3.json'
    if lock.exists():
        assert json.loads(lock.read_text()) == hashes, 'Input/plan changed'
    else:
        lock.write_text(json.dumps(hashes, indent=2), encoding='utf-8')


def screen(name):
    d = pd.read_parquet(RAW / f'{name}_raw_predictors.parquet').set_index('stay_id')
    inf = pd.read_parquet(RAW / f'{name}_infection_evidence.parquet').set_index('stay_id')
    ev = pd.read_parquet(RAW / f'{name}_support_evidence.parquet')
    pf = pd.read_parquet(RAW / f'{name}_pf_ratio.parquet').set_index('stay_id').pf_ratio.reindex(d.index)
    low = lambda x, a, b: np.select([x < b, x < a], [2, 1], default=0)
    high = lambda x, a, b: np.select([x >= b, x >= a], [2, 1], default=0)
    early = ev[ev.start_minute.le(1440) & ev.end_minute.ge(0)]
    cv = pd.Series((d.vs_24h_map_min < 70).astype(int), index=d.index)
    cv.loc[cv.index.isin(early[early.kind.isin(['vaso', 'dobutamine'])].stay_id)] = 2
    renal = high(d.lab_24h_creatinine_max, 1.2, 2)
    renal[d.urine_output_24h < 500] = 2
    score = low(pf, 400, 300) + low(d.lab_24h_platelet_min, 150, 100) + high(d.lab_24h_tbil_max, 1.2, 2) + cv + low(d.gcs, 15, 13) + renal
    flag = inf['paired_with_order_known_by24' if name == 'mimic' else 'documented_sepsis_by24'].reindex(d.index).fillna(False)
    d = d[flag & (score >= 2)].copy()
    assert len(d) == (9464 if name == 'mimic' else 14978)
    return d, ev


EQUERIES = {
 'nursecare': "select nursecareid as rid,patientunitstayid as stay_id,nursecareoffset as obs,nursecareentryoffset as entry,cellattributevalue as value from eicu_icu.nursecare where patientunitstayid=any(%s) and (lower(trim(celllabel))='airway type' or lower(trim(cellattribute))='airway type')",
 'device': "select nursingchartid as rid,patientunitstayid as stay_id,nursingchartoffset as obs,nursingchartentryoffset as entry,nursingchartvalue as value from eicu_icu.nursecharting where patientunitstayid=any(%s) and lower(trim(nursingchartcelltypevallabel))='o2 admin device'",
 'respchart': "select respchartid as rid,patientunitstayid as stay_id,respchartoffset as obs,respchartentryoffset as entry,respchartvaluelabel as label,respchartvalue as value from eicu_icu.respiratorycharting where patientunitstayid=any(%s) and lower(respchartvaluelabel) ~ '(mode|placement|airway|device)'",
 'respcare': "select respcareid as rid,patientunitstayid as stay_id,respcarestatusoffset as entry,airwaytype as value,ventstartoffset,ventendoffset,priorventstartoffset,priorventendoffset from eicu_icu.respiratorycare where patientunitstayid=any(%s)",
 'treatment': "select treatmentid as rid,patientunitstayid as stay_id,treatmentoffset as entry,treatmentstring as value from eicu_icu.treatment where patientunitstayid=any(%s) and lower(treatmentstring) ~ '(ventilat|intubat)'",
 'exam': "select physicalexamid as rid,patientunitstayid as stay_id,physicalexamoffset as entry,physicalexampath as label,physicalexamvalue as value from eicu_icu.physicalexam where patientunitstayid=any(%s) and lower(physicalexampath) ~ '(airway|resp mode)'",
 'metadata': "select patientunitstayid as stay_id,hospitalid,uniquepid,unitdischargeoffset from eicu_icu.patient where patientunitstayid=any(%s)"
}
MQUERY = """select r.stay_id,r.itemid,r.charttime,r.storetime,r.value,
 extract(epoch from (r.charttime-i.intime))/60 as obs,
 extract(epoch from (r.storetime-i.intime))/60 as entry
 from mimiciv_icu.chartevents r join mimiciv_icu.icustays i using(stay_id)
 where r.stay_id=any(%s) and r.itemid in (226732,223849,229314)
 and r.charttime between i.intime and least(i.outtime,i.intime+interval '192 hours')"""


def extract(name, ids):
    queries = EQUERIES if name == 'eicu' else {'chart': MQUERY}
    provenance_path = OUT / f'{name}_extraction.json'
    if provenance_path.exists():
        prov = json.loads(provenance_path.read_text())
        for key in queries:
            assert prov[key]['sha256'] == sha(LOCAL / f'{name}_{key}.parquet')
        return {k: pd.read_parquet(LOCAL / f'{name}_{k}.parquet') for k in queries}
    c = psycopg2.connect(host=os.getenv('PGHOST', 'localhost'), port=int(os.getenv('PGPORT', '5432')),
                        user=os.environ['PGUSER'], dbname=os.getenv(name.upper()+'_DB', 'eicu' if name == 'eicu' else 'mimic4_v22'),
                        application_name='imv_full_revision_readonly')
    c.set_session(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)
    frames, prov = {}, {}
    try:
        with c.cursor() as cur:
            cur.execute("set local statement_timeout='30min'")
            cur.execute('show transaction_read_only')
            assert cur.fetchone()[0] == 'on'
            for key, query in queries.items():
                print('Extract', name, key, flush=True)
                (HERE / 'sql' / f'{name}_{key}.sql').write_text(query + ';\n', encoding='utf-8')
                cur.execute(query, (ids,))
                f = pd.DataFrame(cur.fetchall(), columns=[z.name for z in cur.description])
                for col in ['obs', 'entry']:
                    if col in f:
                        f[col] = pd.to_numeric(f[col], errors='coerce')
                dest = LOCAL / f'{name}_{key}.parquet'
                f.to_parquet(dest, index=False)
                frames[key] = f
                prov[key] = {'rows': len(f), 'sha256': sha(dest), 'read_only': True, 'sql_sha256': hashlib.sha256(query.encode()).hexdigest()}
                print(name, key, len(f), flush=True)
    finally:
        c.rollback()
        c.close()
    provenance_path.write_text(json.dumps(prov, indent=2), encoding='utf-8')
    return frames


def norm(x):
    return re.sub(r'\s+', ' ', str(x).strip().lower()) if pd.notna(x) else ''


AIR = {'oral ett', 'nasal ett', 'tracheostomy', 'double-lumen tube', 'cricothyrotomy', 'oral endotracheal', 'nasal endotracheal', 'endotracheal tube', 'tracheostomy tube'}
M_MODES = {'(s) cmv','aprv','aprv/biphasic+apnpress','aprv/biphasic+apnvol','apv (cmv)','apnea ventilation','cmv','cmv/assist','cmv/assist/autoflow','cmv/autoflow','cpap/pps','cpap/psv','cpap/psv+apn tcpl','cpap/psv+apnpres','cpap/psv+apnvol','mmv','mmv/autoflow','mmv/psv','mmv/psv/autoflow','p-cmv','pcv+','pcv+/psv','pcv+assist','pres/ac','prvc/ac','prvc/simv','psv/sbt','simv','simv/autoflow','simv/pres','simv/psv','simv/psv/autoflow','simv/vol','synchron master','synchron slave','vol/ac','apv (simv)','p-simv','vs','asv'}
E_MODES = {'ac/cmv','cmv','simv','simv+','apv','pressure control','pcv w/assist','aprv','cpap','psv','pressure support','cpap/psv','cpap/ps','a/c','assist control','assist/control','volume control'}


def device_flags(v):
    if re.search(r'\b(no|not|off)\b.*\bvent|disconnect|pre.?intubat|bagging|manual bag|planned|\?', v):
        return False, False, False, False
    niv = bool(re.search(r'non.?invasive|\bniv\b|bipap|cpap mask', v))
    vent = not niv and bool(re.search(r'ventilator|\bvent\b|\bvented\b', v)) and 'venturi' not in v
    combo = vent and bool(re.search(r'trach|trache', v))
    nonvent = bool(re.search(r'nasal|cannula|room air|^none$|^ra$|^n/?c$|nrb|non.?rebreath|venturi|venti mask|oxim|oxym|oxy mask|face.?mask|face tent|aerosol|trach (collar|mask)|^tc$|t.?piece|high.?flow|hiflo|hi flo|misty|simple mask', v)) and not vent
    return vent, combo, niv, nonvent


def evidence(name, frames, d):
    rows = []
    def add(stay, rid, source, obs, entry, value, air=False, vent=False, combo=False, negative=False, nonvent=False, possible=False, basis='observation', zero=False):
        rows.append((int(stay), str(rid), source, float(obs) if pd.notna(obs) else np.nan,
                     float(entry) if pd.notna(entry) else np.nan, str(value), air, vent, combo, negative, nonvent, possible, basis, zero))
    if name == 'mimic':
        for i, r in enumerate(frames['chart'].itertuples()):
            v = norm(r.value)
            if r.itemid == 226732:
                vent, combo, niv, nonvent = device_flags(v)
                add(r.stay_id, i, 'chartevents_device', r.obs, r.entry, r.value, air=v in AIR, vent=vent, combo=combo, negative=niv or nonvent, nonvent=niv or nonvent, possible=v in AIR or vent)
            else:
                niv = v in {'niv','niv-st','duopap'}
                add(r.stay_id, i, 'chartevents_mode', r.obs, r.entry, r.value, vent=v in M_MODES, negative=niv, nonvent=niv, possible=bool(v) and not niv)
    else:
        for r in frames['nursecare'].itertuples():
            v = norm(r.value)
            add(r.stay_id, r.rid, 'nursecare', r.obs, r.entry, r.value, air=v in AIR, negative=v == 'no artificial airway', nonvent=v == 'no artificial airway', possible=v in AIR)
        for r in frames['device'].itertuples():
            v = norm(r.value)
            vent, combo, niv, nonvent = device_flags(v)
            # CPAP listed as a device without an interface remains non-IMV context.
            niv = niv or (not vent and 'cpap' in v)
            add(r.stay_id, r.rid, 'nursechart', r.obs, r.entry, r.value, vent=vent, combo=combo, negative=niv or nonvent, nonvent=niv or nonvent, possible=vent or combo)
        for r in frames['respchart'].itertuples():
            v, label = norm(r.value), norm(r.label)
            mode = 'mode' in label
            niv = mode and bool(re.search(r'\bniv\b|non.?invasive|bipap', v))
            air = ('placement' in label or 'airway' in label) and v in AIR
            add(r.stay_id, r.rid, 'respchart', r.obs, r.entry, r.value, air=air, vent=mode and v in E_MODES and not niv, negative=niv, nonvent=niv, possible=air or (mode and bool(v) and not niv))
        for r in frames['respcare'].itertuples():
            v = norm(r.value)
            if v not in AIR:
                continue
            current_early = pd.notna(r.ventstartoffset) and r.ventstartoffset <= 1440
            prior_early = (pd.notna(r.priorventstartoffset) and pd.notna(r.priorventendoffset)
                           and r.priorventendoffset > r.priorventstartoffset
                           and r.priorventendoffset >= 0 and r.priorventstartoffset <= 1440)
            early_start = current_early or prior_early
            # Entry is context only. A recorded early start is uncertainty, never
            # a manufactured observed interval; source end times are unreliable.
            add(r.stay_id, r.rid, 'respcare', np.nan, r.entry, r.value, possible=True, basis='entry_only', zero=early_start)
        for r in frames['treatment'].itertuples():
            v = norm(r.value)
            possible = bool(re.search(r'mechanical ventilation|reintubation|endotracheal intubation', v)) and not re.search(r'non.?invasive|bipap|mask', v)
            if possible:
                add(r.stay_id, r.rid, 'treatment', np.nan, r.entry, r.value, possible=True, basis='entry_only')
        for r in frames['exam'].itertuples():
            if norm(r.value) in {'intubated', 'tracheostomy', 'ventilated'}:
                add(r.stay_id, r.rid, 'exam', np.nan, r.entry, r.value, possible=True, basis='entry_only')
    cols = ['stay_id','record_id','source','obs','entry','value','air','vent','combo','negative','nonvent','possible','time_basis','early_start_uncertain']
    t = pd.DataFrame(rows, columns=cols)
    ends = d.unitdischargeoffset if name == 'eicu' else (d.outtime - d.intime).dt.total_seconds() / 60
    t['capture_end'] = t.stay_id.map(ends).clip(upper=11520)
    t['time_for_window'] = t.obs.where(t.time_basis.eq('observation'), t.entry)
    t['in_capture'] = t.time_for_window.ge(0) & t.time_for_window.le(t.capture_end)
    # A late entry may preserve a baseline onset ambiguity, never an outcome.
    t = t[t.in_capture | (t.time_basis.eq('entry_only') & t.early_start_uncertain)].copy()
    t['phase'] = np.where(t.time_for_window.le(1440), 'baseline', 'outcome')
    t.to_parquet(LOCAL / f'{name}_normalized_evidence.parquet', index=False)
    point_rows = []
    obs = t[t.time_basis.eq('observation') & t.in_capture]
    for (stay, minute), g in obs.groupby(['stay_id','obs'], sort=False):
        strong = bool((g.air.any() and g.vent.any()) and not g.negative.any())
        combo = bool(g.combo.any() and not g.negative.any())
        airway_conflict = bool(g.air.any() and g.value.map(norm).isin(['no artificial airway','none']).any())
        unresolved = bool(airway_conflict or (g.possible.any() and not strong and not (g.nonvent.any() and not g.vent.any() and not combo)))
        point_rows.append((stay, minute, 'baseline' if minute <=1440 else 'outcome', strong, combo, unresolved, bool(g.air.any() or g.vent.any() or g.nonvent.any() or combo), bool(g.entry.notna().all() and g.entry.le(1440).all())))
    pts = pd.DataFrame(point_rows, columns=['stay_id','minute','phase','strong','combo','uncertain','assessable','entered_by24'])
    for (stay, ph), g in pts[pts.combo].groupby(['stay_id','phase']):
        if len(g) >=2 and g.minute.max()-g.minute.min() >=30:
            pts.loc[g.index, ['strong','uncertain']] = [True, False]
    pts.to_parquet(LOCAL / f'{name}_evidence_points.parquet', index=False)
    outcomes = []
    bypoint = {k: g for k,g in pts.groupby('stay_id')}
    byentry = {k: g for k,g in t[t.time_basis.eq('entry_only')].groupby('stay_id')}
    empty = pts.iloc[:0]
    for stay in d.index:
        p = bypoint.get(stay, empty)
        b, f = p[p.phase.eq('baseline')], p[p.phase.eq('outcome')]
        ent = byentry.get(stay)
        eb = ef = ez = False
        if ent is not None:
            eb = bool((ent.in_capture & ent.phase.eq('baseline') & ent.possible).any())
            ef = bool((ent.in_capture & ent.phase.eq('outcome') & ent.possible).any())
            ez = bool(ent.early_start_uncertain.any())
        bs = bool(b.strong.any())
        bu = bool(b.uncertain.any() or eb or ez or not b.assessable.any())
        fs = bool(f.strong.any())
        fu = bool(f.uncertain.any() or ef)
        status = 'supported' if bs else 'indeterminate' if bu else 'no_identified_support'
        post = 1.0 if fs else np.nan if fu else 0.0
        outcomes.append((stay, status, post, bool((b.strong & b.entered_by24).any()),
                         'early_start_or_zero' if ez else 'possible_baseline_support' if (b.uncertain.any() or eb) else 'no_assessable_baseline' if not b.assessable.any() else '',
                         float(f.loc[f.strong,'minute'].min()) if fs else np.nan))
    state = pd.DataFrame(outcomes, columns=['stay_id','baseline_imv_status','imv_7d_post_window','baseline_imv_available_by24','baseline_unknown_reason','imv_first_observation_minute']).set_index('stay_id')
    return state, t


def assemble(name, d, ev, state):
    d = d.join(state)
    for kind in ['vaso','rrt']:
        q = ev[ev.kind.eq(kind)]
        d['baseline_'+kind] = d.index.isin(q[q.start_minute.le(1440)&q.end_minute.ge(0)].stay_id)
        d[kind+'_7d_post_window'] = d.index.isin(q[q.start_minute.gt(1440)].stay_id).astype(int)
    if name == 'mimic':
        d['uniquepid'] = d.subject_id.astype(str)
        d['death_7d_post_window'] = ((d.deathtime > d.intime + pd.Timedelta(hours=24)) & (d.deathtime <= d.intime + pd.Timedelta(hours=192))).astype(int)
    else:
        anchor = pd.Timestamp('2000-01-01')
        d['intime'] = anchor
        d['outtime'] = anchor + pd.to_timedelta(d.unitdischargeoffset, unit='m')
        d['admittime'] = anchor + pd.to_timedelta(d.hospitaladmitoffset, unit='m')
        d['death_7d_post_window'] = (d.hospitaldischargestatus.eq('Expired') & d.hospitaldischargeoffset.gt(1440) & d.hospitaldischargeoffset.le(11520)).astype(int)
    comp = ['vaso_7d_post_window','imv_7d_post_window','rrt_7d_post_window','death_7d_post_window']
    other = d[['vaso_7d_post_window','rrt_7d_post_window','death_7d_post_window']].max(axis=1)
    d['composite_deterioration_7d'] = np.where(other.eq(1)|d.imv_7d_post_window.eq(1), 1.0, np.where(d.imv_7d_post_window.isna(), np.nan, 0.0))
    d['organ_support_7d'] = np.where(d.vaso_7d_post_window.eq(1)|d.rrt_7d_post_window.eq(1)|d.imv_7d_post_window.eq(1), 1.0, np.where(d.imv_7d_post_window.isna(), np.nan, 0.0))
    d['exclusion'] = np.select([d.baseline_vaso|d.baseline_rrt, d.baseline_imv_status.eq('supported'), d.baseline_imv_status.eq('indeterminate'), d.composite_deterioration_7d.isna()], ['other_baseline_support','baseline_imv_supported','baseline_imv_indeterminate','outcome_indeterminate'], default='included')
    old = pd.read_parquet(OLD / ('study1_bdmcc24_dataset.parquet' if name=='mimic' else 'study1_eicu_bdmcc24_dataset.parquet')).set_index('stay_id')
    trans = d[['baseline_imv_status','baseline_unknown_reason','imv_7d_post_window','composite_deterioration_7d','exclusion']].copy()
    trans['old_included'] = trans.index.isin(old.index)
    for col in ['imv_7d_post_window','composite_deterioration_7d']:
        trans['old_'+col] = old[col].reindex(trans.index)
    trans.reset_index().to_parquet(LOCAL / f'{name}_old_new_transition.parquet', index=False)
    trans.groupby(['old_included','exclusion'], dropna=False).size().rename('stays').to_csv(OUT / f'{name}_membership_transition.csv')
    for col in ['imv_7d_post_window','composite_deterioration_7d']:
        z = trans[trans.old_included].copy()
        z['new_status'] = np.where(z.exclusion.eq('included'), z[col].astype(str), 'excluded:'+z.exclusion)
        pd.crosstab(z['old_'+col], z.new_status).to_csv(OUT / f'{name}_{col}_transition.csv')
    race = d.race.fillna('').str.upper()
    d['race'] = np.select([race.str.contains('WHITE|CAUCASIAN'),race.str.contains('BLACK|AFRICAN'),race.str.contains('ASIAN'),race.str.contains('HISPANIC|LATINO'),race.str.contains('UNKNOWN|UNABLE|DECLIN|UNOBTAIN')|race.eq('')],['White','Black','Asian','Hispanic','Unknown'],default='Other')
    sex = d.gender.fillna('').str.upper()
    d['gender'] = np.select([sex.isin(['M','MALE']),sex.isin(['F','FEMALE'])],['Male','Female'],default='Unknown')
    d['index_time'] = d.intime
    d['window_end'] = d.intime + pd.Timedelta(hours=24)
    eligible = d[d.exclusion.isin(['included','outcome_indeterminate'])].copy()
    chosen = d[d.exclusion.eq('included')].copy()
    eligible.reset_index().to_parquet(DATA / f'{name}_eligible_with_unknown_outcomes.parquet', index=False)
    filename = 'study1_bdmcc24_dataset.parquet' if name=='mimic' else 'study1_eicu_bdmcc24_dataset.parquet'
    chosen.reset_index().to_parquet(DATA / filename, index=False)
    d.reset_index().to_parquet(LOCAL / f'{name}_screened_state.parquet', index=False)
    assert chosen.baseline_imv_status.eq('no_identified_support').all()
    assert not chosen.composite_deterioration_7d.isna().any()
    assert ((chosen[comp].eq(1).any(axis=1)).astype(int) == chosen.composite_deterioration_7d).all()
    return {'screened':len(d),'old_final':len(old),'new_final':len(chosen),'eligible_before_outcome_exclusion':len(eligible),
            'exclusion_counts':d.exclusion.value_counts().to_dict(),'baseline_imv_status_counts':d.baseline_imv_status.value_counts().to_dict(),
            'retained_old':int(chosen.index.isin(old.index).sum()),'newly_included':int((~chosen.index.isin(old.index)).sum()),
            'events':{c:int(chosen[c].sum()) for c in comp+['composite_deterioration_7d']},
            'imv_unknown_among_composite_known':int(chosen.imv_7d_post_window.isna().sum()),
            'data_sha256':sha(DATA / filename)}


if __name__ == '__main__':
    freeze()
    summaries = {}
    for name in ['mimic','eicu']:
        d, ev = screen(name)
        d.reset_index().to_parquet(LOCAL / f'{name}_screen_before_support.parquet', index=False)
        frames = extract(name, d.index.astype(int).tolist())
        state, t = evidence(name, frames, d)
        state.reset_index().to_parquet(LOCAL / f'{name}_imv_state.parquet', index=False)
        t.groupby(['source','phase']).agg(records=('stay_id','size'),stays=('stay_id','nunique')).to_csv(OUT / f'{name}_source_coverage.csv')
        summaries[name] = assemble(name, d, ev, state)
        print(name, json.dumps(summaries[name]), flush=True)
    (OUT / 'cohort_counts.json').write_text(json.dumps(summaries, indent=2), encoding='utf-8')
    print('Full rebuild complete; model fitting not performed by this script.', flush=True)
