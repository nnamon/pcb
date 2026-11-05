# Review 9: confirmation of review 8 (M1)

Independent reviewer, 4 Nov 2026, at commit 35f46ff. Saved by the designer from the reviewer's hand-back. The reviewer's scripts joined the suite in `tests/review9/`.

The suite passed (37 of 37 steps, 675 s) and the unit tests (47).

**Review 8 closures:** 1, 2, 4, 5, 6, 8, 9, 10, 11, 13 to 19 hold, each reproduced with the reviewer's own inputs (real Freerouting for 1, crafted sessions for 2, a fake `java` driving all eight branches of the run choice for 17). 12 holds as scoped. 3 held only for zones with uuids, and 7 did not hold: see 1, 2 and 4 to 6 below.

**Found sound:** fill carry-back on zones with uuids (several zones on one net, a two-layer zone, rule areas, a zone that fills to nothing, a one-line zone) is byte-identical outside the fills, repeatable, and loads in kicad-cli; prewire copper is never ripped or pruned, and input copper on a ripped net still is; the join rule accepts the legitimate edits tried and refuses floating copper; the output contract held for 21 runs; diff on KiCad re-saves of the synthetic boards is identical.

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| 1 | SHOULD-FIX | `splice_fills` paired zones without uuids by file order, which pcbnew's save changes: a legitimate edit refused on two nets; two GND zones on F.Cu and B.Cu got each other's fills; two on F.Cu gave different files from run to run. | Fixed. Zones are found by uuid, or by owner, net, layers and outline (`zone_list`, `src/gate.rs`), with a unit test of reordered zones. `tests/review9/zone_gate_cases.py` edits the reviewer's zone board with and without uuids, three times each: the same bytes, the input plus the edit outside the fills, every fill equal to pcbnew's refill. It fails on the old build. |
| 2 | SHOULD-FIX | The gate never refilled zones inside footprints, so a stale footprint fill gave a false clearance regression; a board with only footprint zones was not filled at all. | Fixed. The helper fills footprint zones too, the carry-back covers them, and any board with a zone is filled. Case `footprint_zone` in `zone_gate_cases.py`: a B.Cu track across FZ1's GND zone is done, not rejected. |
| 3 | SHOULD-FIX | `move_via` refused every stitching via, which joins only through a fill. | Fixed. A fill of the net counts as copper for joins (a zone never filled counts by its outline). Probe `move_stitching_via` reaches the gate, which then judges the move (`tests/review9/join_probes.py`). |
| 4 | SHOULD-FIX | Diff compared pad layers in file order, so a KiCad re-save of the badge showed 258 footprints changed. | Fixed. Pad layers compare as a set. The badge against its re-save is identical; probe `pad_layer_order_only`. |
| 5 | SHOULD-FIX | Diff missed a via's layers, a lock on a track arc, and a zone's second outline. | Fixed. Vias carry their layers (`Via::layers`) in the key; arc locks count; zones keep every outline polygon (`Zone::outlines`). `tests/review9/diff_misses.py`. |
| 6 | NOTE | Diff missed a zone's clearance, a footprint's own Edge.Cuts, a footprint's value. | Fixed. Zones are compared with the settings that change copper (`Zone::settings`); footprints report "edge cuts changed" and "value changed". Same script. |
| 7 | NOTE | `set_width` on a track fed only through a fill was refused, with a message about new copper. | Fixed by 3; the message now says "new or changed copper". Probe `set_width_zone_fed_track`. |
| 8 | NOTE | A prewire stub the router joined mid-length left a tail that was never pruned, so the route was rejected. | Fixed. The free end of a prewire stub, past the router's join, may be pruned; every other prewire piece is kept. Probe `p3_router_joins_middle_of_prewire_stub` (`tests/review9/prewire_probes.py`). |
| 9 | NOTE | When the other run was kept, the preferred run's `.rejected.kicad_pro` was left behind. | Fixed. `gate::remove_result` removes the rejected board and its project files. |
| 10 | NOTE | Edit with a missing board and status with a missing pcb.toml failed as `io`; a bare TOML date gave a type error. | Fixed. Edit refuses a missing board (`usage`); status refuses a missing pcb.toml (`config`); the date error says to quote dates. |
| 11 | NOTE | `--width N=inf` was accepted. | Fixed. A width must be above 0 and at most 25 mm; edit widths, sizes and drills must be finite. |

The reviewer's route-branch check compared the number of segments in the file with an exact count; a track split at two points breaks that count, so the suite's copy checks a lower bound and the reported run's segment count.
