# Audit of the M3 review probes (r15, r16, r17)

Each verdict in `r15/check.py`, `r16/check.py` and `r17/check.py` (each `want` and each `note`), with one label:

- **covered**: an existing case or fixture step asserts the same outcome on an equivalent input.
- **port**: moved into a case file, with the reviewer's input and expected outcome (`# source: review NN, <case>`).
- **evidence**: tested the reviewer's premise, not pcb, or was a NOTE that never failed the run.

Some verdicts are covered by a case ported from a later review that re-checks the same closure; the table names that case. "rc" is `tests/cases/release_cases.py`, "ic" is `tests/cases/import_cases.py`, and "main.rs" is `xtask/src/main.rs`. Line numbers are as of 5 Nov 2026.

| folder | case name | what it checks (short) | label | covered by / ported as |
| --- | --- | --- | --- | --- |
| r15 | golden control | paddle release against the ordered Gerbers: done, nothing unexplained | covered | paddle_keyer_v1 [release]: "compare-gerbers with the ordered files" must exit 0 (done), main.rs:584 |
| r15 | golden track_gone_f | F.Cu track removed: compare rejected | port | rc:339 "r15 golden track_gone_f" |
| r15 | golden track_gone_b | B.Cu track removed: rejected | port | rc:339 "r15 golden track_gone_b" |
| r15 | golden narrow_b | B.Cu V3V3 narrowed: rejected | port | rc:339 "r15 golden narrow_b" |
| r15 | golden pad_moved | R11 moved 0.2 mm: rejected | port | rc:339 "r15 golden pad_moved" |
| r15 | golden via_gone | a TIP via removed: rejected | port | rc:339 "r15 golden via_gone" |
| r15 | golden island_no_net | no-net copper island: rejected | port | rc:339 "r15 golden island_no_net" |
| r15 | golden silk_outline_gone | U1 silk outline removed: rejected | port | rc:339 "r15 golden silk_outline_gone" |
| r15 | golden npth_instead | J1 PTH made NPTH: rejected | port | rc:339 "r15 golden npth_instead" |
| r15 | golden label_shift_03 | version label 0.3 mm off: rejected | port | rc:339 "r15 golden label_shift_03" |
| r15 | golden label_text | label text changed: rejected | port | rc:339 "r15 golden label_text" |
| r15 | golden label_cap | label cap height 0.9 mm: rejected | port | rc:339 "r15 golden label_cap" |
| r15 | golden narrow_f | F.Cu power tracks to 0.15 mm: rejected (#3) | port | rc:339 "r15 golden narrow_f" |
| r15 | golden layer_gone_fpaste | F.Paste file deleted: rejected (#1) | port | rc:348 "r15 golden layer_gone_fpaste" |
| r15 | golden layer_gone_bsilk | B.Silk deleted: rejected (#1) | port | rc:348 "r15 golden layer_gone_bsilk" |
| r15 | golden layer_gone_fmask | F.Mask deleted: rejected (#1) | port | rc:348 "r15 golden layer_gone_fmask" |
| r15 | golden control B.Paste | B.Paste not reported missing (#2) | port | rc:270 "r16 golden control" (missing == [], no B.Paste) |
| r15 | golden origin | U1 in the CPL where the Gerbers put it (#4) | port | rc:281 |
| r15 | golden label_shift_008 | NOTE: label 0.08 mm off | evidence | NOTE |
| r15 | compare zip_vs_folder | zip against folder: done, 7 layers | port | rc:360 |
| r15 | compare x2_names_only | layers named by X2 only: done, 7 layers | port | rc:367 |
| r15 | compare unknown_layers | no X2, unknown names: rejected or refused (#1) | port | rc:377 |
| r15 | compare slot_longer | slot 0.2 mm longer: rejected | port | rc:389 |
| r15 | compare drill_explain_norect | NOTE: drill explain without rect (#21) | evidence | NOTE |
| r15 | release p1 | release with no gate: gate-missing, no folder | covered | rc:189 "flow" (release with no gate refused gate-missing, out absent) |
| r15 | release p2 | board changed after gate: stale, gate-stale | covered | rc:210, rc:212 "flow" (board changed: stale; release gate-stale) |
| r15 | release gate_pro_severity | .kicad_pro change makes gate stale (#6) | covered | rc:648 "r16 gate_inputs" (ported) |
| r15 | release gate_dru_beside | new .kicad_dru makes gate stale (#6) | covered | rc:648 "r16 gate_inputs" (ported) |
| r15 | check pro_hides | track_width ignored in .kicad_pro: still rejected (#5) | covered | rc:531 "r16 check_pro_ignore" (ported; every fab kind ignored) |
| r15 | gate spaces | NOTE: `[ gates.layout ]` header (#19) | evidence | NOTE |
| r15 | gate comment | NOTE: comment after gate table kept (#19) | evidence | NOTE |
| r15 | release cpl_offsets | CPL offsets on turned and bottom parts vs pcbnew | port | rc:808 |
| r15 | release bottom rotation | NOTE: bottom CPL rotation convention (#18) | evidence | NOTE |
| r15 | release rename_collision | rename onto an existing reference refused (#9) | covered | rc:147 "rename_collision" |
| r15 | release dnp_handfit | DNP, excluded, hand-fit parts out of BOM and CPL | port | rc:820 |
| r15 | release repro | two releases: same CSVs, zip differs by dates, checksums | covered | rc:849 "r17 reproducible" (ported; also checks CHECKSUMS) |
| r15 | release rb_thin_track | 0.10 mm track, DRC waived: read-back rejects (#7) | covered | rc:902 "r16 rb_widths" (ported) |
| r15 | release rb_thin_silk | 0.12 / 0.10 mm silk lines found (#8) | covered | badge_r36a [check] findings "silk lines 0.1 mm", "silk lines 0.12 mm" (fixture.toml:144), asserted main.rs:539; read-back side rc:907 "r16 rb_silk_lines" |
| r15 | release rb_cutout | copper at a round cut-out: cu_edge (#16) | covered | rc:915 "r16 rb_cutout" (ported) |
| r15 | release rb_off_board | NOTE: copper off the board (#20) | evidence | NOTE |
| r15 | release rb_short | short only in the copper: rejected, GND / VBUS | covered | rc:923 "r16 rb_short" (ported) |
| r15 | release rb_short folder | NOTE: rejected release folder (#17) | evidence | NOTE |
| r15 | check fab2 | each 2-layer fab rule fires on its own | port | rc:470 (lib/fab_board.py rules_board) |
| r15 | check fab4 (P35) | 4-layer inner copper to hole rules, control not hit | port | rc:473 |
| r15 | check fab4_as_2 | 4-layer board under 2-layer set: config (#10) | port | rc:475 |
| r15 | check p10 | XOUT at 2 A: width-current names net and width | covered | rc:103 "width_current" (P at 3 A: width-current "P F.Cu", 0.3 mm) |
| r15 | check arc_width | width-current sees a thin arc (#12) | covered | rc:517 "r16 check_arc" (ported) |
| r15 | check paste_beside_window | U1.5 and R11.1 paste found beside a windowed pad (#11) | port | rc:500 |
| r15 | check waiver over max | waiver max 27 under count: unwaived | port | rc:524 |
| r15 | check dfm waiver | NOTE: dfm waiver warned unused (#22) | evidence | NOTE |
| r15 | paste again | second pcb paste: same bytes | port | rc:1055 |
| r15 | paste contract | paste output contract (#13) | covered | rc:183 "flow" (paste through the contract checker) |
| r15 | paste dropped | rules dropped: U1, J1 as imported | port | rc:1062 |
| r15 | paste windows_turned | windows inside a pad turned 30° | port | rc:1086 |
| r15 | art | holes, counters, mirror, centre, turned letter in Gerbers | port | rc:1125 |
| r15 | art contract | art output contract (#13) | covered | rc:185 "flow" (art through the contract checker) |
| r15 | art dropped | entry dropped: its groups removed | port | rc:1132 |
| r15 | import rename_into_other_pad | foreign net ending inside another pad: refused (#14) | covered | ic:209, ic:361 "m3_foreign_net_into_other_pad" (same circuit) |
| r15 | import badge_silk | badge silk on turned and bottom parts placed | covered | badge_r36a verify_import (silk section, verify_import.py:553), main.rs:383 |
| r15 | import bottom_silk | bottom part turned 90° with bottom silk | port | ic "m3_silk_bottom_turned" (verify_import places it) |
| r15 | badge check | badge check finds PMUX_ILM, VBUS_F opens, 4-layer fab | covered | badge_r36a [check] findings (exact list), main.rs:539 |
| r15 | badge release read-back | badge read-back: opens, no shorts, no hole_hole (#15) | covered | rc:1179 "r16 badge_release" (ported) |
| r15 | badge check record | NOTE: DESIGN.md record vs silk findings (#23) | evidence | NOTE |
| r16 | 2 control | golden compare done, no missing, no B.Paste, 65 holes | port | rc:270 "r16 golden control" |
| r16 | 1 layer_gone_fpaste | F.Paste deleted: rejected | covered | rc:348 "r15 golden layer_gone_fpaste" (ported) |
| r16 | 1 layer_gone_bsilk | B.Silk deleted: rejected | covered | rc:348 "r15 golden layer_gone_bsilk" (ported) |
| r16 | 1 layer_gone_bmask | B.Mask deleted: rejected | port | rc:348 "r15 golden layer_gone_bmask" |
| r16 | 1 layer_anon | unnamed layers: rejected or refused | covered | rc:377 "r15 compare unknown_layers" (ported; same stripping) |
| r16 | 3 narrow_f | narrowed F.Cu released: rejected | covered | rc:339 "r15 golden narrow_f" (ported) |
| r16 | 4 origin_cpl_on_pads | each top R/C midway between its paste pads | port | rc:298 |
| r16 | 4 frame | page-frame set rejected; --align done | port | rc:398 |
| r16 | 5 check_pro_ignore | every fab kind ignored in .kicad_pro: rejected | port | rc:531 |
| r16 | 6 gate_inputs | stale on .kicad_pro change and new .kicad_dru; gate-stale | port | rc:648 |
| r16 | 9 release_rename | rename onto existing refused; swap allowed | port | rc:828 (swap); onto existing is rc:147 |
| r16 | 10 check_fab_layers | rule set for another layer count: config both ways | port | rc:484 |
| r16 | 11 check_paste_pad5 | U1.5 paste found beside pad 57's windows | covered | rc:500 "r15 check paste_beside_window" (ported) |
| r16 | 12 check_arc | width-current reads a 0.15 mm arc | port | rc:517 |
| r16 | 13 contracts | paste and art done, contract holds | covered | rc:183, rc:185 "flow" |
| r16 | 18 bottom parts warned | NOTE | evidence | NOTE |
| r16 | 19 comment lines kept | NOTE | evidence | NOTE |
| r16 | 22 dfm waiver | NOTE | evidence | NOTE |
| r16 | 26 ring and text height | NOTE | evidence | NOTE |
| r16 | 28 check_own_dru | board's VBUS 0.5 mm rule survives check | covered | rc:562 "r17 own_clearance_rule" (ported; stricter) |
| r16 | 28 check_own_netclass | 0.3 mm netclass: found or drc-truncated | covered | rc:569 "r17 netclass_default_truncated" (ported; same input) |
| r16 | 29 stale_version | version raised, art not run: not released silently | covered | rc:702 "r17 stale_version" (ported; stricter) |
| r16 | 29 stale_label | label moved, art not run | covered | rc:702 "r17 stale_label_moved" (ported) |
| r16 | 29 stale_paste | paste rule dropped, paste not run | covered | rc:702 "r17 stale_paste_dropped" (ported) |
| r16 | 30 stale_fill | NPTH in a stale fill: no copper over the hole | covered | rc:886 "r17 fill_stale" (ported; stricter) |
| r16 | pro_open check | NOTE | evidence | NOTE |
| r16 | pro_open read-back | NOTE | evidence | NOTE |
| r16 | gate hash multiline | NOTE (now rc:658 "r17 multiline_max") | evidence | NOTE |
| r16 | golden silk_grow | NOTE | evidence | NOTE |
| r16 | 7 rb_widths | read-back finds 0.10 and 0.14 mm tracks | port | rc:902 |
| r16 | read-back 0.149 mm | NOTE | evidence | NOTE |
| r16 | read-back necks | NOTE | evidence | NOTE |
| r16 | 8 rb_silk_lines | read-back finds a 0.12 mm silk line, check waived | port | rc:907 |
| r16 | read-back 0.14 mm silk | NOTE | evidence | NOTE |
| r16 | 8 rb_silk_poly | 0.10 mm neck in silk art: rejected | port | rc:911 |
| r16 | 16 rb_cutout | copper at a round cut-out: cu_edge | port | rc:915 |
| r16 | 20 rb_off_board | NOTE | evidence | NOTE |
| r16 | 17 rb_short | short found; release moves aside with CHECKSUMS | port | rc:923 |
| r16 | 17 second rejected | NOTE | evidence | NOTE |
| r16 | 31 compare_slot_turned | slot turned 90° in place: rejected | covered | rc:428 "r17 slot_turned_90" (ported) |
| r16 | 21 explain entries refused | NOTE | evidence | NOTE |
| r16 | second_top_copper | NOTE (now rc:458 "r17 unread_second_fcu") | evidence | NOTE |
| r16 | unlisted_layer | NOTE (now rc:458 "r17 unread_comment_layer") | evidence | NOTE |
| r16 | 14 rename_into_pad | foreign end 0.25 mm inside B's pad, off axis: refused | port | ic "m3_foreign_net_into_pad_corner" |
| r16 | 14 rename_other_side | end over a bottom pad: renamed, tracks all A | port | ic "m3_foreign_net_end_other_side" |
| r16 | internal_one_net | internal connection: R2.1 and R2.2 on N | port | ic "m3_internal_connection_numbered" |
| r16 | internal_two_nets | internal connection across two nets: refused | port | ic "m3_internal_connection_two_nets" |
| r16 | silk_kinds | silk path on a turned part placed | port | ic "m3_silk_turned_kinds" (verify_import) |
| r16 | silk line and rect | NOTE | evidence | NOTE |
| r16 | rename_through_pad | NOTE (now rc:632 "r17 rename_through_pad_checked") | evidence | NOTE |
| r16 | 23 badge_check | badge check finds exactly the fixture's list | covered | badge_r36a [check] findings, main.rs:539 (the same comparison) |
| r16 | 15 badge_release | slots as stadiums, known opens, no shorts | port | rc:1179 |
| r16 | 24 badge read-back time | NOTE | evidence | NOTE |
| r17 | control | base checks clean, 3 inputs records, releases | port | rc:687 |
| r17 | stale_version | found stale, gate refused | port | rc:702 |
| r17 | stale_label_moved | found stale, gate refused | port | rc:702 |
| r17 | stale_paste_dropped | found stale, gate refused | port | rc:702 |
| r17 | stale_zone_clearance | found stale, gate refused | port | rc:702 |
| r17 | stale_label_removed | found stale, gate refused | port | rc:702 |
| r17 | stale_waived | a waiver cannot cover stale | port | rc:709 |
| r17 | kicad_save | records survive a pcbnew save | port | rc:716 |
| r17 | record_moved | moved record still read | port | rc:722 |
| r17 | label_deleted | label deleted after art: not released (#39) | port | rc:734 |
| r17 | paste_undone | paste windows undone: not released (#39) | port | rc:747 |
| r17 | record_copied | NOTE (#44) | evidence | NOTE |
| r17 | place_not_applied | moved [[place]] entry not applied: check not done (#41) | port | rc:760 |
| r17 | reproducible | two releases equal but date lines; board untouched | port | rc:849 |
| r17 | fill_stale | stale fill releases as a fresh fill (#30) | port | rc:886 |
| r17 | rejected_numbered | .rejected, .rejected.2, .rejected.3; owner file kept (#35) | port | rc:940 |
| r17 | netclass_one_net | netclass on VBUS survives check (#28) | port | rc:548 |
| r17 | own_track_width | board track-width rule survives check (#28) | port | rc:555 |
| r17 | own_clearance_rule | VBUS 0.5 mm rule survives check (#28) | port | rc:562 |
| r17 | netclass_default_truncated | 0.3 mm Default netclass: drc-truncated, gate stops | port | rc:569 |
| r17 | own_rule_looser | looser board rule: fab run still finds clearance | port | rc:584 |
| r17 | drc_exclusions | project DRC exclusions do not hide a violation | port | rc:599 |
| r17 | pro_ignores_open | unconnected_items ignored: open still found (#37) | port | rc:606 |
| r17 | pro_ignores_short | shorting_items ignored: short still found (#37) | port | rc:612 |
| r17 | npth_round | npth_copper at 0.05 and 0.09 mm, not 0.12 mm | port | rc:953 |
| r17 | npth_slot | npth_copper on slots, upright and turned | port | rc:972 |
| r17 | pour_own_rules | pour at the board's 0.1 mm does not release (#40) | port | rc:982 |
| r17 | pour check | NOTE (#40) | evidence | NOTE |
| r17 | inner_hole_clearance | no In1 copper under 0.3 mm from a hole released (#40) | port | rc:1003 (as the probe ran: no waivers, the gate refuses); rc:1025 with every finding waived, recording today's behaviour (released, 0.2 mm), marked "owner decision pending: review 17, finding 40" |
| r17 | slack_widths | 0.149 and 0.145 mm tracks found, 0.15 mm not (#32) | port | rc:1037 |
| r17 | slack silk | NOTE (#32) | evidence | NOTE |
| r17 | slot_turned_90 | rejected (#31) | port | rc:428 |
| r17 | slot_turned_10 | rejected (#31) | port | rc:428 |
| r17 | slot_reversed | done (#31) | port | rc:428 |
| r17 | slot_turned_3 | NOTE | evidence | NOTE |
| r17 | route_vs_alternate | routed slots against G85 slots: rejected | port | rc:437 |
| r17 | route_slot_turned | NOTE (#42) | evidence | NOTE |
| r17 | route_slot_deleted | NOTE (#42) | evidence | NOTE |
| r17 | unread_second_fcu | refused gerber-set (#34) | port | rc:458 |
| r17 | unread_comment_layer | refused gerber-set (#34) | port | rc:458 |
| r17 | unread_unnamed_gbr_no_x2 | refused gerber-set (#34) | port | rc:458 |
| r17 | unread_inner_g1_no_x2 | NOTE (#43) | evidence | NOTE |
| r17 | unread_drill_as_txt | NOTE (#43) | evidence | NOTE |
| r17 | unread_third_drl | a third .drl is read: rejected (#34) | port | rc:458 |
| r17 | multiline_max | max raised after a header-shaped line: stale (#33) | port | rc:658 |
| r17 | layout_only | comments and order leave the gate fresh (#33) | port | rc:671 |
| r17 | why_changed | waiver reason reworded: stale (#33) | port | rc:678 |
| r17 | silk_line_rect | silk lines and rects placed: turned, bottom, board (#36) | port | ic "m3_silk_line_rect" (verify_import) |
| r17 | filled rect | NOTE (#45) | evidence | NOTE |
| r17 | rename_through_pad_checked | renamed trace through B's pad stops at check (#38) | port | rc:632 |

## Counts

| folder | covered | port | evidence | total |
| --- | --- | --- | --- | --- |
| r15 | 20 | 34 | 9 | 63 |
| r16 | 14 | 20 | 19 | 53 |
| r17 | 0 | 41 | 9 | 50 |
| all | 34 | 95 | 37 | 166 |

Added with the audit (not a review verdict): rc:1010 "audit r17 check reused work folder": pcb check twice on the inner_hole board with one `--work` folder gives the same findings (`# source: audit of review 17, reused work folder`). The bug it covers is fixed in src (check.rs clears its copies; `kicad::copy_rules` removes rule and project files the source lacks; `drc_counts_with` deletes the old report).

## Undecided

- **r17 inner_hole_clearance (review 17, finding 40), owner decision pending.** The probe passed only because a reused `--work` folder made its waiving check see nothing, so the gate refused. With every finding waived, as the probe meant, the release goes out with In1.Cu copper 0.2 mm from another net's component hole, and the read-back does not stop it. rc:1025 records that behaviour; to flip it, assert the reviewer's verdict there instead. rc:1003 keeps the input as the probe ran it.
- **r17 pour_own_rules** had the same double check: in the probe the gate refused. With the waivers it meant to write, the read-back rejects the release, so the port uses the intended input and passes.
