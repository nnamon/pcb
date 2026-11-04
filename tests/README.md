# pcb tests

`cargo xtask test` runs everything from a clean checkout, and CI runs the same command in the pinned image (`ci/Dockerfile`) on every push that touches `tools/pcb`. It needs `PCB_FREEROUTING_JAR`, or `--fast`, which skips the Freerouting runs and the mutation suites. The summary is written to `target/xtask/summary.json`.

| Folder | What it holds |
| --- | --- |
| `cases/` | Edge cases with the outcome each must have. `import_cases.py` (38 circuit-JSON cases), `orient_cases.py` (8 footprints at every rotation), `route_cases.py` (18 runs on synthetic boards), `edit_cases.py` (27: each operation, each refusal, duplicates, floating new copper, a zoned board run twice, the gate's verdict), `diff_cases.py` (9, on the boards `edit_cases.py` writes, plus a git revision), `contract_cases.py` (output contract, codes, doctor, `init` and `status`, and the contract checker's own sensitivity), `adapter_cases.py` (the KiCad adapter's DRC reading), `zone_cases.py` (`pcb zone` on `lib/zone_board.py`: each feature, refusals, the DRC allowance, determinism, a second run, a changed stitching pitch) |
| `oracles/` | Independent checks of a command's result, reading boards with pcbnew or `lib/kisexp.py`, never pcb's own parser: `verify_import.py`, `verify_route.py`, `verify_zones.py`, `verify_edit.py` (the output differs from the input by exactly what the operations ask) |
| `mutations/` | For each oracle, deliberately damaged results it must fail on, plus the undamaged one it must pass |
| `fixtures/<name>/` | Real boards. Each holds a `fixture.toml` with every board fact the checks need, so no shared check names a part. Its `[[route]]` cases run `pcb route` on the imported board, each with an expected outcome, `still_open` nets and optionally `attempt_used`; a fixture with `[zones]` has a `pcb.toml` that `pcb zone` runs with, twice, and the result goes to verify_zones; its `[[edit]]` cases run `pcb edit`, each with an outcome, an error code or DRC regressions that must be reported, and `verify_edit` on every written result |
| `review8/` | Review 8's probe scripts, kept as cases: edit, diff, init and status, route (`--prewire` with `--rip`, `--width`), `verify_edit`'s mutations, and `move_footprint` against pcbnew's own move |
| `review9/` | Review 9's cases: the gate's fill carry-back on zones with and without uuids and in footprints (`zone_gate_cases.py`), the join rule, diff misses, the router's choice between runs driven by a stand-in java (`fake/`), and prewire with `--rip`. `expect_pass.py` turns their PASS and FAIL lines into an exit status |
| `review10/` | Review 10's probes (zone pairing without uuids and in copied footprints, joins through stale or empty fills, diff on KiCad re-saves and copper graphics, multi-segment prewire stubs), with their verdicts in `check.py` |
| `review11/` | Review 11's probes (the gate's markers on never-filled, hand-written and copied zones; prewire stubs anchored in a never-filled zone or joined at a bend; diff misses and KiCad re-saves of hand-written text), with their verdicts in `check.py` |
| `review12/` | Review 12's probes (markers against colliding ids, shared uuids, groups and pasted footprints; copper text and graphics changes and re-saves; two prewire stubs at one pad), with their verdicts in `check.py` |
| `review13/` | Review 13's probes of `pcb zone` (stitching, features, net ties, refusals, the fill flag, the badge), with their verdicts in `check.py` |
| `review14/` | Review 14's probes confirming review 13's closures (fills against refills, overrides, stitching around custom pads and rule areas, ties, refusals, the badge), with their verdicts in `check.py` |
| `lib/` | Builders for synthetic inputs, and the output-contract checker |

Rules:

- **No shared check names a board.** Board facts (hole names, back-side parts, keep-outs, nets, expected fills, allowed DRC kinds) live in that board's `fixture.toml`.
- **Oracles come from someone else.** Each oracle is written or reviewed by an independent reviewer against the spec. A reviewer's oracle and mutations join the suite.
- **A check without a mutation does not count.** Each oracle check needs a mutation in `mutations/` that it catches.
- **New fixture:** copy the board's inputs into `fixtures/<name>/`, write its `fixture.toml`, and run the suite. `xtask` picks up every folder that has a `fixture.toml`.
