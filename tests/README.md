# pcb tests

`cargo xtask test` runs everything from a clean checkout. Run it in the pinned image (`ci/Dockerfile`) before every push that touches the tool; there is no CI test run, so this local run is the check. It needs `PCB_FREEROUTING_JAR`, or `--fast`, which skips the Freerouting runs and the mutation suites. The summary is written to `target/xtask/summary.json`.

- A step that passed is not run again while its inputs are unchanged: its scripts, the shared test files, the `pcb` binary and the steps it reads from (a mutation suite: the files it damages and the oracle). `cargo xtask test --full` clears that cache and runs everything; run it before a milestone gate or a release.
- `cargo xtask test --list` prints, for each command, the steps that cover it.
- `cargo xtask test --only WORD` runs the unit tests, `pcb doctor` and the steps whose id, folder or `covers` is WORD: `--only zone`, `--only r18`, `--only m4_cases`. A fixture runs under its own name, or all of them under `fixtures`.

## Layout

| Folder | What it holds |
| --- | --- |
| `cases/` | One case file per command, each case with the outcome it must have, listed in `cases/steps.toml`: `import_cases.py`, `orient_cases.py` (footprints at every rotation), `route_cases.py`, `edit_cases.py`, `diff_cases.py` (on the boards `edit_cases.py` writes), `contract_cases.py` (output contract, codes, doctor, `init`, `status`), `adapter_cases.py` (the KiCad adapter's DRC reading), `zone_cases.py`, `release_cases.py` (check, gate, release, compare-gerbers, paste, art), `m4_cases.py` (parts, sync, footprints, place, drawing). `cargo xtask test --list` shows which file covers a command |
| `fixtures/<name>/` | Real boards. Each holds a `fixture.toml` with every board fact the checks need, so no shared check names a part. `[[route]]` cases run `pcb route` on the imported board with an expected outcome and `still_open` nets; `[zones]` runs `pcb zone` twice with the fixture's `pcb.toml` (same bytes both times) and the result goes to verify_zones; `[[edit]]` cases run `pcb edit`; `[release]` runs the release flow and compares it with the files that were ordered; `[flow]` runs a project from its netlist to the release (M4) |
| `oracles/` | Independent checks of a command's result, reading boards with pcbnew or `lib/kisexp.py`, never pcb's own parser: `verify_import`, `verify_route`, `verify_zones`, `verify_edit`, `verify_release`, `verify_sync` (the board against its netlist and JLCPCB's footprints), `verify_drawing` (the drawing against the board and the CPL), `verify_against_v1` (holes, paste and mask against paddle-keyer v1.0.0's Gerbers) |
| `mutations/` | For each oracle, deliberately damaged results it must fail on, plus the undamaged one it must pass |
| `lib/` | Builders for synthetic inputs, and the output-contract checker |

## Order

Unit tests, the release build, `pcb doctor`, the edge cases, the fixtures, then the cases marked `after_fixtures`: `m4_cases.py` reads the `paddle_keyer_m4` fixture's finished project (`PCB_M4_PROJECT`) instead of routing it again, and skips those cases, listing them, without it.

## Reviews

A review's findings become cases in the command's case file, each marked `# source: review NN, <name>`, built with the shared builders in `lib/`. The reviewer writes the input and the expected outcome; their probe scripts stay with the report in `docs/reviews/` and do not run in the suite. A confirmation review re-runs the finding's case and adds a case only for a new finding. `docs/reviews/audit/` records where each verdict of reviews 8 to 20 went.

## Rules

- **No shared check names a board.** Board facts (hole names, back-side parts, keep-outs, nets, expected fills, allowed DRC kinds) live in that board's `fixture.toml`.
- **Oracles come from someone else.** Each oracle is written or reviewed by an independent reviewer against the spec. A reviewer's oracle and mutations join the suite.
- **A check without a mutation does not count.** Each oracle check needs a mutation in `mutations/` that it catches.
- **Reviewers' verdicts stay theirs.** A ported case keeps the reviewer's input and expected outcome; a change to either needs the reason in a comment.
- **New fixture:** copy the board's inputs into `fixtures/<name>/`, write its `fixture.toml`, and run the suite. `xtask` picks up every folder that has a `fixture.toml`.
- **New case:** add it to the command's case file; a new case file needs a `[[step]]` in `cases/steps.toml`.
