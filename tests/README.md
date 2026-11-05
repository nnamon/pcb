# pcb tests

`cargo xtask test` runs everything from a clean checkout. Run it in the pinned image (`ci/Dockerfile`) before every push that touches `tools/pcb`; there is no CI test run, so this local run is the check. It needs `PCB_FREEROUTING_JAR`, or `--fast`, which skips the Freerouting runs and the mutation suites. The summary is written to `target/xtask/summary.json`.

- `cargo xtask test --list` prints, for each command, the steps that cover it.
- `cargo xtask test --only WORD` runs the unit tests, `pcb doctor` and the steps whose id, folder or `covers` is WORD: `--only zone`, `--only r18`, `--only m4_cases`. A fixture runs under its own name, or all of them under `fixtures`.

## Layout

| Folder | What it holds |
| --- | --- |
| `cases/` | Edge cases, each with the outcome it must have, listed in `cases/steps.toml`. `import_cases.py` (43 circuit-JSON cases), `orient_cases.py` (8 footprints at every rotation), `route_cases.py` (18 runs on synthetic boards), `edit_cases.py` (27: each operation, each refusal, duplicates, floating new copper, a zoned board run twice, the gate's verdict), `diff_cases.py` (9, on the boards `edit_cases.py` writes, plus a git revision), `contract_cases.py` (output contract, codes, doctor, `init` and `status`, and the contract checker's own sensitivity), `adapter_cases.py` (the KiCad adapter's DRC reading), `zone_cases.py` (`pcb zone` on `lib/zone_board.py`: each feature, refusals, the DRC allowance, determinism, a second run), `release_cases.py` (`pcb check` findings and waivers, `pcb gate` refusals and staleness, `pcb release` refusals and files), `m4_cases.py` (on copies of `fixtures/paddle_keyer_m4`: parts, sync, place and drawing) |
| `fixtures/<name>/` | Real boards. Each holds a `fixture.toml` with every board fact the checks need, so no shared check names a part. `[[route]]` cases run `pcb route` on the imported board with an expected outcome and `still_open` nets; `[zones]` runs `pcb zone` twice with the fixture's `pcb.toml` (same bytes both times) and the result goes to verify_zones; `[[edit]]` cases run `pcb edit`; `[release]` runs the release flow and compares it with the files that were ordered; `[flow]` runs a project from its netlist to the release (M4) |
| `oracles/` | Independent checks of a command's result, reading boards with pcbnew or `lib/kisexp.py`, never pcb's own parser: `verify_import`, `verify_route`, `verify_zones`, `verify_edit`, `verify_release`, `verify_sync` (the board against its netlist and JLCPCB's footprints), `verify_drawing` (the drawing against the board and the CPL), `verify_against_v1` (holes, paste and mask against paddle-keyer v1.0.0's Gerbers) |
| `mutations/` | For each oracle, deliberately damaged results it must fail on, plus the undamaged one it must pass |
| `regressions/rNN/` | Review NN's probes, kept as regression tests for its closed findings, each folder with its `steps.toml`. `regressions/README.md` indexes them by review, report and command |
| `lib/` | Builders for synthetic inputs, and the output-contract checker |

## Order

Unit tests, the release build, `pcb doctor`, the edge cases, the fixtures, then the regression tests. Reviews 18 to 20 use the `paddle_keyer_m4` fixture's finished flow (`{flow:paddle_keyer_m4}` in their `steps.toml`) instead of routing it again; run alone, they route it themselves.

## Rules

- **No shared check names a board.** Board facts (hole names, back-side parts, keep-outs, nets, expected fills, allowed DRC kinds) live in that board's `fixture.toml`.
- **Oracles come from someone else.** Each oracle is written or reviewed by an independent reviewer against the spec. A reviewer's oracle and mutations join the suite.
- **A check without a mutation does not count.** Each oracle check needs a mutation in `mutations/` that it catches.
- **Reviewers' probes stay theirs.** A probe in `regressions/` is changed only where the tool's behaviour or the test environment moved, and each change carries a comment starting "designer's edit" that says why.
- **New fixture:** copy the board's inputs into `fixtures/<name>/`, write its `fixture.toml`, and run the suite. `xtask` picks up every folder that has a `fixture.toml`.
- **New case or review:** add a `[[step]]` to `cases/steps.toml`, or a `regressions/rNN/` folder with its own `steps.toml`; `xtask` reads every `regressions/*/steps.toml`.
