# Execution and input guide

## Status

This is the source implementation for the final conservative IMV amendment, not a
standalone exact-reproduction bundle. Data extraction is read-only with respect
to PostgreSQL, but writes restricted local files. No clinical analysis runs in
GitHub Actions. Run only inside an authorized, access-controlled environment.

Python dependencies are listed in `requirements.txt`. The original R run used
R 4.5.2, xgboost 1.7.8.1, glmnet 4.1-8, arrow 23.0.1.2, pROC 1.18.5, PRROC 1.4,
ggplot2 4.0.1, patchwork 1.3.0, Matrix 1.7-4, dplyr 1.1.4, tidyr 1.3.1,
tibble 3.2.1, readr 2.1.5, purrr 1.0.4, stringr 1.5.1, yaml 2.3.10,
jsonlite 1.9.1, scales 1.4.0, knitr 1.50 and digest 0.6.37. These are recorded
versions, not an independently tested installation lockfile. Package changes can
change results; do not silently substitute a current XGBoost API.

## Local connection

Scripts read `PGHOST` (default localhost), `PGPORT` (default 5432), `PGUSER`
(required), `MIMIC_DB` (default mimic4_v22) and `EICU_DB` (default eicu).
Use libpq's password file outside this repository, or another secure local libpq
authentication method. Never put passwords in source, command history or Git.

The source schemas are `mimiciv_hosp`, `mimiciv_icu` and `eicu_icu`. Local schema
differences require explicit mapping review. A database named mimic4_v22 is not
itself proof that the contents are v2.2. Confirm the installed data release.

## Stage order

| Order | Script | Inputs and outputs |
| --- | --- | --- |
| 1 | `analysis/rebuild_20261006/rebuild_raw_features.py` | Authorized databases and bundled upstream code; writes raw predictor/lineage Parquet files under local `data/` |
| 2 | `analysis/rebuild_20261006/rebuild_infection_evidence.py` | Raw candidate identifiers and database source records |
| 3 | `analysis/rebuild_20261006/rebuild_support_evidence.py` | Source records; writes support evidence and oxygenation layers |
| 4 | `analysis/rebuild_20261006/assemble_amended_cohort.py` | Raw layers; creates the prior amended cohort needed for transitions |
| 5 | `analysis/rebuild_20261006/validate_raw_cohort.py` | Prior cohort plus historical entry-time source audit; see unavailable-input list |
| 6 | `analysis/imv_full_revision_20261007/01_rebuild.py` | Full screened cohort and database records; applies conservative IMV rules |
| 7 | `analysis/imv_full_revision_20261007/04_qc_freeze.py` | Full reconstruction, previous cohort, historical split/grid and targeted routing inputs; creates pre-fit QC lock |
| 8 | `analysis/imv_full_revision_20261007/02_refit.R` | QC lock and controlled split; tunes on internal validation, fits models, then evaluates external data |
| 9 | `analysis/imv_full_revision_20261007/03_uncertainty.R` | Locally fitted predictions; cluster resampling and sensitivity intervals |
| 10 | `analysis/imv_full_revision_20261007/06_verify_results.R` | Local fits, splits and computed results; reconciles numerical outputs |
| 11 | `analysis/manuscript_review_revision_20261007/01_descriptive_extensions.py` and `02_calibration_extensions.R` | Frozen reconstructed states and predictions; no relabeling or model selection |
| 12 | `analysis/submission_preflight_20261009/01_figures.R` | Frozen predictions and calibration outputs; generates statistical Figures 2-4 |

Use `python path/to/script.py` or `Rscript path/to/script.R`; the R stage scripts
resolve their location through `--file`. Sourcing them interactively without that
argument is not a supported entrypoint. The cohort flowchart and Word generation
are presentation assets outside this source-only release.

SQL files containing `%s` are parameterized psycopg2 query templates, not complete
DBeaver scripts. Supply authorized cohort IDs through bound parameters; never
replace them with patient ID literals in published source. The upstream SQL
snapshots under `source_audit/` are parser inputs, not execution scripts.

## Required inputs deliberately not supplied

| Input | Why it is absent / implication |
| --- | --- |
| `data/raw_timestamp_rebuild_20261006/*.parquet` | Patient-level source-derived records; regenerate only with authorized access |
| `data/amended_cohort_20261006/*.parquet` | Prior cohort required for old/new reconciliation |
| `analysis/rebuild_20261006/results/split_ids_local_only.rds` | Historical patient/stay membership; replacing it changes the analysis |
| `analysis/rebuild_20261006/results/tuning_leaderboard.csv` | Historical result table supplying the original 64 candidate rows; no result tables are published here |
| `analysis/rebuild_20261006/source_audit/eicu_entry_missing.json` | Historical database audit output required by the initial QC script |
| `analysis/rebuild_20261006/PROTOCOL_AMENDMENT.md` | Earlier audit-freeze input; not the final IMV amendment included here |
| `analysis/imv_rule_confirmation_20261007/local_only/case_routing_for_investigator_review.csv` | Restricted technical routing records; not independently adjudicated clinical labels |
| `local_only/` objects, split files and model/prediction RDS | Restricted analysis intermediates; do not distribute trained objects without separate review |

Some expected sample counts are assertions tied to the study snapshot. Failures
require investigation, not deleting assertions to force the pipeline through.
Obtain permitted controlled inputs through the relevant authorized research
arrangements; this repository does not promise their redistribution. Do not
fabricate empty QC reports, new splits or substitute a new candidate grid while
claiming exact manuscript reproduction.
