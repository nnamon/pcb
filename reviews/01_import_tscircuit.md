# Review 1: `pcb import-tscircuit` and `tests/verify_import.py`

Independent reviewer, 30 Oct 2026, at commit db6939b. Saved by the designer from the reviewer's hand-back. The closure column is the designer's; each closure is tested in `tests/verify_import.py` or the unit tests.

**Verdict:** copper (positions, pad sizes, oval slots, nets) on r36a is correct. Two blockers made the imported board wrong as a KiCad model. Several paths silently drop data that r36a happens not to contain, and the check could not see any of these problems.

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| B1 | BLOCKER | Courtyard rects ignore `ccw_rotation`, so every 90/270° part's courtyard is turned 90°. KiCad DRC reports 26 overlaps against tscircuit's 7. Other `pcb_courtyard_*` types are skipped. | |
| B2 | BLOCKER | Bottom footprints get orientation = tscircuit rotation, but KiCad's flipped-footprint convention is rotation + 180. Copper is correct; CPL rotation and a footprint update would turn BT101 180° and swap its + and −. | |
| S1 | SHOULD-FIX | No footprint type attribute (`smd`/`through_hole`): `kicad-cli pcb export pos --smd-only` gives 0 rows. DNP BT101 is written as `smd`. | |
| S2 | SHOULD-FIX | Pad nets come only from source_traces pairing a port with a net. A port-to-port trace gives no net, and a port on two nets silently keeps the first. | |
| S3 | SHOULD-FIX | Track and via nets depend on the non-standard `net_name` field. Without it they land on net 0 silently. | |
| S4 | SHOULD-FIX | Route gaps are dropped silently: a layer change between wire points, or a `via` route point. | |
| S5 | SHOULD-FIX | A polygon pad anchored at its bounding-box centre can sit outside a non-convex polygon (stray copper dot, wrong attach point). | |
| S6 | SHOULD-FIX | Unknown elements (`pcb_cutout`, others), `hole_offset_*`, corner radii and pill radius are dropped silently. | |
| S7 | SHOULD-FIX | A pad can get an empty number. | |
| S8 | SHOULD-FIX | The test misses pad layer side, number, pinfunction, outline, courtyards, attributes, LCSC/DNP, via span, slot axis and polygon shape. A mutated board with all of these changed passed. | |
| N1 | NOTE | No design rules imported; KiCad defaults to 0.2 mm clearance. | |
| N2 | NOTE | `--layers 4` against `num_layers 2` is not reported; non-through vias are written as through. | |
| N3 | NOTE | tscircuit paste and mask settings dropped (intended for paste). | |
| N4 | NOTE | The transform assumes the board centre is (0, 0). | |
| N5 | NOTE | An outline that repeats its first point writes a zero-length Edge.Cuts line. | |
| N6 | NOTE | Library ids containing ':' are rewritten by KiCad. | |
| N7 | NOTE | `value_of` writes 0 Ω as "0pΩ". | |
| N8 | NOTE | The unit test `local_undoes_rotation` only tests a round trip, not KiCad's angle convention. | |
| N9 | NOTE | `board.rs` reads a `gr_poly` outline without its closing segment; `gr_arc` becomes two chords; `gr_circle` is ignored. | |
| N10 | NOTE | The board-hole naming check is specific to this board's source. | |

The reviewer checked:
- The badge board, built and run.
- pcbnew DRC on the converted board.
- An independent comparison with tscircuit's exported drill file and mask: every slot's position and orientation matched.
- Synthetic circuit JSON covering:
  - parts at 90/270° on both sides;
  - pill holes;
  - L-shaped polygon pads;
  - escaped names;
  - port-to-port traces;
  - layer changes without a via;
  - blind vias;
  - cutouts;
  - orphan pads.
- KiCad's flip convention, in pcbnew.

The reviewer's scratch files are in the session scratchpad, `review_import/`.
