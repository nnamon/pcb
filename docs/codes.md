# Error and warning codes

Every `pcb` error and warning carries one of these codes (see `src/contract.rs` and `schemas/`). A test fails if the code uses a code that is not listed here.

## Errors

| Code | Outcome | Meaning | What to do |
| --- | --- | --- | --- |
| `usage` | refused | The command line is wrong | Read the message and `pcb <command> --help` |
| `refused` | refused | The input has something the command does not handle; the message names it | Change the input, or extend the command with a test |
| `kicad-format` | refused | The board file is not in KiCad 10's format (version 20260206): older, or from a newer KiCad | Older: convert a copy with `kicad-cli pcb upgrade <file>` and check it in KiCad. Newer: test pcb on that KiCad first |
| `drc-truncated` | refused | KiCad listed only its first 199 (clearance: 499) violations of a type, so the DRC is incomplete and changes from run to run | Fix the design rules or the board until every type is under the limit; turn off checks that cannot apply in the project file |
| `exists` | refused | `pcb init` would overwrite a project file | Edit the existing pcb.toml, or move it aside |
| `config` | refused | pcb.toml does not parse, has an unknown key or another schema, or has values that are wrong (each named in `data.problems` for `pcb status`) | Fix the keys the message names |
| `edit-op` | refused | An edit operation is malformed: not JSON, an unknown operation or field, a missing value, a point off the board, or two operations on one item | Fix the operation the message names |
| `edit-no-target` | refused | No item, or more than one, where an operation points | Check the position with `pcb info --net`, or name the item by uuid |
| `edit-mismatch` | refused | The item is there but not as the operation expects (another net, width or position): the board has changed under the edit | Read the board again and rewrite the operation |
| `edit-locked` | refused | The item is locked | Add `"unlock": true` to the operation if changing it is meant |
| `edit-unjoined` | refused | New copper touches no copper of its net at an end | Fix the point, or mark the end free (`free_start`, `free_end`, `free`) |
| `unknown-net` | refused | A net named in `--nets` or `--rip` is not on the board | Check the name with `pcb info --net` |
| `non-ascii-net` | refused | A net name has non-ASCII characters, which Freerouting cannot take | Rename the net |
| `arc-unsupported` | refused | The board has track arcs, which `pcb route` does not handle yet | Replace the arcs with segments, or route by hand |
| `bad-layer` | refused | A routing layer is not a copper layer of the board | Use the board's copper layer names |
| `tools-mismatch` | refused | `pcb doctor` found a tool version or behaviour other than the pinned one | Install the pinned versions (tools/pcb/ci/Dockerfile) or re-test pcb on the new ones |
| `rejected-onto-input` | refused | A rejected result's file name is the input board | Choose another `--out` |
| `output-in-work` | refused | The output is pcb's own work file | Choose another `--out` |
| `image-too-large` | refused | The render would exceed 200 million pixels | Lower `--scale` or render a region |
| `panic` | failed | pcb itself crashed; the message holds where | Report it with the command line |
| `kicad` | failed | KiCad's Python module failed (DSN export, fill, DRC) | Run `pcb doctor`; read the message's KiCad output |
| `freerouting` | failed | Freerouting did not start, or wrote no session | Run `pcb doctor`; read the log in the message |
| `freerouting-settings` | failed | Freerouting logged that it did not apply a setting pcb gave it (and would have routed with its default) | Read the lines in the message; the jar may not be the pinned 2.5.0, or the flag changed |
| `freerouting-timeout` | failed | Freerouting ran past `--timeout`, often stuck on an import dialog | Read the warnings in the message |
| `io` | failed | A file could not be read or written | Check the path and permissions |

## Warnings

| Code | Command | Meaning |
| --- | --- | --- |
| `source-errors` | import-tscircuit | The circuit JSON has tscircuit error elements (counted by kind) |
| `layer-count` | import-tscircuit | `--layers` differs from the JSON's `num_layers` |
| `cross-net-allowed` | import-tscircuit | A trace allowed by `--allow-cross-net` ends on another net's port |
| `mechanical-pad` | import-tscircuit | A pad with no port was written as mechanical pad MP |
| `no-freerouting` | doctor | No Freerouting jar was given |
| `config-mismatch` | status | pcb.toml names a net, footprint, pad or layer the board lacks, or a different layer count |
| `version-mismatch` | status | pcb.toml's version differs from the project's VERSION file |
| `drc-not-run` | status | KiCad DRC could not be used (for example `drc-truncated`); the message says why |
| `still-open` | route | A requested net is still not fully connected |
| `pinless-net` | route | A net with copper but no pads was declared to Freerouting |
| `join-outside-region` | route | The router joined tracks wholly outside the region in their middle; they were left unsplit |
