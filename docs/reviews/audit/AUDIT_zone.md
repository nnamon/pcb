# Audit: zone probes (r09 zone gate, r13, r14)

Each verdict in `r09/zone_gate_cases.py` (with `check_splice.py`), `r13/check.py` and `r14/check.py`, with one label:

- **covered**: an existing case or fixture step asserts the same outcome on an equivalent input.
- **port**: added as a case. Zone cases are in `tests/cases/zone_cases.py`, under "Reviews 13 and 14", named `r13_<case>` or `r14_<case>` and built with `tests/lib/spec_board.py`. Edit-gate cases are in `tests/cases/edit_cases.py` (`GATE_ZONE_CASES`). Oracle mutations are in `tests/mutations/zone_mutations.py`. Each one carries `# source: review NN, <case>`.
- **evidence**: the case tested the reviewer's premise (KiCad's behaviour, or a probe's own oracle) rather than pcb, or it was a NOTE that never failed the run.

Line numbers are those of 5 Nov 2026. "zc" is `tests/cases/zone_cases.py`. "Fixture" is the badge_r36a flow in `xtask/src/main.rs`. "zm" is `tests/mutations/zone_mutations.py`.

| folder | case name | what it checks (short) | label | covered by / ported as |
| --- | --- | --- | --- | --- |
| r09 | uuids | edit on the multi-zone board: the result is the input plus the edit outside the fills, fills match pcbnew's refill, 3 runs give the same bytes | port | edit_cases `gate_zones_uuids` |
| r09 | no_uuids | the same with the zone uuids stripped | port | edit_cases `gate_zones_no_uuids` |
| r09 | footprint_zone | a track across a footprint's own GND zone is not rejected on a stale fill (finding 2) | port | edit_cases `gate_zones_footprint_zone` |
| r09 | check_splice.py (oracle) | part 1: input plus appended lines; part 2: each fill (board and footprint) against pcbnew's refill | port | `spec_board.input_plus_appended`, `spec_board.fill_vs_pcbnew`, used by the three cases above (verify_edit cannot read footprint zone fills) |
| r13 | stitch via_in_pad | no via on a solid 4 mm GND pad (#3) | port | `r13_via_in_pad` |
| r13 | stitch keepout_via | no via in a via-only keep-out (#4) | port | `r13_keepout_via` |
| r13 | stitch two_entries | two stitch entries on one grid: refused, or no duplicate via uuids (#9) | port | `r13_two_entries` |
| r13 | stitch one_layer | NOTE #13: no via and no warning | evidence | NOTE; the later warning is r14 nofill_one |
| r13 | stitch margins | every stitching via is at least 0.3 mm from pads, tracks, vias, NPTH, edge and other stitching vias | port | `r13_margins` |
| r13 | stitch pitch_below_size | a pitch below size plus margin is refused or rejected | covered | zc:278 `pitch_below_size` (refused config) |
| r13 | stitch pitch_tiny | a 1 µm pitch is refused (#5) | covered | zc:276 `pitch_tiny` |
| r13 | stitch rect_inf | an infinite stitch rect is refused (#5) | port | `r13_rect_inf` |
| r13 | stitch rect_huge | a ±1e6 rect is refused (#5) | covered | zc:277 `grid_too_big` |
| r13 | stitch resave | after a KiCad save, the second run replaces its own 2 zones and vias, none doubled | port | `r13_resave` |
| r13 | feature keepout_flags | keep-out rect with grow, layer subset, forbid flags as pcbnew reads them | port | `r13_keepout_flags` |
| r13 | feature keepout_layer_clip | an In2.Cu-only keep-out leaves the F.Cu P fill (#6) | port | `r13_keepout_layer_clip` |
| r13 | feature zone_settings | clearance, thermal, priority, min width, connect, islands | port | `r13_zone_settings` |
| r13 | feature fill_priority | the higher fill_priority keeps the overlap; nothing off the board | port | `r13_fill_priority` |
| r13 | feature pad_override | overrides none and solid as pcbnew reads them | port | `r13_pad_override` |
| r13 | feature pad_override_dropped | a dropped override restores the pad's setting (#7) | covered | zc:215-221 `override_dropped` |
| r13 | feature changed | changed settings: 5 own zones removed, a hand zone and via kept | port | `r13_changed` |
| r13 | feature dup_zone | two entries for one net and layer are refused (#8) | covered | zc:272 `dup_zone` |
| r13 | feature dup_keepout | two keep-outs with one name are refused (#8) | covered | zc:273 `dup_keepout` |
| r13 | feature dup_layer | one layer twice in a zone: refused, or no duplicate uuids (#8) | port | `r13_dup_layer` |
| r13 | feature forbid_nothing | NOTE #15: accepted | evidence | NOTE (now refused, zc:274) |
| r13 | feature same_priority_refill | same-priority fills with uuids against file order match a KiCad refill (#1) | port | `r13_same_priority_refill` |
| r13 | tie turn_0_top | tie copper and via pads land where X was, X gone, second run gives the same bytes | port | `r13_turn_0_top` |
| r13 | tie turn_90_top | the same, turned 90° | port | `r13_turn_90_top` |
| r13 | tie turn_30_top | the same, turned 30° | port | `r13_turn_30_top` |
| r13 | tie turn_0_bottom | the same, flipped | port | `r13_turn_0_bottom` |
| r13 | tie turn_135_bottom | the same, flipped and turned 135° | port | `r13_turn_135_bottom` |
| r13 | tie third_net | NOTE #14 | evidence | NOTE (the refusal is r14 tht_other_net) |
| r13 | tie junction | NOTE #14 | evidence | NOTE |
| r13 | tie absorbed_has_pad | NOTE #14 | evidence | NOTE (the refusal is r14 absorbed_pad_on_tie) |
| r13 | tie vias_only | three vias become pads 3, 4, 5 on B, in order | port | `r13_vias_only` |
| r13 | tie under_pad | a B.Cu run under another part's pad is one run, retyped (#10) | port | `r13_under_pad` |
| r13 | tie vias_net_missing | absorb_vias_net not on the board is refused (#11) | covered | zc:279 `vias_net_missing` |
| r13 | refuse unknown_key | unknown pcb.toml key: refused config, nothing written | port | `r13_unknown_key` |
| r13 | refuse zone_clearance_nan | NaN clearance refused | port | `r13_zone_clearance_nan` |
| r13 | refuse min_width_zero | min_width 0 refused | port | `r13_min_width_zero` |
| r13 | refuse connect_bad | bad connect word refused | port | `r13_connect_bad` |
| r13 | refuse fill_layer_missing | [fill] layer the board lacks refused | port | `r13_fill_layer_missing` |
| r13 | refuse keepout_layer_missing | keep-out layer the board lacks refused | port | `r13_keepout_layer_missing` |
| r13 | refuse keepout_layers_word | layers = "every" refused | port | `r13_keepout_layers_word` |
| r13 | refuse stitch_net_missing | stitch net not on the board refused | port | `r13_stitch_net_missing` |
| r13 | refuse stitch_drill_ge_size | drill not below size refused | port | `r13_stitch_drill_ge_size` |
| r13 | refuse allow_max_negative | max -1 refused | port | `r13_allow_max_negative` |
| r13 | refuse width_rule_unknown_net | [nets.OLD] width_mm on a missing net refused | port | `r13_width_rule_unknown_net` |
| r13 | refuse pad_override_no_dot | pad without REF.PAD refused | port | `r13_pad_override_no_dot` |
| r13 | refuse schema_2 | schema 2 refused | port | `r13_schema_2` |
| r13 | refuse no_pcb_toml | no pcb.toml refused | port | `r13_no_pcb_toml` |
| r13 | refuse board_missing | board missing refused | port | `r13_board_missing` |
| r13 | refuse out_is_folder | -o a folder: usage | port | `r13_out_is_folder` |
| r13 | refuse out_folder_missing | -o in a missing folder: usage | port | `r13_out_folder_missing` |
| r13 | refuse work_is_file | --work a file: usage | port | `r13_work_is_file` |
| r13 | refuse out_is_candidate | -o inside the work folder: output-in-work | port | `r13_out_is_candidate` |
| r13 | refuse zone_clearance_inf | NOTE #12 | evidence | NOTE (now refused, zc:275) |
| r13 | refuse thermal_gap_inf | NOTE #12 | evidence | NOTE (now refused, r14 inf_thermal_gap) |
| r13 | refuse keepout_rect_inf | NOTE #12 | evidence | NOTE (now refused, r14 inf_keepout_rect) |
| r13 | refuse allow_unknown_net | NOTE #16 | evidence | NOTE |
| r13 | refuse allow_unknown_kind | NOTE #16 | evidence | NOTE |
| r13 | refuse project_as_file | --project naming pcb.toml runs | port | `r13_project_as_file` |
| r13 | refuse out_default_overwrites | -o the input overwrites it, writes no other board | port | `r13_out_default_overwrites` |
| r13 | refuse rejected_onto_input | rejected with -o the input: input kept, .rejected beside it | port | `r13_rejected_onto_input` |
| r13 | allow control | the control board zones | port | `r13_allow_control` |
| r13 | allow none | a cut-off pad with no allowance is rejected | covered | zc:191 `cut_off_rejected` |
| r13 | allow allow_at_max_1 | one cut-off, max 1: done, one allowed, drc-allowed | covered | zc:191, zc:203 `cut_off_allowed` |
| r13 | allow allow_at_max_2 | two cut-off, max 2: done | port | `r13_allow_at_max_2` |
| r13 | allow above_max_2 | above max is rejected | covered | zc:192 `cut_off_two_over_max` |
| r13 | allow with_real_regression | GND allowed, AGND stays a regression | port | `r13_allow_with_real_regression` |
| r13 | allow kind_not_grown | a kind that did not grow allows nothing | port | `r13_allow_kind_not_grown` |
| r13 | allow wrong_net | an allowance on another net does not cover | port | `r13_allow_wrong_net` |
| r13 | allow typo | a misspelt kind does not cover | port | `r13_allow_unknown_kind_typo` |
| r13 | allow any_nets_max_1 | NOTE #16 | evidence | NOTE |
| r13 | allow ratchet_2 | NOTE #16 | evidence | NOTE |
| r13 | fill pcbnew_writes_flag | the result has as many `(fill yes` as pcbnew wrote | port | `r13_pcbnew_writes_flag` |
| r13 | fill flag_meaning | KiCad loads fills with or without the flag | evidence | KiCad's behaviour |
| r13 | fill check_splice_masks_shape_fill | check_splice.py masked a shape's `(fill yes)` (#17) | evidence | tested a probe oracle; `spec_board.strip_fills` and verify_edit mask zone flags only |
| r13 | badge zone | done, allowed list exactly two, stitch ≥ 190, zone kinds 2/4/34, DRC 189 → 72 | port | `r13_badge_zone` |
| r13 | badge verify_zones | verify_zones passes on the zoned badge | covered | Fixture main.rs:514 "badge_r36a: verify_zones" |
| r13 | badge allowed_items | the allowed DRC items are J701.2, J102.4 and L601.3 | port | `r13_badge_allowed_items` |
| r13 | badge stitch | via count equals the report; none on a pad, in a keep-out, or near another net's pad | port | `r13_badge_stitch` |
| r13 | badge oracle_stitch | verify_zones catches stitching removed, and a via on a pad (#2) | covered | zm:135 `stitch_removed`, zm:141 `stitch_on_pad` (target J) |
| r13 | badge refill | a KiCad refill keeps fills per net and layer; verify_zones passes on it (#1) | port | `badge_refill` (one case with r14's) |
| r13 | badge j102_solid | J102.4 solid: verify_zones fails check D | covered | zm:148 `plated_pad_solid` (solid_override_pad J102.4, target D) |
| r14 | stitch pad_shapes | no via within 0.3 mm of any pad shape: turned, bottom, oval, roundrect, THT (#3) | port | `r14_pad_shapes` |
| r14 | stitch pad_custom | the same with a custom pad (#3) | port | `r14_pad_custom` |
| r14 | stitch keepout_inner_grow | via keep-out on In2.Cu with grow (#4) | port | `r14_keepout_inner_grow` |
| r14 | stitch keepout_board_rule_area | hand-drawn via rule area (#4) | port | `r14_keepout_board_rule_area` |
| r14 | stitch keepout_footprint_rule_area | footprint's via rule area (#4) | port | `r14_keepout_footprint_rule_area` |
| r14 | stitch pitch_tiny | refused within 10 s (#5) | covered | zc:276 `pitch_tiny` |
| r14 | stitch rect_inf | refused within 10 s | port | `r14_rect_inf` |
| r14 | stitch rect_neg_inf | refused within 10 s | port | `r14_rect_neg_inf` |
| r14 | stitch pitch_nan | refused within 10 s | port | `r14_pitch_nan` |
| r14 | stitch rect_huge | refused (#5) | covered | zc:277 `grid_too_big` (same rect and pitch) |
| r14 | stitch grid_near_limit | a grid just under the limit runs within 60 s | port | `r14_grid_near_limit` |
| r14 | stitch two_sizes | overlapping entries of two via sizes keep 0.3 mm apart (#9) | port | `r14_two_sizes` |
| r14 | stitch pitch_below | pitch below size plus margin refused (#9) | covered | zc:278 `pitch_below_size` |
| r14 | stitch pitch_eq_0p9 | pitch equal to size plus margin runs | port | `r14_pitch_eq_0p9` |
| r14 | stitch pitch_eq_1p1 | the same | port | `r14_pitch_eq_1p1` |
| r14 | stitch pitch_eq_0p85 | NOTE R14-4 | evidence | NOTE |
| r14 | stitch pitch_eq_1p2 | NOTE R14-4 | evidence | NOTE |
| r14 | stitch nofill_one | stitch-no-fill names GND:B.Cu (#13) | port | `r14_nofill_one` |
| r14 | stitch nofill_none_missing | no warning when both layers fill | port | `r14_nofill_none_missing` |
| r14 | fill same_prio_against | fills match a KiCad refill (#1) | port | `r14_same_prio_against` |
| r14 | fill same_prio_with | the same | port | `r14_same_prio_with` |
| r14 | fill hand_upper_high | a hand zone with an upper-case uuid sorting high: match a refill | port | `r14_hand_upper_high` |
| r14 | fill hand_upper_mid | the same, mid | port | `r14_hand_upper_mid` |
| r14 | fill hand_lower_low | the same, low | port | `r14_hand_lower_low` |
| r14 | fill fp_zone_high | a footprint zone sorting high: match a refill | port | `r14_fp_zone_high` |
| r14 | fill fp_zone_low | the same, low | port | `r14_fp_zone_low` |
| r14 | fill fp_zone order matters | the two orders differ by over 1 mm² (probe sensitivity) | port | `r14_fp_zone_order_matters` |
| r14 | fill hand_legacy | NOTE R14-5 | evidence | NOTE |
| r14 | fill hand_no_uuid | NOTE R14-5 | evidence | NOTE |
| r14 | fill ko_inner_only | an inner keep-out leaves F and B fills; matches a refill (#6) | port | `r14_ko_inner_only` |
| r14 | fill ko_front_only | F.Cu cut, B.Cu kept | port | `r14_ko_front_only` |
| r14 | fill ko_all | both cut | port | `r14_ko_all` |
| r14 | fill ov_same | one fill-overlap naming A and B; a second run gives the same warnings and bytes | port | `r14_ov_same` |
| r14 | fill ov_distinct | distinct priorities: no warning | covered | zc:227 `overlap_settled` |
| r14 | fill ov_apart | apart: no warning | port | `r14_ov_apart` |
| r14 | fill ov_three | three pairs; the same on a second run | port | `r14_ov_three` |
| r14 | fill ov_plane | NOTE R14-1 | evidence | NOTE |
| r14 | fill ov_hand_zone | NOTE R14-1 | evidence | NOTE |
| r14 | fill ov_two_planes | NOTE R14-1 | evidence | NOTE |
| r14 | fill oracle_regex | check_splice and gate12 mask zone flags, not shape flags (#17) | evidence | tested probe oracles, which leave with the folders |
| r14 | override change_none_then | none and solid set (#7) | port | `r14_change_none_then` |
| r14 | override change_changed | changed overrides, property value | port | `r14_change_changed` |
| r14 | override change_dropped | dropped: pads restored, no property | port | `r14_change_dropped` |
| r14 | override two_one_dropped | one footprint's overrides dropped | port | `r14_two_one_dropped` |
| r14 | override two_resaved | the property survives a KiCad save, hidden | port | `r14_two_resaved` |
| r14 | override two_all_dropped_after_resave | all dropped after the save restores every pad | port | `r14_two_all_dropped_after_resave` |
| r14 | override two_again_same | the same overrides again give the same bytes | port | `r14_two_again_same` |
| r14 | override repeat_set | a shared pad number sets both pads | port | `r14_repeat_set` |
| r14 | override repeat_dropped | NOTE R14-2 | evidence | NOTE |
| r14 | override diff_resave | pcb diff against a KiCad re-save shows no change | port | `r14_diff_resave` |
| r14 | override edit_move | move_footprint keeps the property; dropping it then restores the pads | port | `r14_edit_move` |
| r14 | tie tht_tie | THT tie, copper on B.Cu, via pad 3 (#10) | port | `r14_tht_tie` |
| r14 | tie tht_other_net | run through another part's THT pad refused | port | `r14_tht_other_net` |
| r14 | tie bottom_under_top_pad | bottom tie under a top pad: one run | port | `r14_bottom_under_top_pad` |
| r14 | tie retype_other_parts | absorbed run between A pads retyped (#14) | port | `r14_retype_other_parts` |
| r14 | tie absorbed_pad_on_tie | absorbed net on a tie pad refused | port | `r14_absorbed_pad_on_tie` |
| r14 | tie vias_net_is_absorbed | NOTE R14-3 | evidence | NOTE |
| r14 | config dup_keepout_name | refused (#8) | covered | zc:273 `dup_keepout` |
| r14 | config dup_zone_two_entries | refused (#8) | covered | zc:272 `dup_zone` |
| r14 | config dup_zone_one_entry | a layer twice in one entry refused | port | `r14_dup_zone_one_entry` |
| r14 | config dup_keepout_layer | refused | port | `r14_dup_keepout_layer` |
| r14 | config dup_fill_layer | refused | port | `r14_dup_fill_layer` |
| r14 | config ok_names_differ_in_case | k and K both run | port | `r14_ok_names_differ_in_case` |
| r14 | config ok_zone_split_entries | one net over two entries runs | port | `r14_ok_zone_split_entries` |
| r14 | config ok_two_nets_one_layer | runs | port | `r14_ok_two_nets_one_layer` |
| r14 | config forbid_empty | refused (#15) | covered | zc:274 `forbid_nothing` |
| r14 | config ok_forbid_one | runs | port | `r14_ok_forbid_one` |
| r14 | config inf_keepout_rect | refused (#12) | port | `r14_inf_keepout_rect` |
| r14 | config inf_keepout_grow | refused | port | `r14_inf_keepout_grow` |
| r14 | config inf_zone_clearance | refused | covered | zc:275 `clearance_inf` |
| r14 | config inf_zone_min_width | refused | port | `r14_inf_zone_min_width` |
| r14 | config inf_thermal_gap | refused | port | `r14_inf_thermal_gap` |
| r14 | config nan_thermal_spoke | refused | port | `r14_nan_thermal_spoke` |
| r14 | config inf_fill_grow | refused | port | `r14_inf_fill_grow` |
| r14 | config inf_current | refused | port | `r14_inf_current` |
| r14 | config inf_width | refused | port | `r14_inf_width` |
| r14 | config inf_fill_clearance | refused | port | `r14_inf_fill_clearance` |
| r14 | config inf_fill_min_width | refused | port | `r14_inf_fill_min_width` |
| r14 | config inf_stitch_size | refused | port | `r14_inf_stitch_size` |
| r14 | config inf_stitch_margin | refused | port | `r14_inf_stitch_margin` |
| r14 | config nan_stitch_rect | refused | port | `r14_nan_stitch_rect` |
| r14 | badge run | no overlap or unfilled warning, only drc-allowed, stitch ≥ 190, tie 49 segments / 2 retyped / via pads 3, 4 | port | `r14_badge_run` |
| r14 | badge refill | a KiCad refill keeps every zone's fill; verify_zones passes on it (#1) | port | `badge_refill` |
| r14 | badge refill_twice | KiCad's refill of its own refill changes nothing | evidence | KiCad's behaviour |
| r14 | badge oracle_j | verify_zones check J catches: one via below the floor, vias over pad edges (GND SMD, GND THT, other net), in a keep-out, and at a grown keep-out's edge; exactly the floor passes (#2) | port | zm `stitch_below_floor`, `stitch_edge_gnd_smd`, `stitch_edge_gnd_tht`, `stitch_edge_other_net`, `stitch_in_keepout`, `stitch_keepout_edge` (target J), and the control `stitch_keep_floor passes` |
| r14 | badge oracle_d | check D catches J102.4 solid after a refill (#2) | covered | zm:148 `plated_pad_solid` |
| r14 | badge oracle_d no refill | NOTE R14-6 | evidence | NOTE |

Probe outputs that carried no verdict (r14 `original`, `two_set` and `diff_with_property`) are left out of the table.

## Counts

| label | r09 | r13 | r14 | total |
| --- | --- | --- | --- | --- |
| covered | 0 | 13 | 9 | 22 |
| port | 4 | 54 | 66 | 124 |
| evidence | 0 | 14 | 12 | 26 |
| total | 4 | 81 | 87 | 172 |

The badge cases run the badge through `pcb import-tscircuit` and `pcb zone` once, inside zone_cases.py, which takes about 25 s. They need the run's JSON reply (its allowances, warnings, tie counts and stitch count), and the fixture flow does not keep that reply. The fixture flow runs after the cases, so its zoned board may also be older than the binary under test.
