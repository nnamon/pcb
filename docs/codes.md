# Error and warning codes

Every `pcb` error and warning carries one of these codes (see `src/contract.rs` and `schemas/`). A test fails if the code uses a code that is not listed here.

## Errors

| Code | Outcome | Meaning | What to do |
| --- | --- | --- | --- |
| `usage` | refused | The command line is wrong | Read the message and `pcb <command> --help` |
| `refused` | refused | The input has something the command does not handle; the message names it | Change the input, or extend the command with a test |
| `unknown-net` | refused | A net named in `--nets` or `--rip` is not on the board | Check the name with `pcb info --net` |
| `non-ascii-net` | refused | A net name has non-ASCII characters, which Freerouting cannot take | Rename the net |
| `arc-unsupported` | refused | The board has track arcs, which `pcb route` does not handle yet | Replace the arcs with segments, or route by hand |
| `bad-layer` | refused | A routing layer is not a copper layer of the board | Use the board's copper layer names |
| `tools-mismatch` | refused | `pcb doctor` found a tool version or behaviour other than the pinned one | Install the pinned versions (tools/pcb/ci/Dockerfile) or re-test pcb on the new ones |
| `kicad` | failed | KiCad's Python module failed (DSN export, fill, DRC) | Run `pcb doctor`; read the message's KiCad output |
| `freerouting` | failed | Freerouting did not start, or wrote no session | Run `pcb doctor`; read the log in the message |
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
| `still-open` | route | A requested net is still not fully connected |
| `pinless-net` | route | A net with copper but no pads was declared to Freerouting |
| `join-outside-region` | route | The router joined tracks wholly outside the region in their middle; they were left unsplit |
