# Audit of review probes 8 to 20 (5 Nov 2026)

Reviews 8 to 20 left one probe suite each, re-run on every test run (about 33 of 50 minutes). Each verdict was sorted into one of three:

- **covered:** an existing case, fixture step, oracle check or unit test asserts the same outcome on an equivalent input; the table names it;
- **port:** now a case in its command's case file, marked `# source: review NN, <name>`;
- **evidence:** it tested the review's premise (KiCad's or EasyEDA's own behaviour, a probe's own oracle) or was a note that never failed the run.

| File | Reviews | Covered | Ported | Evidence | Total |
| --- | --- | --- | --- | --- | --- |
| `AUDIT_m1.md` | 8 to 12 | 13 | 218 | 1 | 232 |
| `AUDIT_zone.md` | 9 (zone gate), 13, 14 | 22 | 124 | 26 | 172 |
| `AUDIT_m3.md` | 15 to 17 | 34 | 95 | 37 | 166 |
| `AUDIT_m4.md` | 18 to 20 | 22 | 139 | 39 | 200 |
| All | | 91 | 576 | 103 | 770 |

The audit found one pcb bug: `pcb check` with a reused `--work` folder came back done with no findings (fixed; case in `release_cases.py`). One decision is open: review 17, finding 40, whether the release read-back refuses inner copper too close to another net's hole when the finding is waived (`release_cases.py`, marked "owner decision pending").

The probes themselves are in git history at e17bfac, under `tools/pcb/tests/regressions/`.
