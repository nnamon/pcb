# Review 14: confirmation of review 13

Independent confirmation reviewer, 4 Nov 2026, at commit 9c9508b. Saved by the designer from the reviewer's hand-back; closures added after. The reviewer's scripts joined the suite in `tests/review14/`.

15 of the 17 closures held. Findings 3 and 4 held for the inputs the closure tested, but each failed on a variation: custom pads (3), and keep-outs drawn on the board or inside a footprint (4). There were 7 new NOTEs and no new BLOCKER or SHOULD-FIX.

| # | Closure | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Gate markers sort as zone uuids; fixture priorities; `fill-overlap`; refilled control | CONFIRMED | Every zone's fill matches a KiCad refill on same-priority fills sorting with and against file order, hand-made zones with upper- and lower-case uuids, and footprint zones (152.78 against 104.70 mm², so the order is really tested). On the badge no fill changes on a refill, and verify_zones passes on the refilled board. H fires only on the mutations aimed at it. Probes fill14, badge14 `badge_refill`. |
| 2 | Check J, fixture facts, three mutations | CONFIRMED | J passes with 13 of 203 vias removed and fails with 14 (floor 190); it fails for one via overlapping by 0.05 mm a GND SMD pad, a GND THT pad, another net's pad, a keep-out's grown edge, and for a via at a keep-out's centre. Probes badge14 `badge_oracle_j`, `badge_oracle_d`. |
| 3 | Grid point outside each pad's turned outline plus margin | REJECTED | Held for turned rects, circles, ovals, roundrects, bottom-side and THT pads (smallest gap 0.435 mm against 0.3). Failed for a custom pad (0.4 mm anchor, 4 × 4 mm primitive): `pad_rect` read only the anchor. Probes stitch14 `pad_shapes`, `pad_custom`. |
| 4 | Points in a via keep-out skipped | REJECTED | Held for pcb.toml keep-outs. Failed for rule areas forbidding vias drawn on the board or inside a footprint: 196 vias inside, run rejected. Probes stitch14 `keepout_board_rule_area`, `keepout_footprint_rule_area`. |
| 5 | Non-finite values and big grids refused | CONFIRMED | stitch14 `pitch_tiny`, `rect_inf`, `rect_neg_inf`, `pitch_nan`, `rect_huge`, `grid_near_limit`. |
| 6 | Pour keep-outs per layer | CONFIRMED | fill14 `ko_inner_only`, `ko_front_only`, `ko_all`. |
| 7 | `pcb:pad_override` record | CONFIRMED | Changed overrides, two footprints, a pcbnew re-save, the same override twice, `pcb edit move_footprint` and `pcb diff` against a re-save. Probes override14. |
| 8 | Duplicate names and layers refused | CONFIRMED | config14 `dup_*`, `ok_*`. |
| 9 | Later stitch entries skip earlier vias; pitch floor | CONFIRMED | stitch14 `two_sizes`, `pitch_below`, `pitch_eq_0p9`, `pitch_eq_1p1`. |
| 10 | Run ends meet pads on their own layer | CONFIRMED | tie14 `tht_tie`, `bottom_under_top_pad`, `tht_other_net`. |
| 11 | `absorb_vias_net` checked | CONFIRMED | Variation: R14-3. |
| 12 | Non-finite numbers refused | CONFIRMED | 14 fields; config14 `inf_*`, `nan_*`. |
| 13 | `stitch-no-fill` warning | CONFIRMED | stitch14 `nofill_one`, `nofill_none_missing`. |
| 14 | Absorption refusals | CONFIRMED | tie14 `absorbed_pad_on_tie`, `retype_other_parts`; badge14 `badge_run`. |
| 15 | Empty `forbid` refused | CONFIRMED | config14 `forbid_empty`, `ok_forbid_one`. |
| 16 | Allowance semantics documented | CONFIRMED | Read against gate.rs. Wording: verify_zones compares the zoned board's count with `max`, an absolute count. |
| 17 | Oracle regex `\(fill yes(?=\s)` | CONFIRMED | fill14 `oracle_regex`. |

| # | Severity | Finding | Closure |
| --- | --- | --- | --- |
| 3 | SHOULD-FIX | Custom pads: stitching read only the anchor size (above). | Fixed. The board model keeps each custom pad's primitives' extent (`Pad::prims`, from polygons, lines, rectangles, circles and arcs with their widths); `pad_rect`, used by stitching and by fill outlines, covers it. Probe `pad_custom` passes. |
| 4 | SHOULD-FIX | Board and footprint rule areas that forbid vias were not kept out of stitching (above). | Fixed. `Zone::forbids_vias` is read from the zone's keep-out settings, and stitching skips every such zone's outline, holes left open, with pcb.toml's. Probes `keepout_board_rule_area`, `keepout_footprint_rule_area` pass. |
| R14-1 | NOTE | `fill-overlap` compared only fills: a fill against a `[[zone]]` pour or a hand-made zone at its priority, and two `[[zone]]` pours of different nets on one layer, were not warned. Probes fill14 `ov_plane`, `ov_hand_zone`, `ov_two_planes`. | Fixed. The comparison includes each `[[zone]]` pour (the board less that layer's pour keep-outs) and the board's own copper zones at their priority (`Zone::priority`). The warning says to give one its own priority. |
| R14-2 | NOTE | The override record held one value per pad number, so two pads numbered "2" were both put back to the first's setting. Probe override14 `repeat_dropped`. | Fixed. Pads sharing a number are recorded as `NUM#K`, the K-th in file order; the probe's pads now come back to none and inherited. (The run is then rejected, rightly: the pad left on none is unconnected, as in the design before the override.) |
| R14-3 | NOTE | `absorb_vias_net` equal to `absorb_net` ran to done, leaving the net and a three-net tie group. Probe tie14 `vias_net_is_absorbed`. | Fixed. Refused (`config`). |
| R14-4 | NOTE | The pitch floor was a plain float compare: 0.85 with 0.55 + 0.3 was refused. Probes stitch14 `pitch_eq_0p85`, `pitch_eq_1p2`. | Fixed. Compared with a 1e-9 tolerance; both run. |
| R14-5 | NOTE | `marks` sorted uuids by text, KiCad by value: a legacy 8-digit id sorted wrongly. A zone with no uuid gets a random one at every KiCad load. Probes fill14 `hand_legacy`, `hand_no_uuid`. | Fixed for legacy ids: ids are compared as 32 hex digits, a short one right-aligned. A zone with no uuid cannot be fixed by sorting; only hand-written files carry one, and `pcb zone` gives its own zones ids. |
| R14-6 | NOTE | Check D reads the saved fill, so a solid override with an old relief fill left in a hand-edited file passes verify_zones. Probe badge14 `badge_oracle_d`. | Not changed. pcb's own outputs are always refilled by the gate; the oracle judges pcb's outputs. |
| R14-7 | NOTE | fixture.toml's stitch comment said 202 vias; the run gives 203. | Fixed. |

Suite at 9c9508b: 47 of 47 steps passed in 1659 s. The reviewer's `check.py` exited 1 (74 passed, 3 failed: findings 3 and 4).

Rerun: `cd tools/pcb && cargo build --release && python3 tests/review14/check.py target/release/pcb /tmp/r14` (6 to 35 minutes); one probe: `python3 tests/review14/check.py target/release/pcb /tmp/r14 stitch14.py`.
