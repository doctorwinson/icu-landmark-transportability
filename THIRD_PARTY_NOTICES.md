# Third-party code

The following public upstream SQL snapshots were retained from the extraction
implementation. They are code, not database records. Their hashes are recorded in
`PUBLIC_FILES.json`; an upstream commit SHA was not captured at the original
download, so these are not represented as commit-pinned downloads. Two numeric
ICU-stay examples were removed from comments in `mimic_ventilation_upstream.sql`
for this code-only release. Executable SQL and the upstream copyright are retained.

| Local file under `analysis/rebuild_20261006/source_audit/` | Original source | License |
| --- | --- | --- |
| `mimic_antibiotic_upstream.sql` | [MIT-LCP/mimic-code antibiotic.sql](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/medication/antibiotic.sql) | MIT, copyright 2019 MIT Laboratory for Computational Physiology |
| `mimic_ventilation_upstream.sql` | [MIT-LCP/mimic-code ventilation.sql](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/treatment/ventilation.sql) | MIT, same notice |
| `eicu_pivoted_uo_upstream.sql` | [MIT-LCP/eicu-code pivoted-uo.sql](https://github.com/MIT-LCP/eicu-code/blob/main/concepts/pivoted/pivoted-uo.sql) | MIT, copyright 2015 MIT Laboratory for Computational Physiology |

Full notices are in `LICENSES/mimic-code.txt` and `LICENSES/eicu-code.txt`.
The antibiotic patterns, ventilator-mode vocabulary and urine-output path rules
extracted or adapted from these files remain covered by those notices, including
their use in the generated SQL templates.

The scripts parse the snapshots as text. **Do not execute the upstream snapshots
against your database.** Some include upstream CREATE/DROP statements; those
statements are not the read-only extraction workflow. Public-release scripts fail
if a snapshot is missing instead of silently downloading a changing `main` branch.

Python and R dependencies are separately distributed projects under their own
licenses. The study code license does not relicense dependencies or grant database
access or redistribution rights.
