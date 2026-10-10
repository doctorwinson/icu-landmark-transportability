# Data access and publication boundary

MIMIC-IV v2.2 and eICU-CRD v2.0 are credentialed-access databases. Use your own
approved account, required training and data-use agreement. This repository does
not provide a download proxy, credentials or transferable access rights.

Official sources, checked on 2026-10-10:

- [MIMIC-IV v2.2](https://physionet.org/content/mimiciv/2.2/)
- [MIMIC-IV license](https://physionet.org/content/mimiciv/view-license/2.2/)
- [eICU v2.0](https://physionet.org/content/eicu-crd/2.0/)
- [eICU license](https://physionet.org/content/eicu-crd/view-license/2.0/)

The currently displayed licenses require protecting restricted data and sharing
associated publication code. Code sharing does not authorize data sharing. Each
user must follow the agreement applicable to their access; this document is not a
substitute for it or an institutional determination.

## Never commit

- Raw or derived patient rows, even after removing names or replacing identifiers.
- Patient, admission, ICU-stay or hospital identifier values and split membership.
- Individual time series, event timestamps, narrative extracts or case-review lists.
- Predictions, SHAP values at patient level, resampling memberships and model objects.
- Database dumps, credentials, `.pgpass`, environment files or cloud access keys.
- SQL query results, hospital-level outputs, logs, notebooks with saved outputs,
  screenshots, manuscripts, archives or backups from the research workspace.

This release omits all statistical outputs, including aggregate tables. The
extraction and analysis code will create restricted local files when run by an
authorized user. Ignoring them in Git is a safeguard, not anonymization and not
permission to distribute them by another route.

Run `python tools/check_release.py` before every commit and push. Only the reviewed
file allowlist may be staged. If a secret or restricted file enters history, stop
publication, revoke the credential where applicable and follow the data provider's
incident process; deleting the latest file alone does not remove prior exposure.

For questions, open issues containing only code, schemas or independently invented
examples. Do not paste patient records or upload clinical outputs to an issue,
pull request, external AI service or CI artifact.
