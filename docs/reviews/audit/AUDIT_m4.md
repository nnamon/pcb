# Audit of the M4 probes (r18, r19, r20)

Every verdict in `r18/check.py`, `r19/check.py` and `r20/check.py` (a `want` or a `note`), labelled:

- **covered:** an existing case, fixture step, oracle check or unit test asserts the same outcome on an equivalent input;
- **port:** added to `tests/cases/m4_cases.py` (builders in `tests/lib/m4_synth.py`), each with `# source: review NN, <case>`, asserting the reviewer's outcome;
- **evidence:** it tested the reviewer's premise (EasyEDA's data, the fixture, the probe itself) or was a note that never fails the run.

A row naming several cases holds one verdict per case. "Ported as" quotes the start of the `want(...)` name in `m4_cases.py`. Cases marked (P) read the finished M4 project from `PCB_M4_PROJECT` and are skipped without it.

| Folder | Case name | What it checks | Label | Covered by / ported as |
| --- | --- | --- | --- | --- |
| r18 | c5446_fields | C5446's shown pin numbers match the datasheet, spice numbers do not | evidence | EasyEDA's data; parsing by shown number is `src/easyeda.rs` test `symbol_pins` (l. 381) |
| r18 | spice_numbered_sync | XC6206 numbered by the spice field refused `pin-name` | covered | `m4_cases.py` l. 141 "sync: XC6206 with VIN and VOUT on each other's pads refused" |
| r18 | datasheet_numbered_sync | note: datasheet-numbered schematic syncs | evidence | note |
| r18 | swap_D+_D-, swap_IN+_IN-, swap_Q_~Q, swap_VREF+_VREF-, swap_CS_CS# | a swap of names differing by a sign or active-low mark refused | covered | `src/sync.rs` test `pin_names` l. 607 (each pair not the same pin); refusal path `m4_cases.py` l. 141 |
| r18 | swap_SDA_SCL, swap_CC1_CC2 | control: swap refused | port | "sync: a swap of SDA and SCL refused", "... CC1 and CC2 ..." |
| r18 | swap_A_K | control: swap refused | covered | `src/sync.rs` l. 613 `!same_pin("1", "A", "K")` |
| r18 | fixture_parts | the fixture's 48 parts match EasyEDA's pad outlines, holes, slots | port | "sync: the fixture's 48 parts match EasyEDA's pad outlines" (verify_sync D checks pad centres only) |
| r18 | synthetic_rect_30, _rect_90_tht, _polygon_hole, _oval_slot_long, _oval_slot_turned, _bottom_smd | control: synthetic pad converts to EasyEDA's geometry | port | "sync: synthetic <k> matches EasyEDA's geometry" |
| r18 | synthetic_round_slot_x | finding 3: slot across a round pad follows the hole points | covered | `src/easyeda.rs` test `plated_slot_runs_along_the_pad` l. 370 |
| r18 | synthetic_rect_slot_across | finding 3: slot across a rectangular pad follows the hole points | port | "sync: a slot across a rectangular pad runs where EasyEDA's hole points put it" |
| r18 | synthetic_oval_45, synthetic_unplated_pad | notes | evidence | notes |
| r18 | lcsc_change | finding 4: new LCSC code and value reach the board on re-sync | covered | `m4_cases.py` l. 160 "sync: a part changed in the same package is replaced" |
| r18 | control (parts18) | parts done on the flow's board, LED1 offset 0 | covered | fixture flow step `parts` (`fixtures/paddle_keyer_m4/fixture.toml` l. 15; `xtask` fails the step unless done) |
| r18 | two_pad_180 | finding 5: LED1/D1 declared 180 off rejected | port | "parts: LED1 and D1 declared 180 off: rejected" (merged with r19 m4_led_d_180) |
| r18 | two_pad_offset_009, crystal_180 | notes | evidence | notes |
| r18 | qfn_90, qfn_180, uson8_180, sot23_180_renumbered | control: by-shape match solves the true turn | port | "parts: by-shape <k> solves its true turn" |
| r18 | bottom_vs_kicad_flip | control: bottom pads, angles, layers, drills equal KiCad's flip | port | "place: bottom-side pads, angles, layers and drills equal KiCad's own flip" |
| r18 | bottom text mirrored | note | evidence | note |
| r18 | golden_copper (holes) | control: every v1.0.0 component hole matched | covered | `oracles/verify_against_v1.py` check A (l. 108), run by the flow (`xtask/src/main.rs` l. 632); tolerance 0.05 mm against the probe's 0.02 mm |
| r18 | golden_copper (n_empty) | control: every M4 paste opening holds a v1.0.0 one | covered | `verify_against_v1.py` check B (l. 115), release to v1.0.0 direction |
| r18 | golden_copper (pin-in-paste) | finding 6: v1.0.0's J1 shell-leg paste is in the release | covered | `verify_against_v1.py` check B, v1.0.0 to release direction |
| r18 | economic_after_gate | control: release re-checks the parts cache | port (P) | "release: a part Standard-only in the cache after the gate stops the release" |
| r18 | two_pad_180_release | finding 5: LED1/D1 not released turned | port (P) | "release: LED1 and D1 declared 180 off are not released" |
| r18 | live | note (network) | evidence | note |
| r19 | control (stale19) | finished project checks done, nothing stale | covered | fixture flow step `check` (`fixture.toml` l. 16; stale findings make it rejected) |
| r19 | kicad_save, kicad_save_rerun_save, kicad_refill_save, kicad_move_back, netlist_exported_unchanged, board_turned_360 | 39/41: harmless edits leave nothing stale | port (P) | "check: harmless <k>: done, nothing stale" |
| r19 | pip_dropped, aperture_moved, art_point, art_layer, art_moved, sync_value, sync_lcsc, sync_pin_dropped, place_shift_005, place_rot_180, board_moved_001 | 39/41: each edit makes its command stale | port (P) | "check: <k>: stale <cmd>" |
| r19 | record_copied | note 44: pasted art record is stale, no release | port (P) | "check: a record pasted from another run" |
| r19 | aperture_round, aperture_turned, pip_margin, footprint_changed_on_board | notes | evidence | notes (the first two closed by review 20's stale20, ported) |
| r19 | pour_0_1, pour_0_3, inner_hole_0_2 | 40: check's DRC on kept fills | port | "check: a 2-layer pour at the board's 0.1 mm", "check: the pour at 0.3 mm", "check: inner copper 0.2 mm" |
| r19 | custom_rule_0_5, netclass_0_5 | 40: released fill keeps the board's 0.5 mm | port | "release: the released fill keeps the board's own 0.5 mm ..." |
| r19 | fixture_has_no_c5446_override | the fixture holds no pin map | evidence | tests the fixture and pins18's edit |
| r19 | datasheet_numbered | XC6206 syncs with no override | covered | `m4_cases.py` l. 126 "sync: a new board with every part" |
| r19 | spice_numbered | refused `pin-name` | covered | `m4_cases.py` l. 141 |
| r19 | partial_map | a one-pin map does not hide the swap | port | "sync: the spice-numbered XC6206 with a partial pin map refused" |
| r19 | shown_vs_spice_spice_order | schematic following spice numbers refused | port | "sync: a schematic following the spice numbers refused" |
| r19 | shown_vs_spice_shown_order, blank_shown_falls_back | sync done | port | "sync: a schematic following the symbol's shown numbers syncs", "sync: a blank shown number falls back" |
| r19 | swap D+ D- as D- D+, swap IN+ IN- as IN- IN+, swap VREF+ VREF- as VREF- VREF+ | 2: refused | covered | `src/sync.rs` l. 607 |
| r19 | swap Q Q#, CS CS#, WR# WR, V+ V-, +IN -IN, RESET RESET#, OE OE#, D+ D- as D− D+, TX+ TX-, R/W# R#/W | 2: refused `pin-name` | port | "sync: swap <a> <b> as <c> <d> refused pin-name" |
| r19 | swap GND VSS as VSS GND, swap OUT OUT1 as OUT1 OUT | notes | evidence | notes |
| r19 | same CS# as ~{CS} | 2: syncs | covered | `src/sync.rs` l. 610 |
| r19 | same CS# as /CS, same DVDD1 as DVDD | 2: syncs | port | "sync: CS# wired as /CS syncs", "sync: DVDD1 wired as DVDD syncs" |
| r19 | same (9 other spellings) | notes | evidence | notes |
| r19 | slot_rot0_along, slot_rot0_across, slot_rot90_along, slot_rot0_big | 3: drill between the hole points | port | "sync: <k>: the drill runs between the hole points" |
| r19 | j1_slots | 3: J1's four shell slots | port | "sync: J1's four shell slots run between EasyEDA's hole points" |
| r19 | slot_diagonal | 3: slot across the pad's axes refused | port | "sync: a slot across the pad's axes refused" |
| r19 | slot_offset_along, slot_offset_rot90 | 47: off-centre slot drilled at its hole points | port | "sync: offset_along: ...", "sync: offset_rot90: ..." |
| r19 | slot_offset_along_checked | 47: off-centre slot in place or stopped by check | port | "check: the off-centre slot is in place or check stops it" |
| r19 | slot_rot45/30/135_along, slot_rot30_across, slot_rot30_big, slot_rot30_big_checked, slot_rot30_round_checked | notes | evidence | notes |
| r19 | m4_led_d_180 | 5: rotation finding each, no release | port | parts half: "parts: LED1 and D1 declared 180 off"; release half (P): "release: LED1 and D1 declared 180 off are not released" |
| r19 | by_shape_offset_0, by_shape_offset_180 | 5/48: D9 on an A/K footprint | port | merged with r20 d9_by_shape_*: "parts: D9 matched by shape on an A/K footprint at offset <n>" |
| r19 | m4_resistor_180 | note | evidence | note |
| r19 | economic_unknown | 18 note 5: warns `economic-unknown` | port | "parts: a record with no componentProductType warns economic-unknown" |
| r19 | lcsc_and_value, value_only, odd_values, bottom_part, paste_part | 4: re-sync replaces in place | port | "sync: R1 5.1k C25905 to 10k C25744 replaced in place", "sync: the value alone replaced", "sync: values with quotes and non-ASCII kept", "sync: a bottom-side part replaced stays", "sync: U1 replaced loses its paste windows" |
| r19 | routed_rip | note | evidence | note |
| r19 | dnp_and_not_in_bom | 49: C2 and C3 not ordered | port (P) | merged with r20 flags_set: "release: C2 and C3 left out of the BOM and CPL" (input adds C6 excluded from simulation) |
| r19 | control (oracle19) | verify_against_v1 passes the release | covered | flow step "holes, paste and mask against v1.0.0's Gerbers" (`xtask/src/main.rs` l. 632) |
| r19 | pip_removed, slot_moved_0_1, ep_full_paste | 6: verify_against_v1 fails the mutation | port (P) | "verify_against_v1: fails <k>" |
| r19 | pip_shrunk, slot_turned | notes | evidence | notes |
| r20 | slot_<k> drill and copper, for k in project_fp_kicad_offset, off_along_r0, off_along_r90, off_along_r180, off_along_r270, off_across_r0, off_r90_board90, off_r0_board30, off_r270_board180, off_slot_across_pad, off_r0_bottom, thin_ring, broken_ring, centred_r0 | 47: drill and copper where EasyEDA puts them | port | "sync: <k>: drill and copper where EasyEDA puts them" (14) |
| r20 | slot_<k> offset solver, same 14 | 47: turn 0, offset 0, residual 0 | port | "parts: <k>: the offset solver finds turn 0" (14) |
| r20 | slot_thin_ring, slot_broken_ring (check) | 47: check stops a thinned ring | port | "check: <k>: a slot whose offset thins the ring is stopped" |
| r20 | slot_rect_rot30, slot_polygon_rot0 | 51: refused `footprint` | port | "sync: <k>: a slot in a custom pad refused" |
| r20 | slot_round_rot30 | note | evidence | note |
| r20 | m4_no_polarity | 48: no polarity finding on the M4 board | covered | fixture flow step `parts` (`fixture.toml` l. 15): done means no finding |
| r20 | d9_by_shape_0, d9_by_shape_180 | 48: polarity finding, no release | port | "parts: D9 matched by shape on an A/K footprint at offset <n>" |
| r20 | r9_by_shape | note | evidence | note |
| r20 | soic_ep_turned180, qfn_ep_turned90 | 58: not released at the wrong turn | port | "parts: <k>: a pattern that repeats under a turn is not released at the wrong turn" |
| r20 | soic_ep_turned90_declared0 | 58 control: rotation finding | port | "parts: an SOIC turned 90 and declared 0 is a rotation finding" |
| r20 | soic_ep_not_turned | 58 control: releases or `turn` finding alone | port | "parts: the SOIC not turned releases, or is a turn finding alone" |
| r20 | flags_set (board), flags_set (release) | 49: flags reach the board; BOM and CPL leave C2, C3 out | port (P) | "sync: DNP and not-in-BOM flags reach the board", "release: C2 and C3 left out of the BOM and CPL" |
| r20 | flags_cleared | 59: cleared flag cleared, or check stops it | port (P) | "sync: a flag cleared in the schematic is cleared on the board" |
| r20 | hand_exclude_from_bom, hand_exclude_from_pos | 59: a hand exclusion is stopped | port (P) | "check: <k>: a fitted part dropped by hand in pcbnew is stopped" |
| r20 | dnp_field_no | 60: user field DNP = No is not DNP | port (P) | "sync: a user field DNP = No does not make the part DNP" |
| r20 | schematic_changed_after_gate | 61: release stopped | port (P) | "release: a schematic changed after the gate stops the release" |
| r20 | not_on_board | note | evidence | note |
| r20 | value_only, lcsc_same_package | 55: replaced without --rip, copper kept, check and release done | port (P) | "sync: <k>: replaced without --rip, copper kept" |
| r20 | lcsc_same_title_other_pads | note | evidence | note |
| r20 | lcsc_other_title_other_pads | 55 control: `sync-copper` | port (P) | "sync: another package title on a routed part needs --rip" |
| r20 | harmless_load_save, _j1_90_back, _u1_45_back, _u1_180_twice, _j1_360, _r1_flip_back, _all_90_back, _all_30x12 | 50: nothing stale | port (P) | "check: harmless <k>: done, nothing stale" |
| r20 | edited_window_round, _window_turned45, _window_roundrect, _window_turned90 | 50: 4 windows, stale paste | port (P) | "check: window_<k>: stale paste" |

## Counts

Counted per verdict (a row with several cases counts each).

| Folder | Verdicts | covered | port | evidence |
| --- | --- | --- | --- | --- |
| r18 | 39 | 13 | 18 | 8 |
| r19 | 96 | 8 | 61 | 27 |
| r20 | 65 | 1 | 60 | 4 |
| Total | 200 | 22 | 139 | 39 |

Of the 139 ports, 46 need the finished M4 project (P) and are skipped, and listed, unless `PCB_M4_PROJECT` is set. The suite does not set it yet: `xtask` runs `cases/steps.toml` before the fixtures, so `{flow:paddle_keyer_m4}` is empty when `m4_cases` runs. Wiring it needs a step that runs `m4_cases.py` after the fixtures with `env = { PCB_M4_PROJECT = "{flow:paddle_keyer_m4}" }`, which is outside this audit's files.
