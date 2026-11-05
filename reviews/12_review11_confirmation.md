# Review 12: confirmation of review 11 (M1)

Independent reviewer, 4 Nov 2026, at commit 2982164 (with 130b12f built beside it, to tell new defects from old). Saved by the designer from the reviewer's hand-back. The reviewer's probes joined the suite in `tests/review12/`, with their verdicts in `check.py`.

The suite passed (44 of 44 steps, 836 s), and `git status` was clean after it. No BLOCKER.

**Review 11 closures:** N1, N2, N6, N7, N8 and N9 hold. N4 and N5 hold for the cases they name, with more in R1, R3 and R4. N3 holds for its case, not in general (R2).

**Found sound:** the markers held in eight cases (never filled, no uuids, one shared uuid, uuids equal to markers, a footprint and edge lines already using marker ids, zones in a group, a rule area, a footprint pasted twice as identical text, a footprint zone moved in the same edit), each one file over three runs, fills pcbnew's, zone uuids kept, no marker in the output; the badge's 40-zone board gave the same; the output contract held for 40 runs; badge re-saves compare identical; holes are handled.

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| R1 | SHOULD-FIX | Diff's copper graphics key dropped font size, thickness, bold, justification, mirroring, the knockout flag and arc points inside a polygon: six changes reported identical, a regression from 130b12f. | Fixed. Board and footprint graphics compare whole as canonical text (`graphic_canon`, `src/diff.rs`): every child that places or shapes the item, with only KiCad's re-save spellings read alike. `tests/review12/diff12.py`, 22 changes seen. |
| R2 | SHOULD-FIX | With two prewire stubs from one pad, the walk from the stub the router never joined ran through the pad into the other stub, so the unjoined stub was pruned and a route that should be rejected came back done. | Fixed. The walk stops at the board's own copper (pad, via, fill, input track), at a junction of three or more prewire tracks, and at a change of layer (`src/route.rs`). Probe `two_stubs_one_pad`: the unjoined stub is kept and the route is judged with it. |
| R3 | NOTE | Diff missed width, fill, text and position changes of a footprint's copper items. | Fixed by R1: footprint items compare whole. `diff12.py`. |
| R4 | NOTE | Re-saves of hand-written text showed changes: a `gr_poly` with no stroke, a `gr_arc` whose ends pcbnew swaps, a hand-written dimension, a pad's spoke angle 90. | Fixed. A missing width is 0; arc ends compare in either order; a dimension compares by type, layer, points, height and line thickness; the spoke angle defaults to 90. `diff12.py`, 16 re-saves identical. |
| R5 | NOTE | A zone with no polygon was refused with "the filled board has 4 zones, the candidate 5". | Fixed. Refused with the zone named: "zone 5 (GND) has no outline polygon; KiCad would drop it". Probe `zone_without_polygon`. |
| R6 | NOTE | `-o` a folder or in a missing folder, and `--work` a file, failed as `io` without a path, the first only after DRC. | Fixed. Edit and route check both before any work and refuse (`usage`) with the path named. |
| R7 | NOTE | `info --net` with an unknown net gave done with empty lists and a length of -0.0. | Fixed. Refused (`unknown-net`); the length is written as 0. |

The designer's suite run after these fixes caught one flaky check, not a review finding: review 8's mutation `set_width_uuid_changed` replaced the first character of a random uuid with `f`, so it changed nothing whenever the uuid already began with `f` (1 run in 16). It now always swaps that character for a different one.
