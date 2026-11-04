# Error and warning codes

Every `pcb` error and warning carries one of these codes (see `src/contract.rs` and `schemas/`). A test fails if the code uses a code that is not listed here.

## Errors

| Code | Outcome | Meaning | What to do |
| --- | --- | --- | --- |
| `usage` | refused | The command line is wrong, or names a board, file or git revision that is not there | Read the message and `pcb <command> --help` |
| `refused` | refused | The input has something the command does not handle; the message names it | Change the input, or extend the command with a test |
| `kicad-format` | refused | The board file is not in KiCad 10's format (version 20260206): older, or from a newer KiCad | Older: convert a copy with `kicad-cli pcb upgrade <file>` and check it in KiCad. Newer: test pcb on that KiCad first |
| `drc-truncated` | refused | KiCad listed only its first 199 (clearance: 499) violations of a type, so the DRC is incomplete and changes from run to run | Fix the design rules or the board until every type is under the limit; turn off checks that cannot apply in the project file |
| `exists` | refused | `pcb init` would overwrite a project file, or `pcb release` was given a folder that is not empty | Edit the existing pcb.toml, or move it aside; release into a new folder |
| `config` | refused | pcb.toml does not parse, has an unknown key or another schema, or has values that are wrong (each named in `data.problems` for `pcb status`) | Fix the keys the message names |
| `edit-op` | refused | An edit operation is malformed: not JSON, an unknown operation or field, a missing value, a point off the board, or two operations on one item | Fix the operation the message names |
| `edit-no-target` | refused | No item, or more than one, where an operation points | Check the position with `pcb info --net`, or name the item by uuid |
| `edit-mismatch` | refused | The item is there but not as the operation expects (another net, width or position): the board has changed under the edit | Read the board again and rewrite the operation |
| `edit-locked` | refused | The item is locked | Add `"unlock": true` to the operation if changing it is meant |
| `edit-unjoined` | refused | New copper touches no copper of its net at an end | Fix the point, or mark the end free (`free_start`, `free_end`, `free`) |
| `unknown-net` | refused | A net named in `--nets` or `--rip` is not on the board | Check the name with `pcb info --net` |
| `non-ascii-net` | refused | A net name has non-ASCII characters, which Freerouting cannot take | Rename the net |
| `arc-unsupported` | refused | The board has track arcs, which `pcb route` does not handle yet, or a net `pcb zone` absorbs into a net tie has arcs | Replace the arcs with segments, or route by hand |
| `bad-layer` | refused | A routing layer is not a copper layer of the board | Use the board's copper layer names |
| `tools-mismatch` | refused | `pcb doctor` found a tool version or behaviour other than the pinned one | Install the pinned versions (tools/pcb/ci/Dockerfile) or re-test pcb on the new ones |
| `rejected-onto-input` | refused | A rejected result's file name is the input board | Choose another `--out` |
| `output-in-work` | refused | The output is pcb's own work file | Choose another `--out` |
| `image-too-large` | refused | The render would exceed 200 million pixels | Lower `--scale` or render a region |
| `gerber-set` | refused | `compare-gerbers` cannot compare: a set has no board outline, or an explanation names a zone net and no `--board` was given | Give both sets an Edge.Cuts layer; pass `--board` |
| `gate-check` | refused | `pcb gate pass` found unwaived `pcb check` findings | Fix them, or add a `[[waiver]]` with a reason |
| `gate-missing` | refused | `pcb release` found no gate recorded in pcb.toml | Run `pcb check`, then `pcb gate pass NAME` |
| `gate-stale` | refused | `pcb release` found a gate whose inputs (board, pcb.toml, art and fonts) or version changed since it passed | Check again and pass the gate again |
| `panic` | failed | pcb itself crashed; the message holds where | Report it with the command line |
| `kicad` | failed | KiCad's Python module failed (DSN export, fill, DRC) | Run `pcb doctor`; read the message's KiCad output |
| `freerouting` | failed | Freerouting did not start, or wrote no session | Run `pcb doctor`; read the log in the message |
| `freerouting-settings` | failed | Freerouting logged that it did not apply a setting pcb gave it (and would have routed with its default) | Read the lines in the message; the jar may not be the pinned 2.5.0, or the flag changed |
| `freerouting-timeout` | failed | Freerouting ran past `--timeout`, often stuck on an import dialog | Read the warnings in the message |
| `gerbonara` | failed | The Gerber helper (python3 with gerbonara and shapely) failed | Read the message's traceback |
| `sha256sum` | failed | `sha256sum` could not run for the release checksums | Install coreutils |
| `io` | failed | A file that exists could not be read, or one could not be written | Check the path and permissions |
| `netlist` | refused | The netlist (or the schematic's) cannot be read, or two parts share a reference or one is not annotated | Annotate the schematic; check the file |
| `footprint` | refused | `pcb sync`: a part has neither an LCSC code nor a project footprint (`footprints/NAME.kicad_mod` for its Footprint field `LIB:NAME`) | Give the symbol an LCSC field or a project footprint |
| `pin-missing` | refused | `pcb sync`: the netlist connects a pin number the footprint has no pad for | Fix the symbol's pin numbers to the footprint's pads |
| `pin-name` | refused | `pcb sync`: a connected pin's name differs from JLCPCB's symbol (or `[parts.<LCSC>] pins`); the XC6206 trap | Check the datasheet; fix the schematic, or give the datasheet's names in `[parts.<LCSC>] pins` |
| `sync-copper` | refused | `pcb sync`: tracks or vias of a net whose pads change would be left wrong | Run `pcb sync --rip` and route the nets again |
| `locked` | refused | `pcb sync` or `pcb place` would remove, replace or move a locked part | Unlock it, or change the circuit or the place |
| `unknown-ref` | refused | `pcb place`: a `[[place]]` or `--ref` names a part the board does not have | Run `pcb sync` first; check the reference |
| `side` | refused | `pcb place`: an assembled part placed on a side the assembler does not place | Move it, or change `[assembly] machine_sides` |
| `off-board` | refused | `pcb place`: a pad's centre would be outside the outline | Change the place |
| `keepout` | refused | `pcb place`: a part's pads would fall in a `[[keepout]]` that forbids footprints | Change the place or the keep-out |
| `plated-pad` | refused | `pcb place`: a part would cover a plated through-hole pad of a part on the other side | Move one of them |
| `parts-cache` | refused | `pcb sync` or `pcb parts`: a part's EasyEDA data is missing from `parts/` or does not convert | Run `pcb parts --live` |
| `network` | failed | `pcb parts --live` could not reach EasyEDA or JLCPCB, or the reply was not a part | Retry; check the LCSC code |
| `pdf` | failed | `pcb drawing` could not write the PDF | Report it with the SVG sheets |
| `kicad-cli` | failed | kicad-cli could not export the schematic's netlist | Open the schematic in KiCad 10 and check it loads |
| `sync` | failed | `pcb sync`'s own read-back of the board it wrote found a pad on the wrong net (pcb's bug) | Report it with the board and netlist |

## Warnings

| Code | Command | Meaning |
| --- | --- | --- |
| `source-errors` | import-tscircuit | The circuit JSON has tscircuit error elements (counted by kind) |
| `layer-count` | import-tscircuit | `--layers` differs from the JSON's `num_layers` |
| `cross-net-allowed` | import-tscircuit | A trace allowed by `--allow-cross-net` ends on another net's port |
| `net-renamed` | import-tscircuit | Traces or vias carry a net name the circuit has no net for, and land only on one net's ports; they are written on that net, which the message names |
| `mechanical-pad` | import-tscircuit | A pad with no port was written as mechanical pad MP |
| `no-freerouting` | doctor | No Freerouting jar was given |
| `config-mismatch` | status | pcb.toml names a net, footprint, pad or layer the board lacks, or a different layer count |
| `version-mismatch` | status | pcb.toml's version differs from the project's VERSION file |
| `drc-not-run` | status | KiCad DRC could not be used (for example `drc-truncated`); the message says why |
| `still-open` | route | A requested net is still not fully connected |
| `pinless-net` | route | A net with copper but no pads was declared to Freerouting |
| `repeated-ref` | diff | A reference appears more than once on a board; repeats are matched in file order |
| `fill-overlap` | zone | Two nets' fills overlap at the same priority, so which keeps the copper follows KiCad's zone order, not a choice; set `fill_priority` on one |
| `stitch-no-fill` | zone | A `[[stitch]]` net has no fill on some copper layer, so it gets no stitching vias; the message names the net and layer |
| `layer-missing` | compare-gerbers | A layer with something on it is in only one of the two sets |
| `waiver-unused` | check | A `[[waiver]]` matched no finding (stale or misspelt), or its finding counts more than its `max` |
| `bottom-cpl-unverified` | release | The CPL has bottom-side parts, whose rotation convention pcb has not checked against JLCPCB's |
| `version-not-on-board` | release | No `[[text]]` entry prints the project version on the board (`{version}`) |
| `drc-allowed` | zone | A DRC kind grew within its `pcb.toml [[drc_allow]]` allowance; the message names it |
| `second-run-failed` | route | The router's second run (no region keep-outs) failed or timed out; the first run's result stands |
| `join-outside-region` | route | The router joined tracks wholly outside the region in their middle; they were left unsplit |
| `unplaced` | sync, place | Parts added beside the board, or with no `[[place]]` and off the board |
| `ripped` | place | Tracks and vias on a moved part's pads were removed; route those nets again |
| `buy-ahead` | parts, release | A part's JLCPCB stock is under 20 times the order's need, or under 1000 |
| `extended-parts` | parts, release | Extended parts, each a loading fee, listed |
| `parts-stale` | parts, release | JLCPCB data in the cache is over 30 days old |
| `parts-unchecked` | release | The project has no `parts/` cache, so JLCPCB's data was not checked |
| `labels-omitted` | drawing | Designators that would overlap other text were left off a view; the table lists them |
| `plane-split` | route | The new tracks cut a zone net's fills apart (the router leaves zone nets to their zones); run `pcb zone` again |
| `arcs-kept` | sync | The board has track arcs, which `pcb sync --rip` does not remove; check them |
