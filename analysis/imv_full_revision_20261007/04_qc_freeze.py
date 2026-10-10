"""Independent full-cohort reconciliation and pre-fit hash lock."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
DATA=ROOT/'data/imv_revision_20261007'
OLD=ROOT/'data/amended_cohort_20261006'
LOCAL=HERE/'local_only'
OUT=HERE/'results'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
counts=json.loads((OUT/'cohort_counts.json').read_text())
features=json.loads((HERE.parent/'rebuild_20261006/feature_whitelist.json').read_text())
checks={}
for name in ['mimic','eicu']:
    d=pd.read_parquet(LOCAL/f'{name}_screened_state.parquet').set_index('stay_id')
    points=pd.read_parquet(LOCAL/f'{name}_evidence_points.parquet')
    ev=pd.read_parquet(LOCAL/f'{name}_normalized_evidence.parquet')
    fname='study1_bdmcc24_dataset.parquet' if name=='mimic' else 'study1_eicu_bdmcc24_dataset.parquet'
    new=pd.read_parquet(DATA/fname).set_index('stay_id')
    old=pd.read_parquet(OLD/fname).set_index('stay_id')
    assert len(d)==counts[name]['screened'] and d.index.is_unique and new.index.is_unique
    assert set(new.index)==set(d[d.exclusion.eq('included')].index)
    assert new.baseline_imv_status.eq('no_identified_support').all()
    assert not new[['baseline_vaso','baseline_rrt']].any().any()
    assert not new.composite_deterioration_7d.isna().any()
    cmp=['vaso_7d_post_window','imv_7d_post_window','rrt_7d_post_window','death_7d_post_window']
    pos=d[cmp].eq(1).any(axis=1)
    unk=d[cmp].isna().any(axis=1)&~pos
    assert d.composite_deterioration_7d.eq(1).equals(pos)
    assert d.composite_deterioration_7d.isna().equals(unk)
    assert len(new)==counts[name]['new_final'] and int(new.composite_deterioration_7d.sum())==counts[name]['events']['composite_deterioration_7d']
    inside=ev[ev.in_capture]
    assert inside.time_for_window.ge(0).all() and inside.time_for_window.le(inside.capture_end).all()
    outside=ev[~ev.in_capture]
    assert outside.time_basis.eq('entry_only').all() and outside.early_start_uncertain.all()
    assert points.loc[points.phase.eq('baseline'),'minute'].le(1440).all()
    assert points.loc[points.phase.eq('outcome'),'minute'].gt(1440).all()
    baseline_ids=set(points[points.phase.eq('baseline')&points.strong].stay_id)
    assert baseline_ids==set(d[d.baseline_imv_status.eq('supported')].index)
    followup_ids=set(points[points.phase.eq('outcome')&points.strong].stay_id)
    assert followup_ids==set(d[d.imv_7d_post_window.eq(1)].index)
    common=new.index.intersection(old.index)
    pd.testing.assert_frame_equal(new.loc[common,features],old.loc[common,features],check_dtype=False)
    for c in ['vaso_7d_post_window','rrt_7d_post_window','death_7d_post_window']:
        assert new.loc[common,c].equals(old.loc[common,c]), c
    assert sum(counts[name]['exclusion_counts'].values())==len(d)
    checks[name]={'whole_screen_processed':True,'tri_state_composite_verified':True,'baseline_and_followup_windows_verified':True,
                  'retained_predictors_unchanged':True,'other_components_unchanged':True,'flow_sums_verified':True}
    if name=='eicu':
        meta=pd.read_parquet(LOCAL/'eicu_metadata.parquet').set_index('stay_id')
        d=d.join(meta[['hospitalid']])
        assert not d.hospitalid.isna().any()
        tab=d.groupby(['hospitalid','exclusion']).size().unstack(fill_value=0)
        tab['screened']=tab.sum(axis=1)
        tab['retention_fraction']=tab.get('included',0)/tab.screened
        tab.to_csv(OUT/'hospital_selection_coverage.csv')
        checks[name]['screen_hospitals']=int(d.hospitalid.nunique())
        checks[name]['old_final_hospitals']=int(meta.loc[old.index,'hospitalid'].nunique())
        checks[name]['new_final_hospitals']=int(d.loc[new.index,'hospitalid'].nunique())
        d.groupby(['exclusion','baseline_unknown_reason']).size().rename('stays').to_csv(OUT/'eicu_exclusion_reasons.csv')
        prior=pd.read_csv(HERE.parent/'imv_rule_confirmation_20261007/local_only/case_routing_for_investigator_review.csv')
        z=prior[['case_id','stay_id','technical_action']].merge(d.reset_index()[['stay_id','baseline_imv_status','exclusion','imv_7d_post_window']],on='stay_id',validate='one_to_one')
        assert len(z)==115
        assert z.loc[z.technical_action.eq('EXCLUDE_BASELINE_INDETERMINATE'),'exclusion'].isin(['baseline_imv_indeterminate','baseline_imv_supported','other_baseline_support']).all(), 'Unresolved cases were readmitted'
        assert z.loc[z.technical_action.eq('EXCLUDE_BASELINE_SUPPORTED'),'baseline_imv_status'].eq('supported').all()
        assert z.loc[z.technical_action.eq('POST24_CAPTURE_CANDIDATE'),'imv_7d_post_window'].eq(1).all()
        z.to_csv(LOCAL/'targeted115_vs_full_review.csv',index=False)
        pd.crosstab(z.technical_action,z.exclusion).to_csv(OUT/'targeted115_vs_full_counts.csv')

qc={'passed':True,'checks':checks,'unknown_policy_user_confirmed':True,'independent_clinician_gold_standard':False,
    'complete_outcome_analysis_is_selected_population':True,'old_files_not_modified':True}
(OUT/'full_cohort_qc.json').write_text(json.dumps(qc,indent=2),encoding='utf-8')
paths=list(DATA.glob('*.parquet'))+[HERE/'PLAN.md',HERE/'01_rebuild.py',HERE/'02_refit.R',HERE/'03_uncertainty.R',Path(__file__),OUT/'full_cohort_qc.json',HERE.parent/'rebuild_20261006/feature_whitelist.json',HERE.parent/'rebuild_20261006/results/tuning_leaderboard.csv',HERE.parent/'rebuild_20261006/results/split_ids_local_only.rds']
hashes={str(p):sha(p) for p in paths}
lock=HERE/'prefit_lock_v3.json'
if lock.exists():
    assert json.loads(lock.read_text())==hashes,'Frozen pre-fit inputs changed'
else:
    lock.write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print(json.dumps(qc,indent=2))
