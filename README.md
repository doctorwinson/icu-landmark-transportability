# ICU landmark transportability

SQL, Python and R code for a 24-hour landmark study of deterioration risk in
record-assessable ICU infection and sepsis cohorts. The analysis examines how
organ-support documentation and outcome ascertainment limit transport between
MIMIC-IV v2.2 and eICU-CRD v2.0.

**Code-only release.** No patient records, identifiers, data extracts, split
memberships, predictions, fitted models, statistical output tables or manuscript
files are distributed here. Both databases require credentialed access; they are
not unrestricted open data. The MIT code license grants no rights to their data.

## Contents

| Directory | Purpose |
| --- | --- |
| `analysis/rebuild_20261006/` | Raw-timestamp extraction, feature definitions and initial amended-cohort assembly |
| `analysis/imv_rule_confirmation_20261007/` | Conservative IMV protocol amendment |
| `analysis/imv_full_revision_20261007/` | Final IMV rules, reconciliation, model fitting and uncertainty analysis |
| `analysis/manuscript_review_revision_20261007/` | Descriptive and calibration extensions |
| `analysis/submission_preflight_20261009/` | ROC, precision-recall, calibration, decision-curve and SHAP plotting |
| `tools/` | Code-release checks that do not connect to a database |
| `docs/` | Execution order, dependencies, data restrictions and release provenance |

The dated stage names preserve the dependency structure of the study. Earlier
cohort assembly is a dependency for reconciliation, not an alternative final
analysis. Original numbering is not execution order: read the workflow below.

## Start here

1. Read [data restrictions](docs/DATA_ACCESS.md) and obtain your own authorized
   access to the source databases before attempting extraction.
2. Read the [execution and input guide](docs/REPRODUCTION.md). Exact reproduction
   additionally requires controlled historical split and QC inputs that are not
   public. A new split is a new analysis, not the published frozen analysis.
3. For a data-free code check, run:

```sh
python tools/check_release.py
python -m unittest discover -s tests -v
Rscript tools/check_r_syntax.R
git config core.hooksPath .githooks
```

These checks validate release contents, Python/R syntax and a plotting-boundary
regression test. They do not establish clinical label accuracy or rerun the study.

## Interpretation

The target population is selected by record assessability. Indeterminate first-day
IMV excludes eligibility; indeterminate follow-up IMV is not automatically a
negative outcome. A definite positive component can still establish a positive
composite. Absence of recorded events is not verified absence of clinical events.
Independent clinician IMV adjudication has not been completed. This is research
code, not a clinical decision tool or a deployment-ready probability model.

## Citation and licensing

Use the version-specific citations in [CITATIONS.md](CITATIONS.md) when using the
databases. Project code is MIT licensed; third-party SQL retains its original MIT
notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `LICENSES/`.
Release changes and development provenance are recorded in
[PROVENANCE.md](docs/PROVENANCE.md).

The manuscript was unpublished at this code release. No publication DOI or
acceptance status is implied.

## 中文说明

这是公开代码仓库，不是患者数据仓库。不要把数据库导出、患者 ID、训练/测试划分、
病例核对表、预测结果、模型对象或运行日志提交到 GitHub。标识符字段名和 SQL 参数
保留是为了代码可读和复核，不代表发布了患者标识符的实际取值。

仓库提供源代码与运行依赖说明，但历史受控划分和质控输入未公开，因此不是无数据
一键复现包。请勿移除已有校验、跳过未知状态规则或生成新划分后声称复现了原稿结果。
