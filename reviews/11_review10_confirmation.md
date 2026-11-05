# Review 11: confirmation of review 10 (M1)

Independent reviewer, 4 Nov 2026, at commit 130b12f. Saved by the designer from the reviewer's hand-back. The reviewer's probes joined the suite in `tests/review11/`, with their verdicts in `check.py`.

The suite passed (43 of 43 steps, 815 s). No BLOCKER.

**Review 10 closures:** 2, 3, 8 and 9 hold. 1 held for filled zones only (N1). 4, 5 and 6 hold as scoped, with more cases in N4 and N5. 7 held for a join inside a segment but introduced N3.

**Found sound:** footprint-zone nets in `--router.plane_nets` leave routing unchanged (Freerouting skips a plane net only for items joined to a conduction area, which KiCad's DSN does not write for them); gate pairing survived footprints moved, swapped and turned in the same edit; the badge board and its zoned version compare identical against pcbnew re-saves and a refill; the output contract held for 34 runs including missing, empty, unparseable and directory inputs; other prewire stubs lost only their free-end piece.

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| N1 | SHOULD-FIX | The gate swapped fills between uuid-less zones on one net, layers and outline when they were never filled: the candidate's `fill` differs from the filled copy's `fill yes`, so the canonical match failed and file order decided. | Fixed at the root. The copy pcbnew fills gives every zone a marker uuid of its own (`mark_zones`, `src/gate.rs`), pcbnew keeps it, and fills come back by marker; the matching tiers are gone. Unit test `fills_carried_back_by_marker_and_nothing_else`; `tests/review11/gate11.py` (never-filled, hand-written, copied footprints): three runs, one file, every fill pcbnew's. |
| N2 | SHOULD-FIX | Diff reported zones changed when only their fill state changed (the badge's zoned board unfilled: 38 added, 38 removed). | Fixed. The canonical text leaves out the `fill yes` flag along with the fills. |
| N3 | SHOULD-FIX | Regression from review 10's 7: a prewire stub anchored in a never-filled zone was pruned whole, with the router's wire, and the route rejected. | Fixed. Only the stub from the router's join out to the free end is marked prunable, and the pruning counts a never-filled zone by its outline, as edit's join check does. `tests/review11/prewire11.py`, all five cases done. |
| N4 | NOTE | Diff false positives after a KiCad re-save of hand-written text: zone `priority 0`, `name ""`, `filled_areas_thickness no`, hatched fill defaults, a rule area's `net ""`; `gr_text`, `gr_poly (fill solid)`, `gr_line (width)`, `gr_circle` child order; pad numbers as text. | Fixed. Those zone defaults are dropped or written out; copper graphics compare by geometry, width (`width` or `stroke`), fill and net; pad settings compare as numbers. `diff11.py`, 15 re-save cases identical. |
| N5 | NOTE | Diff missed a footprint's own `zone_connect` and `clearance`, a dimension or target on F.Cu, and a footprint property moved to F.Cu. | Fixed. Footprint rules count as a pad change; dimensions and targets on copper are copper graphics; footprint properties and dimensions on copper count as footprint copper graphics. `diff11.py`, 7 cases seen. |
| N6 | NOTE | KiCad 10 reads a zone's polygons after the first as holes; pcb counted them as copper. | Fixed. `Zone::holes` replaces `outlines`; a never-filled zone joins inside its outline and outside its holes. Unit test `zone_hole_is_not_copper`. |
| N7 | NOTE | A stub joined at its bend was not pruned. | Fixed. An inner corner the router's copper ends on stops the walk the same way a split does. Probe `join_at_bend`. |
| N8 | NOTE | A directory given as the board, `--ops` or `--prewire` failed as `io`. | Fixed. Anything but a file is refused (`usage`). |
| N9 | NOTE | Commit 130b12f added scratch files `tools/pcb/x.kicad_*`, written by `tests/review10/lib.py`. | Fixed. The files are removed and the helper builds its boards in a temporary folder. |
