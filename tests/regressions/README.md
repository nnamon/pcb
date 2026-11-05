# Regression tests

Each folder holds one independent review's probes, kept after its findings closed so they cannot come back. The reviewer wrote them; `check.py` (or `expect_pass.py` in r09) holds the verdict for each case, and cases for findings marked NOTE print under "notes" without failing. The report with every finding and its closure is in `docs/reviews/`.

`cargo xtask test --only rNN` runs one folder; `cargo xtask test --list` shows which folders cover a command.

| Folder | Report | Covers | What the probes test |
| --- | --- | --- | --- |
| `r08/` | `08_m1.md` | edit, diff, init, status, route | edit, diff, init and status; route with `--prewire`, `--rip` and `--width`; `verify_edit`'s mutations; `move_footprint` against pcbnew's own move |
| `r09/` | `09_review8_confirmation.md` | zone, gate, edit, diff, route | the gate's fill carry-back on zones with and without uuids and in footprints; the join rule; diff misses; the router's choice between runs, driven by a stand-in java (`fake/`); prewire with `--rip` |
| `r10/` | `10_review9_confirmation.md` | gate, edit, diff, route | zone pairing without uuids and in copied footprints; joins through stale or empty fills; diff on KiCad re-saves and copper graphics; multi-segment prewire stubs |
| `r11/` | `11_review10_confirmation.md` | gate, diff, route | the gate's markers on never-filled, hand-written and copied zones; prewire stubs anchored in a never-filled zone or joined at a bend; KiCad re-saves of hand-written text |
| `r12/` | `12_review11_confirmation.md` | gate, diff, route | markers against colliding ids, shared uuids, groups and pasted footprints; copper text and graphics changes; two prewire stubs at one pad |
| `r13/` | `13_m2.md` | zone | `pcb zone`: stitching, features, net ties, refusals, the fill flag, the badge |
| `r14/` | `14_review13_confirmation.md` | zone | fills against refills, overrides, stitching around custom pads and rule areas, ties, refusals, the badge |
| `r15/` | `15_m3.md` | check, gate, release, compare-gerbers, paste, art, import | milestone M3: check, gates, release and its read-back, compare-gerbers, paste, art, the import's additions, the badge |
| `r16/` | `16_m3_confirmation.md` | check, gate, release, compare-gerbers, import | the paddle keyer through check, gate and release with stale inputs; read-back limits; compare-gerbers; import; the badge |
| `r17/` | `17_m3_confirmation.md` | check, gate, release, compare-gerbers, import | stale records, the two DRC runs, release fills, compare-gerbers, the gate hash, import silkscreen |
| `r18/` | `18_m4.md` | parts, sync, place, footprint, release | milestone M4: pin numbers and names, EasyEDA conversion, sync, parts, place, the release against v1.0.0 (Freerouting) |
| `r19/` | `19_confirmation.md` | check, sync, footprint, parts, release | stale output, fab fills, pin numbers and names, slots, two-pad turns, re-sync, DNP flags, the v1.0.0 oracle (Freerouting) |
| `r20/` | `20_confirmation.md` | footprint, parts, sync, check | off-centre slots, polarity, DNP flags, re-sync copper, stale comparison (Freerouting) |

Reviews 1 to 7 (M0) left no probe folders.
