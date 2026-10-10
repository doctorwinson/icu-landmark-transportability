"""Read-only descriptive extensions requested by review; no label or fit changes."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / 'analysis/imv_full_revision_20261007'
RAW = ROOT / 'data/raw_timestamp_rebuild_20261006'
OUT = HERE / 'results'
OUT.mkdir(exist_ok=True)

def stats(x):
    x = pd.Series(x).dropna()
    return dict(n=len(x), median=float(x.median()), q1=float(x.quantile(.25)), q3=float(x.quantile(.75)))
def med(x, digits=1):
    q = stats(x)
    return f'{q["median"]:.{digits}f} [{q["q1"]:.{digits}f}, {q["q3"]:.{digits}f}]'
def pct(x):
    return f'{int(x.sum())}/{len(x)} ({100*x.mean():.1f}%)'

summary, follow, overlap, density, selection = {}, [], [], [], []
for name in ['mimic', 'eicu']:
    d = pd.read_parquet(RUN / f'local_only/{name}_screened_state.parquet').set_index('stay_id')
    final = d[d.exclusion.eq('included')].copy()
    eligible = d[d.exclusion.isin(['included', 'outcome_indeterminate'])].copy()
    points = pd.read_parquet(RUN / f'local_only/{name}_evidence_points.parquet')
    base = points[points.phase.eq('baseline') & points.assessable]
    cnt = base.groupby('stay_id').size()
    final['airway_points'] = cnt.reindex(final.index).fillna(0)
    summary[name] = dict(eligible=len(eligible), eligible_imv_unknown=int(eligible.imv_7d_post_window.isna().sum()), final=len(final), baseline_observations=stats(final.airway_points),
                         single_assessable_baseline=int(final.airway_points.eq(1).sum()))
    # Potential record-capture length after landmark, not verified event-free follow-up.
    icu_end = ((final.outtime-final.intime).dt.total_seconds()/3600)
    hospital_end = ((final.dischtime-final.intime).dt.total_seconds()/3600) if name=='mimic' else final.hospitaldischargeoffset/60
    for subset, mask in [('All analytic records', pd.Series(True,index=final.index)), ('Composite-negative records', final.composite_deterioration_7d.eq(0))]:
        for setting, end in [('ICU support capture', icu_end), ('Hospital mortality capture', hospital_end)]:
            x = end[mask]; duration = (x.clip(upper=192)-24).clip(lower=0)
            follow.append(dict(dataset=name, population=subset, channel=setting, n=int(mask.sum()), end_missing=int(x.isna().sum()), potential_hours=med(duration), exit_before192=pct(x.lt(192))))
    # Explicitly preserve unknown support-only status rather than mislabel death-only.
    s, death = final.organ_support_7d, final.death_7d_post_window
    cats = {'Support only':s.eq(1)&death.eq(0), 'Death only with support-negative label':s.eq(0)&death.eq(1), 'Support and death':s.eq(1)&death.eq(1), 'Death with support indeterminate':s.isna()&death.eq(1), 'Neither recorded':s.eq(0)&death.eq(0)}
    assert sum(int(m.sum()) for m in cats.values()) == len(final)
    for cat, mask in cats.items():
        overlap.append(dict(dataset=name, category=cat, count=int(mask.sum()), denominator=len(final), percent=100*mask.mean()))
    # First qualifying recorded event: support-source starts, corroborated IMV observation,
    # or hospitalization death time. This is NOT independently verified treatment onset.
    ev = pd.read_parquet(RAW / f'{name}_support_evidence.parquet')
    ev = ev[ev.kind.isin(['vaso','rrt']) & ev.start_minute.gt(1440) & ev.stay_id.isin(final.index)].copy()
    ends = (icu_end*60).clip(upper=11520)
    ev = ev[ev.start_minute.le(ev.stay_id.map(ends))]
    times = pd.DataFrame(index=final.index)
    for kind in ['vaso','rrt']:
        times[kind] = ev[ev.kind.eq(kind)].groupby('stay_id').start_minute.min().reindex(final.index)
    times['imv'] = final.imv_first_observation_minute.where(final.imv_7d_post_window.eq(1))
    death_time = ((final.deathtime-final.intime).dt.total_seconds()/60) if name=='mimic' else final.hospitaldischargeoffset
    times['death'] = death_time.where(death.eq(1))
    first = times.min(axis=1)
    assert first.notna().equals(final.composite_deterioration_7d.eq(1))
    tied = times.eq(first,axis=0).sum(axis=1)
    first_type = times.fillna(np.inf).idxmin(axis=1).where(first.notna(), 'No recorded event').mask(tied.gt(1),'Tied recorded events')
    summary[name]['first_event_hours_after_landmark'] = stats(first.dropna()/60-24)
    summary[name]['first_event_types'] = {str(k):int(v) for k,v in first_type[first.notna()].value_counts().items()}
    lineage = pd.read_parquet(RAW / f'{name}_feature_lineage.parquet')
    for var in ['spo2','heart_rate','resp_rate','map','inr','urine']:
        col = 'urine_output_24h' if var=='urine' else ('lab_24h_' if var=='inr' else 'vs_24h_')+var+'_first'
        ids = final.index[final[col].notna()]
        z = lineage[(lineage.variable.eq(var)) & lineage.stay_id.isin(ids) & lineage.n_used.gt(0)]
        density.append(dict(dataset=name, variable=var, observed_stays=z.stay_id.nunique(), total_stays=len(final), valid_record_count=med(z.n_used), first_last_span_hours=med((z.last_measurement_minute-z.first_measurement_minute)/60)))
    if name=='eicu':
        meta = pd.read_parquet(RUN / 'local_only/eicu_metadata.parquet').set_index('stay_id')
        d['hospital'] = meta.hospitalid.reindex(d.index)
        d['airway_points'] = cnt.reindex(d.index).fillna(0)
        for var, label in [('age','Age, years'),('vs_24h_spo2_min','Minimum oxygen saturation, %'),('gcs','GCS'),('airway_points','Assessable airway/device timestamps')]:
            groups = [d[d.exclusion.eq(g)][var] for g in ['included','baseline_imv_indeterminate','outcome_indeterminate']]
            den = np.sqrt((groups[0].var()+groups[1].var())/2)
            selection.append([label]+[med(x) for x in groups]+[f'{abs(groups[0].mean()-groups[1].mean())/den:.3f}' if den>0 else 'NA'])
        for var,label in [('gender','Male'),('race','White')]:
            selection.append([label]+[pct(d.loc[d.exclusion.eq(g),var].eq(label)) for g in ['included','baseline_imv_indeterminate','outcome_indeterminate']]+['Not estimated'])
        screened_h = d.groupby('hospital').size()
        avail = d[~d.exclusion.isin(['other_baseline_support','baseline_imv_supported'])]
        denom = avail.groupby('hospital').size().reindex(screened_h.index,fill_value=0)
        included = d[d.exclusion.eq('included')].groupby('hospital').size().reindex(screened_h.index,fill_value=0)
        rate = (included/denom.replace(0,np.nan)).dropna()
        summary['hospital_selection'] = dict(screened_hospitals=len(screened_h), hospitals_with_eligible_denominator=int(denom.gt(0).sum()), hospitals_with_zero_final=int((included.eq(0)&denom.gt(0)).sum()), final_hospitals=int(included.gt(0).sum()), retention_across_hospitals=stats(rate*100), denominator=int(denom.sum()), imv_indeterminate=int(d.exclusion.eq('baseline_imv_indeterminate').sum()))
        # Aggregate distribution only: no hospital identifiers leave local analytical sources.
        pd.cut(rate*100,[-.01,0,10,25,50,75,100]).value_counts(sort=False).rename_axis('retention_percent').rename('hospitals').to_csv(OUT/'hospital_selection_distribution.csv')
for filename, rows in [('followup_capture',follow),('support_death_overlap',overlap),('measurement_density',density)]:
    pd.DataFrame(rows).to_csv(OUT/f'{filename}.csv',index=False)
pd.DataFrame(selection,columns=['Characteristic','Included (n=1621)','Baseline IMV indeterminate (n=7576)','Composite indeterminate (n=39)','Absolute SMD included vs baseline unknown']).to_csv(OUT/'selection_comparison.csv',index=False)
(OUT/'descriptive_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
