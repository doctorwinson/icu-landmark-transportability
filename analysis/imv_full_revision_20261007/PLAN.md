# Full-population IMV revision and refitting plan

2026-10-07. Post-audit amendment, not a prospective preregistration. The user approved conservative unknown handling and requested full application, transitions, and refitting. Existing external aggregate performance is known. Neither database is modified. Preserve all older cohorts and results.

## Frozen implementation choices

Reconstruct the infection/organ-screen population from the frozen raw timestamp layers, before ANY support exclusions: expected prior screen sizes 9464 MIMIC-IV v2.2 and 14978 eICU. Query IMV source records for EVERY screened stay, not the 115 targeted records. Vasopressor, RRT, death, infection, organ screening and 75 predictor definitions remain unchanged; this is specifically an IMV amendment. Their existing capture limitations remain.

Baseline minutes 0 through1440; follow-up >1440 through min(11520, ICU discharge). Pair artificial airway with current ventilator device or a recognized mechanical ventilator mode at the same observation time; do not pair charting by entry time or carry forward airway across the landmark. Repeated explicit tracheostomy-to-ventilator device observations separated by >=30min in the same phase qualify under the existing repeated-evidence rule, not as proof of continuous duration. Explicit same-time contrary airway/device evidence prevents strong classification at that point. Preserve other non-conflicted positive points.

Mode alone and airway alone are uncertain unless contemporaneous device context explains nonventilator support. Generic ventilation treatment records and reintubation entries do not independently establish a timed IMV event. respiratorycare status and treatment timestamps are entry times; use as uncertainty/context, not observed onset. Zero vent-start + artificial-airway evidence without independent baseline support is baseline-indeterminate; do not manufacture an interval end from status entry. Nonzero start/end fields without observed airway/ventilator corroboration remain uncertainty, not a restored clinical gold standard.

First-day status: any strong baseline evidence -> supported; otherwise unresolved baseline evidence or lack of interpretable first-day airway/device observations -> indeterminate; otherwise no identified baseline support in assessable records. A later strong event must never resolve an uncertain baseline into eligibility. Evidence recorded late but observed in baseline affects retrospective eligibility and is flagged as not available by24.

Later entry-only records provide follow-up uncertainty, not a verified onset; an explicit zero/pre-landmark vent-start or other direct baseline signal remains baseline uncertainty regardless of entry time. Records after ICU discharge do not create support events. Do not infer whole-day nonventilation from isolated oxygen observations.

Unknown baseline -> separate exclusion. Among otherwise eligible stays, definite component positive -> composite1 even if IMV unknown; IMV unknown with no other positive -> composite unknown and excluded from complete-outcome modeling, retained in the eligibility export and flow counts. Component metrics exclude only that component's unknowns. Support-only labels likewise retain unknown unless another support component is positive.

## Pre-fit implementation QC correction

Before any model refitting, source-level QC identified that an empty prior-ventilation interval (both historical offsets zero) must not create baseline uncertainty by itself. Historical intervals require end>start and overlap with baseline; current vent-start=0 retains the agreed conservative treatment. Same-time artificial-airway plus explicit no-airway/None is unresolved, not negative. The preliminary code/counts are retained in pre_qc_v0; input_lock_v2 freezes the corrected implementation. This correction is based on field semantics, not prediction performance.

### Window-context QC correction before final release

The full replay of the115 targeted cases detected8 zero-start cases incorrectly readmitted because their baseline-timing uncertainty was entered outside the outcome capture window. Preserve such entry-only records as baseline uncertainty context, without allowing them to create an outcome or a timed support event. Archive the preliminary v2 counts/fits, stop its uncertainty job, and rerun with v3 locks. No model performance is used to choose this correction. Full QC now explicitly prohibits readmission of unresolved-zero cases and verifies that outcome evidence remains within the capture window.

## Refitting, no external selection

Retain old MIMIC split identities for retained stays. New eligible stays receive a deterministic SHA256(subject_id with salt imv_revision_20261007) split at70/15/15, without looking at outcome. Never reshuffle existing test patients after relabeling. Report actual split counts and event counts, no claim temporal validation or pristine untouched test data.

Reuse the previous 64 XGBoost parameter candidate rows, validation AUPRC -> AUROC -> Brier -> gap selection, early stopping50, seed20261006. Refit preprocessing on development after internal selection. Ridge: alpha0, unweighted, 81lambda grid10^seq(2,-6), validation logloss, tie stronger penalty. BaselineXGB unchanged. Historical weightedLR remains a labeled historical comparator, not sole reference. Save fitted models before reading external outcomes for evaluation.

Primary uncertainty: paired2000replicate hospital bootstrap, sensitivity patient and connected patient-hospital blocks. Internal patient bootstrap2000. Fixed5/10/15% threshold workload and paired net-benefit differences. Include outcome-informed external prevalence reference and fixed development prevalence separately. Confidence intervals are exploratory pointwise, conditional on fitted models, not multiplicity-adjusted.

Recompute component performance, unchanged-composite support-only performance, no-measurement-indicator and high-missingness variants, support-only refit, patient-disjoint recalibration and SHAP. Uncertain outcome scenarios use fixed predictions with unknowns set0/all1, not strict bounds or true labels. Retain hospital overlap disclosure for recalibration. New hospital-independent updating and nested CV from the optimization draft are not silently added to this run.

Write new outputs only to this analysis directory and data/imv_revision_20261007. Old main manuscript remains historical until all new counts and results are reconciled; do not mix versions or call new outputs submission-ready automatically. Patient records and model bundles remain local_only.
