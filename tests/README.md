# pcb tests

`cargo xtask test` runs everything from a clean checkout, and CI runs the same command in the pinned image (`ci/Dockerfile`) on every push that touches `tools/pcb`. It needs `PCB_FREEROUTING_JAR`, or `--fast`, which skips the Freerouting runs and the mutation suites. The summary is written to `target/xtask/summary.json`.

| Folder | What it holds |
| --- | --- |
| `cases/` | Edge cases with the outcome each must have. `import_cases.py` (38 circuit-JSON cases), `route_cases.py` (8 synthetic boards), `contract_cases.py` (output contract, codes, doctor, and the contract checker's own sensitivity) |
| `oracles/` | Independent checks of a command's result, reading boards with pcbnew alone: `verify_import.py`, `verify_route.py`, `verify_zones.py` |
| `mutations/` | For each oracle, deliberately damaged results it must fail on, plus the undamaged one it must pass |
| `fixtures/<name>/` | Real boards. Each holds a `fixture.toml` with every board fact the checks need, so no shared check names a part |
| `lib/` | Builders for synthetic inputs, and the output-contract checker |

Rules:

- **No shared check names a board.** Board facts (hole names, back-side parts, keep-outs, nets, expected fills, allowed DRC kinds) live in that board's `fixture.toml`.
- **Oracles come from someone else.** Each oracle is written or reviewed by an independent reviewer against the spec. A reviewer's oracle and mutations join the suite.
- **A check without a mutation does not count.** Each oracle check needs a mutation in `mutations/` that it catches.
- **New fixture:** copy the board's inputs into `fixtures/<name>/`, write its `fixture.toml`, and run the suite. `xtask` picks up every folder that has a `fixture.toml`.
