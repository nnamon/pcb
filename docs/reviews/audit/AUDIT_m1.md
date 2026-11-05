# Audit of review probes, group M1 (reviews 8 to 12)

Every verdict in `r08/`, `r09/` (except `zone_gate_cases.py`, audited separately), `r10/`, `r11/` and `r12/`, labelled as the test method in `DESIGN.md` says:

- **covered**: an existing case checks the same outcome on an equivalent input.
- **port**: now a case in a case file, or a mutation in `tests/mutations/edit_mutations.py`, with a comment `# source: review NN, <case name>`.
- **evidence**: the probe tested a premise, not pcb, or never failed the run.

Where ported cases live:

- `edit_cases.py` cases are `rNN_<name>` in `M1_CASES`, run by `run_m1`.
- `diff_cases.py` cases are `M1["rNN_<name>"]`. Review 10, 11 and 12 re-saves and misses are generated from the tables `R10_RESAVE`, `R11_HAND`, `R12_MISS` and `R12_RESAVE`, and keep the probe's name. Review 12 re-saves get the prefix `r12_resave_`.
- `contract_cases.py` cases are `m1_<name>`.
- `route_cases.py` cases are `rNN_<name>` in `M1_CASES`.

Shared inputs:

- `tests/lib/gate_board.py` builds the pcbnew boards of reviews 8 and 10 to 12.
- `tests/lib/fake_java/` holds the stand-in java, copied from `r09/fake/`.

Two cases count as covered by another ported case rather than by an older one, so the suite does not check the same thing twice:

- Review 10's closure diffs reproduce review 9's misses.
- Review 11's `dup_no_uuid_filled` is review 10's `dup_no_uuid` with the same board and edit.

`r09/check_splice.py` and `r09/zone_board.py` are helpers of `zone_gate_cases.py` and hold no verdicts of their own. `r10/lib.py` is a helper; its builder is now `gate_board.py`.

| folder | case name | what it checks (short) | label | covered by / ported as |
| --- | --- | --- | --- | --- |
| r08 edit_probes | self_join_polyline_refused | polyline doubling back on itself refused, edit-unjoined | covered | edit_cases.py:54 `self_loop_refused` (same ops) |
| r08 edit_probes | floating_triangle_refused | two new tracks touching only each other refused, edit-unjoined | port | edit_cases `r08_floating_triangle_refused` |
| r08 edit_probes | stacked_floating_vias_refused | two new vias at one free point refused | port | edit_cases `r08_stacked_floating_vias_refused` |
| r08 edit_probes | via_uuid_and_wrong_at_refused | delete via by uuid with a contradicting `at` refused | port | edit_cases `r08_via_uuid_and_wrong_at_refused` |
| r08 edit_probes | track_uuid_and_wrong_ends_refused | delete track by uuid with wrong layer and ends refused | port | edit_cases `r08_track_uuid_and_wrong_ends_refused` |
| r08 edit_probes | zoned_board_byte_identical_elsewhere | gzone edit done, verify_edit passes | covered | edit_cases.py:52 `zoned_join_n` (gzone, same ops, verify_edit, run twice) |
| r08 edit_probes | same_item_by_uuid_and_position_refused | one via named by uuid and by position refused, edit-op | port | edit_cases `r08_same_item_by_uuid_and_position_refused` |
| r08 edit_probes | end_on_arc_counts_as_joined | an end on a track arc is not edit-unjoined | port | edit_cases `r08_end_on_arc_counts_as_joined` |
| r08 edit_probes | locked_set_width_refused | set_width on a locked track refused, edit-locked | port | edit_cases `r08_locked_set_width_refused` |
| r08 edit_probes | free_end_other_end_checked | free end set, other end still unjoined, refused | port | edit_cases `r08_free_end_other_end_checked` |
| r08 edit_probes | contract_in_every_run | every edit output passes the contract | covered | edit_cases.py:330 (contract check on every case run; `run_m1` checks its own) |
| r08 diff_probes | turned | footprint turned 90° reported "turned" | port | diff_cases `r08_turned` |
| r08 diff_probes | flipped | footprint flipped reported "flipped" | port | diff_cases `r08_flipped` |
| r08 diff_probes | rotation_270_equals_minus_90 | 270° and −90° identical | port | diff_cases `r08_rotation_270_equals_minus_90` |
| r08 diff_probes | footprint_removed | S3 reported removed | port | diff_cases `r08_footprint_removed` |
| r08 diff_probes | pad_size_changed | pad size inside a footprint not identical | port | diff_cases `r08_pad_size_changed` |
| r08 diff_probes | pad_moved_in_footprint | pad moved in its footprint not identical | port | diff_cases `r08_pad_moved_in_footprint` |
| r08 diff_probes | duplicate_reference_move_seen | move of one of two same-reference footprints seen | port | diff_cases `r08_duplicate_reference_move_seen` |
| r08 diff_probes | duplicate_track_added | a duplicate track counts as one added, 42 mm | port | diff_cases `r08_duplicate_track_added` |
| r08 diff_probes | via_size_change | via size: one removed, one added | port | diff_cases `r08_via_size_change` |
| r08 diff_probes | outline_change_not_identical | board outline change seen | port | diff_cases `r08_outline_change_not_identical` |
| r08 diff_probes | arc_change_not_identical | track arc mid moved seen | port | diff_cases `r08_arc_change_not_identical` |
| r08 diff_probes | zone_moved_not_identical | zone moved by pcbnew seen | port | diff_cases `r08_zone_moved_not_identical` |
| r08 diff_probes | lock_change_seen | a track's lock removed seen | port | diff_cases `r08_lock_change_seen` |
| r08 project_probes | init_board_path_relative_to_pcb_toml | init with `-o` elsewhere; status finds the board | port | contract_cases `m1_init_board_path_relative_to_pcb_toml` |
| r08 project_probes | init_output_passes_status_odd_name | init never writes a file status refuses (`.kicad_pcb.v2`) | port | contract_cases `m1_init_output_passes_status_odd_name` |
| r08 project_probes | init_output_passes_status_empty_name | the same with `--name ""` | port | contract_cases `m1_init_output_passes_status_empty_name` |
| r08 project_probes | init_counts_mixed_copper_layer | a "mixed" inner layer counts: 4 layers | port | contract_cases `m1_init_counts_mixed_copper_layer` |
| r08 project_probes | version_mismatch_warned | VERSION one folder up differs: version-mismatch | port | contract_cases `m1_version_mismatch_warned` |
| r08 project_probes | tag_found | the tag in TAGS.tsv above is recorded | port | contract_cases `m1_tag_found` |
| r08 project_probes | tag_prefix_not_counted | `xproj-v…` and `…-rc` tags do not count | port | contract_cases `m1_tag_prefix_not_counted` |
| r08 project_probes | impossible_date_is_a_problem | date 2026-13-45 listed in problems | port | contract_cases `m1_impossible_date_is_a_problem` |
| r08 project_probes | negative_grow_is_a_problem | keep-out `grow_mm = -5` listed in problems | port | contract_cases `m1_negative_grow_is_a_problem` |
| r08 project_probes | missing_board_reported_as_config | board named in pcb.toml missing: refused | port | contract_cases `m1_missing_board_reported_as_config` |
| r08 project_probes | schema_float_message | `schema = 1.0` not called "no schema key" | port | contract_cases `m1_schema_float_message` |
| r08 route_probes | prewired_set_width_survives_rip | prewired 0.5 mm W track kept through `--rip W` (Freerouting) | port | route_cases `r08_prewired_set_width_survives_rip` |
| r08 route_probes | prewired_readd_survives_rip | prewire delete-all and re-add at 0.45 kept through rip | port | route_cases `r08_prewired_readd_survives_rip` |
| r08 route_probes | prewired_stub_not_pruned | prewired L stub from pad L2 kept, L ripped | port | route_cases `r08_prewired_stub_not_pruned` |
| r08 route_probes | width_twice_refused | `--width` twice for one net refused | port | route_cases `r08_width_twice_refused` |
| r08 move_fp_vs_pcbnew | move_footprint matches pcbnew | turned, flipped footprint: pads, graphic, rule area where pcbnew's move puts them | port | edit_cases `r08_move_footprint_matches_pcbnew` (board `gate_board.py fp_rotated`) |
| r08 verify_edit_mutations | new_segment_locked | verify_edit catches a lock on new copper | port | edit_mutations.py `m_new_segment_locked` |
| r08 verify_edit_mutations | new_via_locked | verify_edit catches a lock on a new via | port | edit_mutations.py `m_new_via_locked` |
| r08 verify_edit_mutations | set_width_uuid_changed | verify_edit catches a widened track's changed uuid | port | edit_mutations.py `m_set_width_uuid_changed` |
| r08 verify_edit_mutations | set_width_locked | verify_edit catches a lock gained by set_width | port | edit_mutations.py `m_set_width_locked` |
| r08 verify_edit_mutations | move_via_uuid_changed | verify_edit catches a moved via's changed uuid | port | edit_mutations.py `m_move_via_uuid_changed` |
| r08 verify_edit_mutations | move_via_layers_changed | verify_edit catches a moved via's changed layers | port | edit_mutations.py `m_move_via_layers_changed` |
| r08 verify_edit_mutations | delete_uuid_wrong_item | verify_edit catches delete-by-uuid taking the wrong via | port | edit_mutations.py `m_delete_uuid_wrong_item` |
| r09 join_probes | set_width_all_of_chain | widening every W segment accepted, verify_edit | port | edit_cases `r09_set_width_all_of_chain` |
| r09 join_probes | set_width_middle_only | widening the middle W segment accepted | port | edit_cases `r09_set_width_middle_only` |
| r09 join_probes | move_via_small_unlock | locked via moved 0.05 mm with unlock accepted | port | edit_cases `r09_move_via_small_unlock` |
| r09 join_probes | move_via_relay_tracks | via moved and its three tracks laid again accepted | port | edit_cases `r09_move_via_relay_tracks` |
| r09 join_probes | delete_all_dup_readd | delete both duplicates, re-add one | covered | edit_cases.py:47 `duplicate_delete_all_and_readd` (same ops, dup, verify_edit) |
| r09 join_probes | delete_all_dup_readd_two_segments | the same, re-added as two segments | port | edit_cases `r09_delete_all_dup_readd_two_segments` |
| r09 join_probes | move_fp_with_track | N1 moved and joined by a new track | port | edit_cases `r09_move_fp_with_track` |
| r09 join_probes | move_fp_and_relay_its_track | W1 moved, its track deleted and laid again | port | edit_cases `r09_move_fp_and_relay_its_track` |
| r09 join_probes | new_chain_from_pad_through_two_vias | pad, track, via, B.Cu track, via, track, pad accepted | covered | edit_cases.py:24 `join_n_through_vias` (same chain, vias at 30/35 not 25/35; done and verify_edit) |
| r09 join_probes | move_stitching_via | gzone stitching via moved, fed by the zone | port | edit_cases `r09_move_stitching_via` |
| r09 join_probes | set_width_zone_fed_track | widening a B.Cu GND track fed only by the zone | port | edit_cases `r09_set_width_zone_fed_track` |
| r09 join_probes | floating_square_loop | closed square of new track refused | port | edit_cases `r09_floating_square_loop` |
| r09 join_probes | floating_track_between_new_vias | track between two new free vias refused | port | edit_cases `r09_floating_track_between_new_vias` |
| r09 join_probes | floating_b_side_pair | two B.Cu tracks touching only each other refused | port | edit_cases `r09_floating_b_side_pair` |
| r09 join_probes | moved_via_onto_floating_new_track | via moved onto self-joined new track refused | port | edit_cases `r09_moved_via_onto_floating_new_track` |
| r09 join_probes | end_over_other_layer_track | F.Cu end over a B.Cu track of its net, no via: refused | port | edit_cases `r09_end_over_other_layer_track` |
| r09 join_probes | end_on_other_net | end on another net's track refused, edit-unjoined | covered | edit_cases.py:28 `unjoined_end_refused` (its end (30,20) lies on L's F.Cu track) |
| r09 join_probes | delete_track_with_at | `at` on a track delete refused, edit-op | covered | edit_cases.py:57 `delete_via_at_for_track_refused` (same ops) |
| r09 join_probes | delete_via_with_layer | `layer` on a via delete refused, edit-op | port | edit_cases `r09_delete_via_with_layer` |
| r09 join_probes | delete_track_uuid_only_start | track delete with only `start` refused, edit-op | port | edit_cases `r09_delete_track_uuid_only_start` |
| r09 join_probes | delete_track_uuid_right_ends_reversed | uuid plus the right ends reversed accepted, verify_edit | port | edit_cases `r09_delete_track_uuid_right_ends_reversed` |
| r09 join_probes | delete_track_uuid_wrong_layer_only | uuid with a wrong layer refused, edit-mismatch | port | edit_cases `r09_delete_track_uuid_wrong_layer_only` |
| r09 join_probes | delete_track_uuid_start_only | uuid with a start only refused, edit-mismatch | port | edit_cases `r09_delete_track_uuid_start_only` |
| r09 join_probes | delete_via_uuid_wrong_net | via uuid with the wrong net refused, edit-mismatch | port | edit_cases `r09_delete_via_uuid_wrong_net` |
| r09 join_probes | delete_via_uuid_right_at | via uuid with the right `at` accepted, verify_edit | port | edit_cases `r09_delete_via_uuid_right_at` |
| r09 join_probes | track_from_arc_mid_to_pad | track from an arc's middle to a pad accepted | port | edit_cases `r09_track_from_arc_mid_to_pad` |
| r09 join_probes | track_near_arc_chord_not_arc | end on the arc's chord, not the arc, refused | port | edit_cases `r09_track_near_arc_chord_not_arc` |
| r09 diff_misses | via_layers_changed | via layers F/B to F/In1 seen | port | diff_cases `r09_via_layers_changed` |
| r09 diff_misses | arc_lock_changed | arc lock seen | port | diff_cases `r09_arc_lock_changed` |
| r09 diff_misses | zone_second_outline_changed | zone's second outline changed seen | port | diff_cases `r09_zone_second_outline_changed` |
| r09 diff_misses | zone_clearance_changed | zone clearance changed seen | port | diff_cases `r09_zone_clearance_changed` |
| r09 diff_misses | footprint_edge_cut_moved | footprint Edge.Cuts line changed seen | port | diff_cases `r09_footprint_edge_cut_moved` |
| r09 diff_misses | pad_layer_order_only | pad layer order only: identical | port | diff_cases `r09_pad_layer_order_only` |
| r09 diff_misses | pad_shape_rect_to_circle | pad shape changed seen | port | diff_cases `r09_pad_shape_rect_to_circle` |
| r09 diff_misses | number_format_only | `33` vs `33.000`: identical | port | diff_cases `r09_number_format_only` |
| r09 diff_misses | footprint_value_changed | footprint value changed seen | port | diff_cases `r09_footprint_value_changed` |
| r09 route_branches | first_closes_all | stand-in java: one run, used 0, done | port | route_cases `r09_first_closes_all` |
| r09 route_branches | preferred_open_rejected_region_kept | open run shorts: region run kept | port | route_cases `r09_preferred_open_rejected_region_kept` |
| r09 route_branches | preferred_region_rejected_open_kept | region run shorts: open run kept | port | route_cases `r09_preferred_region_rejected_open_kept` |
| r09 route_branches | both_rejected | both short: rejected, attempt 1 written | port | route_cases `r09_both_rejected` |
| r09 route_branches | tie_first_kept | tie: first kept | port | route_cases `r09_tie_first_kept` |
| r09 route_branches | second_fails | second run fails: first kept, second-run-failed | port | route_cases `r09_second_fails` |
| r09 route_branches | second_times_out | second run times out: first kept, second-run-failed | port | route_cases `r09_second_times_out` |
| r09 route_branches | first_fails | first run fails: outcome failed | port | route_cases `r09_first_fails` |
| r09 prewire_probes | p1_set_width_middle_track | prewired 0.5 mm middle W track kept through rip (Freerouting) | port | route_cases `r09_p1_set_width_middle_track` |
| r09 prewire_probes | p2_prewire_via_and_track_on_ripped_net | prewired L track, via and B.Cu track kept (Freerouting) | port | route_cases `r09_p2_prewire_via_and_track_on_ripped_net` |
| r09 prewire_probes | p3_router_joins_middle_of_prewire_stub | router joins mid-stub: tail pruned, rest kept | port | route_cases `r09_p3_router_joins_middle_of_prewire_stub` |
| r09 prewire_probes | p4_prewire_tail_on_ripped_end | prewire on a ripped track's end kept | port | route_cases `r09_p4_prewire_tail_on_ripped_end` |
| r09 prewire_probes | p5_input_still_ripped | a prewire op on W leaves L's input rippable (2 ripped) | port | route_cases `r09_p5_input_still_ripped` |
| r09 prewire_probes | p6_identical_readd_counts_as_input | NOTE only; always printed PASS | evidence | none |
| r10 gate_probes | dup_no_uuid | two identical GND zones without uuids: 3 runs done, one file, pcbnew's fills | port | edit_cases `r10_dup_no_uuid` |
| r10 gate_probes | dup_uuid | the same with uuids (control) | port | edit_cases `r10_dup_uuid` |
| r10 gate_probes | second_poly_no_uuid | zones differing only in a second outline | port | edit_cases `r10_second_poly_no_uuid` |
| r10 gate_probes | same_ref_no_uuid | two same-reference footprints, each with a zone | port | edit_cases `r10_same_ref_no_uuid` |
| r10 gate_probes | same_ref_dup_zone_uuid | the same, zones sharing one uuid | port | edit_cases `r10_same_ref_dup_zone_uuid` |
| r10 gate_probes | top_dup_uuid | top-level zones sharing a uuid | port | edit_cases `r10_top_dup_uuid` |
| r10 gate_probes | move_fp_zone_no_uuid | footprint with zone and rule area moved by an odd offset | port | edit_cases `r10_move_fp_zone_no_uuid` |
| r10 gate_probes | move_fp_zone_no_uuid_half | the same by 50 nm | port | edit_cases `r10_move_fp_zone_no_uuid_half` |
| r10 gate_probes | keepouts_no_uuid | identical keep-outs plus a copper zone | port | edit_cases `r10_keepouts_no_uuid` |
| r10 gate_probes | repeated_point_no_uuid | zone outline with a repeated point | port | edit_cases `r10_repeated_point_no_uuid` |
| r10 gate_probes2 | zone_layers_reversed_no_uuid | 2-layer zone written B.Cu first: done | port | edit_cases `r10_zone_layers_reversed_no_uuid` |
| r10 gate_probes2 | via_in_filled_footprint_zone | via into a filled footprint zone: rejected | port | edit_cases `r10_via_in_filled_footprint_zone` |
| r10 join_probes | no_zone_track | GND track in free space, no zone: refused | port | edit_cases `r10_no_zone_track` |
| r10 join_probes | never_filled_track | track joined by a never-filled zone's outline: rejected | port | edit_cases `r10_never_filled_track` |
| r10 join_probes | never_filled_via | via joined the same way: rejected | port | edit_cases `r10_never_filled_via` |
| r10 join_probes | stale_fill_track | track on a stale fill: rejected | port | edit_cases `r10_stale_fill_track` |
| r10 join_probes | stale_fill_via | via on a stale fill: rejected | port | edit_cases `r10_stale_fill_via` |
| r10 join_probes | islands_kept_never_filled_track | islands-kept zone never filled: rejected | port | edit_cases `r10_islands_kept_never_filled_track` |
| r10 join_probes | fp_zone_never_filled_via | via in a never-filled footprint zone: rejected | port | edit_cases `r10_fp_zone_never_filled_via` |
| r10 join_probes | track_on_B_under_F_zone | B.Cu track under an F.Cu zone: refused | port | edit_cases `r10_track_on_B_under_F_zone` |
| r10 closure_probes | move_stitching_via | via fed by a filled B.Cu pour moved: done | port | edit_cases `r10_move_stitching_via` |
| r10 closure_probes | move_feed_via | feed via moved off its pad track: rejected | port | edit_cases `r10_move_feed_via` |
| r10 closure_probes | set_width_fill_fed_track | widening a fill-fed B.Cu track: done | port | edit_cases `r10_set_width_fill_fed_track` |
| r10 closure_probes | move_stitching_via_out_of_pour | via moved out of the pour: refused | port | edit_cases `r10_move_stitching_via_out_of_pour` |
| r10 closure_probes | via_layers_FIn1 | via layers F/B to F/In1 seen | covered | diff_cases `r09_via_layers_changed` (ported, line 132) |
| r10 closure_probes | arc_lock | arc lock seen | covered | diff_cases `r09_arc_lock_changed` (ported, line 134) |
| r10 closure_probes | zone_second_outline | a second outline added to a filled zone seen | port | diff_cases `r10_zone_second_outline` (review 9 moved an outline; this adds one) |
| r10 closure_probes | zone_clearance | zone clearance seen | covered | diff_cases `r09_zone_clearance_changed` (ported, line 138) |
| r10 closure_probes | fp_value | footprint value seen | covered | diff_cases `r09_footprint_value_changed` (ported, line 144) |
| r10 closure_probes | fp_edge_cuts | footprint Edge.Cuts change seen | covered | diff_cases `r09_footprint_edge_cut_moved` (ported, line 140) |
| r10 closure_probes | rejected_run_files_removed | preferred run rejected: done, no `out.rejected.*` left | port | route_cases `r10_rejected_run_files_removed` |
| r10 prewire_probes | single_segment_stub | router joins a one-segment stub's middle: done | port | route_cases `r10_single_segment_stub` |
| r10 prewire_probes | two_segment_stub | joins a two-segment stub next to the pad: done | port | route_cases `r10_two_segment_stub` |
| r10 prewire_probes | two_segment_stub_join_far | joins the free segment: done | port | route_cases `r10_two_segment_stub_join_far` |
| r10 prewire_probes | free_end_also_reached | router also reaches the free end: done | port | route_cases `r10_free_end_also_reached` |
| r10 diff_probes | zone_thermal_gap | zone thermal gap seen | port | diff_cases `r10_zone_thermal_gap` |
| r10 diff_probes | zone_thermal_bridge | zone spoke width seen | port | diff_cases `r10_zone_thermal_bridge` |
| r10 diff_probes | zone_connect_pads_none | zone pad connection "no" seen | port | diff_cases `r10_zone_connect_pads_none` |
| r10 diff_probes | zone_island_mode | island removal mode seen | port | diff_cases `r10_zone_island_mode` |
| r10 diff_probes | zone_hatched | hatched fill seen | port | diff_cases `r10_zone_hatched` |
| r10 diff_probes | copper_gr_poly_added | copper gr_poly added seen | port | diff_cases `r10_copper_gr_poly_added` |
| r10 diff_probes | copper_gr_text_added | copper gr_text added seen | port | diff_cases `r10_copper_gr_text_added` |
| r10 diff_probes | fp_zone_outline | footprint zone outline seen | port | diff_cases `r10_fp_zone_outline` |
| r10 diff_probes | pad_zone_connect | pad zone_connect override seen | port | diff_cases `r10_pad_zone_connect` |
| r10 diff_probes | edge_circle_radius | Edge.Cuts circle radius seen | port | diff_cases `r10_edge_circle_radius` |
| r10 diff_probes | resave_base | pcbnew re-save identical | port | diff_cases `r10_resave_base` |
| r10 diff_probes | resave_via_layers_reversed | re-save of via layers "B.Cu" "F.Cu" identical | port | diff_cases `r10_resave_via_layers_reversed` |
| r10 diff_probes | resave_minimal_zone | re-save of a minimal zone identical | port | diff_cases `r10_resave_minimal_zone` |
| r10 diff_probes | resave_partial_keepout | re-save of a partial keep-out identical | port | diff_cases `r10_resave_partial_keepout` |
| r10 diff_probes | resave_zone_layers_FB | re-save of `F&B.Cu` zone identical | port | diff_cases `r10_resave_zone_layers_FB` |
| r10 diff_probes | resave_track_width_long | re-save of width 0.20000001 identical | port | diff_cases `r10_resave_track_width_long` |
| r11 gate11 | dup_no_uuid_unfilled | review 10's duplicate pair never filled: 3 runs, one file, pcbnew's fills | port | edit_cases `r11_dup_no_uuid_unfilled` |
| r11 gate11 | dup_no_uuid_filled | the same filled (control) | covered | edit_cases `r10_dup_no_uuid` (ported; same board, edit and checks) |
| r11 gate11 | dup_no_uuid_handtext | filled, with a redundant hand-written child | port | edit_cases `r11_dup_no_uuid_handtext` |
| r11 gate11 | same_ref_same_pos | pasted footprints at one place, zones without uuids | port | edit_cases `r11_same_ref_same_pos` |
| r11 gate11 | move_fp_no_uuid | turned footprint with zone moved in the edit | port | edit_cases `r11_move_fp_no_uuid` |
| r11 gate11 | move_fp_no_uuid_2 | two footprints swapped in one edit | port | edit_cases `r11_move_fp_no_uuid_2` |
| r11 prewire11 | anchor_unfilled_zone_two_seg | stub from inside a never-filled zone, two segments: done | port | route_cases `r11_anchor_unfilled_zone_two_seg` |
| r11 prewire11 | anchor_unfilled_zone_one_seg | the same, one segment: done | port | route_cases `r11_anchor_unfilled_zone_one_seg` |
| r11 prewire11 | anchor_pad_two_seg | stub from pad L2 (control): done | port | route_cases `r11_anchor_pad_two_seg` |
| r11 prewire11 | join_at_bend | router joins at the stub's bend: done | port | route_cases `r11_join_at_bend` |
| r11 prewire11 | free_end_on_other_input | stub's free end on other input copper: done | port | route_cases `r11_free_end_on_other_input` |
| r11 diff11 | footprint_zone_connection_none | footprint zone connection seen | port | diff_cases `r11_footprint_zone_connection_none` |
| r11 diff11 | footprint_local_clearance | footprint clearance seen | port | diff_cases `r11_footprint_local_clearance` |
| r11 diff11 | dimension_on_F_Cu | dimension on copper seen | port | diff_cases `r11_dimension_on_F_Cu` |
| r11 diff11 | target_on_F_Cu | target on copper seen | port | diff_cases `r11_target_on_F_Cu` |
| r11 diff11 | reference_text_on_F_Cu | reference moved to F.Cu seen | port | diff_cases `r11_reference_text_on_F_Cu` |
| r11 diff11 | gr_rect_on_F_Cu (control) | copper rect seen | port | diff_cases `r11_gr_rect_on_F_Cu` |
| r11 diff11 | pad_thermal_spoke_angle_90 | pad spoke angle seen | port | diff_cases `r11_pad_thermal_spoke_angle_90` |
| r11 diff11 | gr_text_minimal_on_cu | re-save identical | port | diff_cases `r11_gr_text_minimal_on_cu` |
| r11 diff11 | gr_poly_old_fill_solid | re-save identical | port | diff_cases `r11_gr_poly_old_fill_solid` |
| r11 diff11 | gr_line_on_cu_width_only | re-save identical | port | diff_cases `r11_gr_line_on_cu_width_only` |
| r11 diff11 | gr_circle_on_cu_child_order | re-save identical | port | diff_cases `r11_gr_circle_on_cu_child_order` |
| r11 diff11 | zone_priority0_name_empty | re-save identical | port | diff_cases `r11_zone_priority0_name_empty` |
| r11 diff11 | zone_connect_pads_yes | re-save identical | port | diff_cases `r11_zone_connect_pads_yes` |
| r11 diff11 | zone_filled_areas_thickness_no | re-save identical | port | diff_cases `r11_zone_filled_areas_thickness_no` |
| r11 diff11 | zone_hatch_fill_mode | re-save identical | port | diff_cases `r11_zone_hatch_fill_mode` |
| r11 diff11 | zone_no_hatch_no_fill | re-save identical | port | diff_cases `r11_zone_no_hatch_no_fill` |
| r11 diff11 | zone_clockwise_start_other_corner | re-save identical | port | diff_cases `r11_zone_clockwise_start_other_corner` |
| r11 diff11 | zone_keepout_full | re-save identical | port | diff_cases `r11_zone_keepout_full` |
| r11 diff11 | pad_thermal_hand | re-save identical | port | diff_cases `r11_pad_thermal_hand` |
| r11 diff11 | fp_zone_hand | re-save identical | port | diff_cases `r11_fp_zone_hand` |
| r11 diff11 | fp_text_on_cu | re-save identical | port | diff_cases `r11_fp_text_on_cu` |
| r11 diff11 | fp_poly_on_cu | re-save identical | port | diff_cases `r11_fp_poly_on_cu` |
| r12 gate12 | collide_marker_ids | items already holding marker ids: 3 runs, one file, fills, uuids kept, no marker left, no line removed | port | edit_cases `r12_collide_marker_ids` |
| r12 gate12 | collide_marker_ids_unfilled | the same never filled, zone uuids stripped | port | edit_cases `r12_collide_marker_ids_unfilled` |
| r12 gate12 | dup_uuid_all_zones | every zone shares one uuid | port | edit_cases `r12_dup_uuid_all_zones` |
| r12 gate12 | zones_in_group | zones in a group | port | edit_cases `r12_zones_in_group` |
| r12 gate12 | fp_zone_moved | footprint zone moved by the edit (no line check) | port | edit_cases `r12_fp_zone_moved` |
| r12 gate12 | zone_uuid_is_marker | zone uuids equal to other markers | port | edit_cases `r12_zone_uuid_is_marker` |
| r12 gate12 | zone_without_polygon | zone with no outline refused, "has no outline" | port | edit_cases `r12_zone_without_polygon` |
| r12 gate12 | pasted_fp_same_uuids | footprint pasted twice, one zone's clearance changed | port | edit_cases `r12_pasted_fp_same_uuids` |
| r12 diff12 | gr_text_font_size | seen | port | diff_cases `r12_gr_text_font_size` |
| r12 diff12 | gr_text_thickness | seen | port | diff_cases `r12_gr_text_thickness` |
| r12 diff12 | gr_text_knockout | seen | port | diff_cases `r12_gr_text_knockout` |
| r12 diff12 | gr_text_mirror_justify | seen | port | diff_cases `r12_gr_text_mirror_justify` |
| r12 diff12 | gr_text_bold | seen | port | diff_cases `r12_gr_text_bold` |
| r12 diff12 | gr_poly_arc_mid_moved | seen | port | diff_cases `r12_gr_poly_arc_mid_moved` |
| r12 diff12 | gr_poly_fill_hatch | seen | port | diff_cases `r12_gr_poly_fill_hatch` |
| r12 diff12 | fp_line_cu_width | seen | port | diff_cases `r12_fp_line_cu_width` |
| r12 diff12 | fp_poly_cu_fill | seen | port | diff_cases `r12_fp_poly_cu_fill` |
| r12 diff12 | fp_poly_cu_arc_mid | seen | port | diff_cases `r12_fp_poly_cu_arc_mid` |
| r12 diff12 | fp_text_cu_moved | seen | port | diff_cases `r12_fp_text_cu_moved` |
| r12 diff12 | fp_text_cu_text | seen | port | diff_cases `r12_fp_text_cu_text` |
| r12 diff12 | fp_text_cu_size | seen | port | diff_cases `r12_fp_text_cu_size` |
| r12 diff12 | fp_property_cu_moved | seen | port | diff_cases `r12_fp_property_cu_moved` |
| r12 diff12 | fp_rect_cu_fill | seen | port | diff_cases `r12_fp_rect_cu_fill` |
| r12 diff12 | fp_attr_zone_connect | seen | port | diff_cases `r12_fp_attr_zone_connect` |
| r12 diff12 | gr_text_moved (control) | seen | port | diff_cases `r12_gr_text_moved` |
| r12 diff12 | fp_line_cu_moved (control) | seen | port | diff_cases `r12_fp_line_cu_moved` |
| r12 diff12 | zone_hole_moved | seen | port | diff_cases `r12_zone_hole_moved` |
| r12 diff12 | zone_hole_removed | seen | port | diff_cases `r12_zone_hole_removed` |
| r12 diff12 | n5_value_to_B_Cu | Value moved to B.Cu seen | port | diff_cases `r12_n5_value_to_B_Cu` |
| r12 diff12 | n5_pad_clearance | pad clearance seen | port | diff_cases `r12_n5_pad_clearance` |
| r12 diff12 | gr_poly_no_stroke | re-save identical | port | diff_cases `r12_resave_gr_poly_no_stroke` |
| r12 diff12 | gr_rect_fill_none | re-save identical | port | diff_cases `r12_resave_gr_rect_fill_none` |
| r12 diff12 | gr_arc_on_cu | re-save identical | port | diff_cases `r12_resave_gr_arc_on_cu` |
| r12 diff12 | gr_text_no_angle | re-save identical | port | diff_cases `r12_resave_gr_text_no_angle` |
| r12 diff12 | gr_poly_with_arc | re-save identical | port | diff_cases `r12_resave_gr_poly_with_arc` |
| r12 diff12 | target_on_cu | re-save identical | port | diff_cases `r12_resave_target_on_cu` |
| r12 diff12 | dimension_on_cu | re-save identical | port | diff_cases `r12_resave_dimension_on_cu` |
| r12 diff12 | fp_line_cu_width_only | re-save identical | port | diff_cases `r12_resave_fp_line_cu_width_only` |
| r12 diff12 | fp_zone_connect_attr | re-save identical | port | diff_cases `r12_resave_fp_zone_connect_attr` |
| r12 diff12 | gr_text_knockout (resave) | re-save identical | port | diff_cases `r12_resave_gr_text_knockout` |
| r12 diff12 | zone_with_hole | re-save identical | port | diff_cases `r12_resave_zone_with_hole` |
| r12 diff12 | n4_zone_prio0_name_empty_2layer | re-save identical | port | diff_cases `r12_resave_n4_zone_prio0_name_empty_2layer` |
| r12 diff12 | n4_rule_area_net_empty | re-save identical | port | diff_cases `r12_resave_n4_rule_area_net_empty` |
| r12 diff12 | n4_hatch_zone | re-save identical | port | diff_cases `r12_resave_n4_hatch_zone` |
| r12 diff12 | n4_gr_line_width_b | re-save identical | port | diff_cases `r12_resave_n4_gr_line_width_b` |
| r12 diff12 | n4_pad_numbers_text | re-save identical | port | diff_cases `r12_resave_n4_pad_numbers_text` |
| r12 prewire12 | two_stubs_one_pad: stub 1 kept | of two stubs at pad L2, the one the router never joined is kept | port | route_cases `r12_two_stubs_one_pad` |
| r12 prewire12 | anchor_zone_outside_hole | stub anchored in a zone outside its hole: done | port | route_cases `r12_anchor_zone_outside_hole` |
| r12 prewire12 | anchor_zone_in_hole | stub anchored in the zone's hole: refused | port | route_cases `r12_anchor_zone_in_hole` |
| r12 prewire12 | join_inner_corner_3seg | router joins a 3-segment stub's inner corner: done | port | route_cases `r12_join_inner_corner_3seg` |
| r12 prewire12 | one_stub_control | stub alone, router joins the pad: rejected | port | route_cases `r12_one_stub_control` |

## Counts

| label | r08 | r09 | r10 | r11 | r12 | total |
| --- | --- | --- | --- | --- | --- | --- |
| covered | 3 | 4 | 5 | 1 | 0 | 13 |
| port | 44 | 45 | 46 | 32 | 51 | 218 |
| evidence | 0 | 1 | 0 | 0 | 0 | 1 |
| verdicts | 47 | 50 | 51 | 33 | 51 | 232 |

The 218 ported cases are split across the files as follows:

| file | ported cases |
| --- | --- |
| `edit_cases.py` | 69 |
| `diff_cases.py` | 99 |
| `contract_cases.py` | 11 |
| `route_cases.py` | 32 |
| `tests/mutations/edit_mutations.py` | 7 |

Review 8's mutations damage two inputs that are not verdicts of their own: `r08_move_via_by_position` and `r08_delete_via_by_uuid` in `edit_cases.py`. The probe required both edits to be done.

The gate cases run twice, not three times. The second run checks that the file is the same bytes; the reviewers' third run repeated that check. `r12_zone_without_polygon` runs once.

`run_m1` in `edit_cases.py` builds each board once and copies it to the cases that use it, and so does `run_m1` in `route_cases.py`.
