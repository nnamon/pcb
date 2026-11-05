"""Cases for `pcb edit` on the synthetic base board (tests/lib/synth_board.py): each operation, each refusal, and
the gate's verdict. Every written result is checked by tests/oracles/verify_edit.py; the input must never change.

Board landmarks (mm): pads N1 (20,15) and N2 (40,15) on N, unrouted; W tracks along y=10 from x=15 to 55 (0.4 mm
from 15 to 38); L: locked stub (15,20)-(20,20), locked via at (20,20), locked B.Cu tail to (20,24); S track from
(3,30) to (45,30). Pads are 1 mm squares on F.Cu.

Usage: python3 edit_cases.py pcb-binary workdir
"""
import hashlib
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)
# name: (operations, outcome, error code or words, extra check)
CASES = {
    "join_n": ([T("N", "F.Cu", 0.2, (20, 15), (40, 15))], "done", None, "fixes unconnected N"),
    "join_n_through_vias": ([T("N", "F.Cu", 0.2, (20, 15), (30, 15)), dict(op="add_via", net="N", at=[30, 15], size=0.6, drill=0.3),
                             T("N", "B.Cu", 0.2, (30, 15), (35, 15)), dict(op="add_via", net="N", at=[35, 15], size=0.6, drill=0.3),
                             T("N", "F.Cu", 0.2, (35, 15), (40, 15))], "done", None, "fixes unconnected N"),
    "short_rejected": ([T("N", "F.Cu", 0.2, (20, 15), (20, 8), (40, 8), (40, 15))], "rejected", None, None),
    "unjoined_end_refused": ([T("N", "F.Cu", 0.2, (20, 15), (30, 20))], "refused", "edit-unjoined", None),
    "free_end_allowed": ([T("N", "F.Cu", 0.2, (20, 15), (25, 17), free_end=True)], "rejected", None, "dangling end is a DRC regression"),
    "unjoined_via_refused": ([dict(op="add_via", net="N", at=[30, 25], size=0.6, drill=0.3)], "refused", "edit-unjoined", None),
    "locked_via_refused": ([dict(op="move_via", net="L", at=[20, 20], to=[21, 21])], "refused", "edit-locked", None),
    "unlocked_move_breaks_net_rejected": ([dict(op="move_via", net="L", at=[20, 20], to=[22, 26], unlock=True)], "refused", "edit-unjoined", None),
    "wrong_net_refused": ([dict(op="move_via", net="GND", at=[20, 20], to=[21, 21])], "refused", "edit-mismatch", None),
    "no_target_refused": ([dict(op="delete", what="via", net="N", at=[1, 1])], "refused", "edit-no-target", None),
    "set_width": ([dict(op="set_width", net="W", layer="F.Cu", start=[15, 10], end=[30, 10], from_=0.4, to=0.5)], "done", None, None),
    "set_width_wrong_from_refused": ([dict(op="set_width", net="W", layer="F.Cu", start=[15, 10], end=[30, 10], from_=0.3, to=0.5)], "refused", "edit-mismatch", None),
    "delete_breaks_net_rejected": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30])], "rejected", None, None),
    "move_footprint": ([dict(op="move_footprint", ref="N2", **{"from": [40, 15]}, to=[40, 16])], "done", None, None),
    "move_footprint_wrong_from_refused": ([dict(op="move_footprint", ref="N2", **{"from": [41, 15]}, to=[40, 16])], "refused", "edit-mismatch", None),
    "unknown_net_refused": ([T("NOPE", "F.Cu", 0.2, (20, 15), (40, 15))], "refused", "unknown-net", None),
    "bad_layer_refused": ([T("N", "In1.Cu", 0.2, (20, 15), (40, 15))], "refused", "bad-layer", None),
    "off_board_refused": ([T("N", "F.Cu", 0.2, (20, 15), (90, 15))], "refused", "edit-op", None),
    "same_item_twice_refused": ([dict(op="set_width", net="W", layer="F.Cu", start=[15, 10], end=[30, 10], from_=0.4, to=0.5),
                                 dict(op="delete", what="track", net="W", layer="F.Cu", start=[15, 10], end=[30, 10])], "refused", "edit-op", None),
    # two S tracks along the same line (variant dup): a position names both, so delete must say which or take all
    "duplicate_named_by_position_refused": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30])], "refused", "edit-no-target", None),
    "duplicate_delete_all_and_readd": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], all=True),
                                        T("S", "F.Cu", 0.2, (3, 30), (45, 30))], "done", None, None),
    "duplicate_delete_all_breaks_net_rejected": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], all=True)], "rejected", None, None),
    # a board with a zone: the gate fills a copy and carries back only the fills (review 8, 3); checked by verify_edit
    # and run twice, byte for byte the same
    "zoned_join_n": ([T("N", "F.Cu", 0.2, (20, 15), (40, 15))], "done", None, "twice"),
    # new copper joined only to itself floats (review 8, 13)
    "self_loop_refused": ([T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5), (25, 26.5))], "refused", "edit-unjoined", None),
    "floating_pair_refused": ([T("N", "F.Cu", 0.2, (25, 26), (28, 26), free_start=False), dict(op="add_via", net="N", at=[25, 26], size=0.6, drill=0.3)], "refused", "edit-unjoined", None),
    # a uuid and a contradicting position (review 8, 5), and a field that does not apply
    "delete_via_at_for_track_refused": ([dict(op="delete", what="track", net="S", layer="F.Cu", start=[3, 30], end=[45, 30], at=[3, 30])], "refused", "edit-op", None),
    "unknown_field_refused": ([dict(op="add_via", net="N", at=[30, 15], size=0.6, drill=0.3, sise=1)], "refused", "edit-op", None),
}


# boards other than the base variant
VARIANT = {"zoned_join_n": "gzone", "duplicate_named_by_position_refused": "dup", "duplicate_delete_all_and_readd": "dup", "duplicate_delete_all_breaks_net_rejected": "dup"}


def gate_zone_spec(variant=None):
    """Review 9's zone board (80 x 50 mm): Z1 GND F.Cu left, Z2 GND F.Cu right (same net and layer), Z3 GND on F.Cu and
    B.Cu, Z4 VCC B.Cu with no pad of its net (fills to nothing), K1 a rule area, Z5 VCC F.Cu, and a footprint FZ1
    holding a rule area and a GND copper zone. Variant n34 adds through-hole N pads N3 (52,28) and N4 (69,28)."""
    tht = lambda ref, x, y, net: {"ref": ref, "at": (x, y), "pads": [{"num": "1", "at": (x, y), "kind": "tht", "drill": 0.6, "net": net}]}
    smd = lambda ref, x, y, net: {"ref": ref, "at": (x, y), "pads": [{"num": "1", "at": (x, y), "net": net}]}
    fps = [tht("G1", 10, 10, "GND"), tht("G2", 60, 10, "GND"), tht("G3", 40, 40, "GND"), smd("V1", 70, 40, "VCC"), smd("N1", 20, 25, "N"),
           smd("N2", 50, 25, "N"), smd("S1", 5, 45, "S")]
    if variant == "n34":
        fps += [tht("N3", 52, 28, "N"), tht("N4", 69, 28, "N")]
    fps += [smd("S2", 30, 45, "S"), tht("FZ1", 60, 28, "GND")]
    return {"edge": (0, 0, 80, 50), "nets": ["GND", "VCC", "N", "S"], "fps": fps, "tracks": [(5, 45, 30, 45, "S", 0.2, "F.Cu")],
            "zones": [{"net": "GND", "layers": ["F.Cu"], "rect": (2, 2, 38, 20)}, {"net": "GND", "layers": ["F.Cu"], "rect": (42, 2, 78, 20)},
                      {"net": "GND", "layers": ["F.Cu", "B.Cu"], "rect": (30, 35, 50, 48)}, {"net": "VCC", "layers": ["B.Cu"], "rect": (2, 22, 20, 33)},
                      {"keepout": True, "layers": ["F.Cu", "B.Cu"], "rect": (25, 5, 30, 15)}, {"net": "VCC", "layers": ["F.Cu"], "rect": (62, 33, 78, 48)},
                      {"keepout": True, "layers": ["F.Cu"], "rect": (55, 22, 58, 26), "parent": "FZ1"},
                      {"net": "GND", "layers": ["B.Cu"], "rect": (56, 24, 66, 32), "parent": "FZ1"}]}


def strip_zone_uuids(p):
    """Removes zone uuids, as a hand-written or generated board may lack them: then the save's order is all there is."""
    import re
    t = open(p).read()
    out, i = [], 0
    for m in re.finditer(r"\(zone\b", t):
        if m.start() < i:
            continue
        depth, j = 0, m.start()
        while True:
            c = t[j]
            if c == '"':
                j = t.index('"', j + 1)
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(t[i:m.start()])
        out.append(re.sub(r"\n[ \t]*\(uuid \"[^\"]*\"\)", "", t[m.start():j + 1]))
        i = j + 1
    out.append(t[i:])
    open(p, "w").write("".join(out))


ADD_N = [T("N", "F.Cu", 0.2, (20, 25), (50, 25))]
ADD_N34 = [T("N", "B.Cu", 0.2, (52, 28), (54, 31), (67, 31), (69, 28))]
# name, board variant, zone uuids stripped, operations
GATE_ZONE_CASES = [
    # source: review 9, uuids
    ("gate_zones_uuids", None, False, ADD_N),
    # source: review 9, no_uuids
    ("gate_zones_no_uuids", None, True, ADD_N),
    # source: review 9, footprint_zone (finding 2: a track across a footprint's own GND zone is not rejected on a stale
    # footprint fill)
    ("gate_zones_footprint_zone", "n34", False, ADD_N34),
]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def ops_json(ops):
    # "from" is a Python keyword: written from_ above
    return [{("from" if k == "from_" else k): v for k, v in o.items()} for o in ops]


# ---- Reviews 8 to 12 (M1), moved from tests/regressions@e17bfac/r08 to r12; see docs/reviews/audit/AUDIT_m1.md ----
# Each case: board (("synth", variant, text appended before the board's last paren) or ("gate", variant) from
# tests/lib/gate_board.py), ops, want ("done", "rejected", "refused", "pass" = done or rejected, "not_unjoined" = not
# refused as edit-unjoined), and optional code, words (in the error message), oracle (verify_edit on the written
# file), runs (2: the second run must give the same bytes; the reviewers ran 3, the third repeating that check),
# check ("gate": every run done, one file over all runs, each fill pcbnew's own;
# "identity": also the zone uuids kept, no marker uuid left, no line outside fills removed; "markers": "identity"
# without the line check; "fp_pcbnew": the moved footprint where pcbnew's own move puts it).
DT = lambda net, layer, s, e, **kw: dict(op="delete", what="track", net=net, layer=layer, start=list(s), end=list(e), **kw)
SW = lambda net, layer, s, e, f, t, **kw: dict(op="set_width", net=net, layer=layer, start=list(s), end=list(e), from_=f, to=t, **kw)
V = lambda net, at, **kw: dict(op="add_via", net=net, at=list(at), size=0.6, drill=0.3, **kw)
UUID_ITEMS = ('\t(via (at 50 30) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net "GND") (uuid "aaaaaaaa-0000-4000-8000-000000000001"))\n'
              '\t(segment (start 50 33) (end 55 33) (width 0.2) (layer "F.Cu") (net "GND") (uuid "bbbbbbbb-0000-4000-8000-000000000002"))\n')
GND_B_TRACK = '\t(segment (start 40 33) (end 45 33) (width 0.3) (layer "B.Cu") (net "GND") (uuid "cccccccc-0000-4000-8000-000000000003"))\n'
BASE, DUP, ARC, GZ = ("synth", "base", ""), ("synth", "dup", ""), ("synth", "arc", ""), ("synth", "gzone", "")
UU = ("synth", "base", UUID_ITEMS)
ADD_S = [T("S", "F.Cu", 0.2, (5, 45), (30, 45))]
G_TRACK = [T("GND", "F.Cu", 0.25, (15, 15), (30, 20))]
G_VIA = [V("GND", (20, 20))]
GATE3 = dict(want="done", runs=2, check="gate")
ID3 = dict(want="done", runs=2, check="identity")
M1_CASES = {
    # review 8, 13: floating new copper
    "r08_floating_triangle_refused": dict(board=BASE, ops=[T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5)), T("N", "F.Cu", 0.2, (28, 26.5), (28, 28), (25, 26.5))], want="refused", code="edit-unjoined"),  # source: review 8, floating_triangle_refused
    "r08_stacked_floating_vias_refused": dict(board=BASE, ops=[dict(op="add_via", net="N", at=[25, 27], size=0.6, drill=0.3), dict(op="add_via", net="N", at=[25, 27], size=0.6, drill=0.3)], want="refused"),  # source: review 8, stacked_floating_vias_refused
    "r08_free_end_other_end_checked": dict(board=BASE, ops=[T("N", "F.Cu", 0.2, (25, 26.5), (28, 26.5), free_end=True)], want="refused", code="edit-unjoined"),  # source: review 8, free_end_other_end_checked
    # review 8, 5: a uuid and a position that disagree
    "r08_via_uuid_and_wrong_at_refused": dict(board=UU, ops=[dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001", at=[5, 5])], want="refused"),  # source: review 8, via_uuid_and_wrong_at_refused
    "r08_track_uuid_and_wrong_ends_refused": dict(board=UU, ops=[dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", layer="B.Cu", start=[1, 1], end=[2, 2])], want="refused"),  # source: review 8, track_uuid_and_wrong_ends_refused
    "r08_same_item_by_uuid_and_position_refused": dict(board=UU, ops=[dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001"), dict(op="move_via", net="GND", at=[50, 30], to=[50, 31], unlock=True)], want="refused", code="edit-op"),  # source: review 8, same_item_by_uuid_and_position_refused
    # review 8, 14: track arcs are copper for joins
    "r08_end_on_arc_counts_as_joined": dict(board=ARC, ops=[T("N", "F.Cu", 0.2, (30, 13), (30, 9.5), free_end=True)], want="not_unjoined"),  # source: review 8, end_on_arc_counts_as_joined
    # the results review 8's verify_edit mutations damage (tests/mutations/edit_mutations.py); the probe required done
    "r08_move_via_by_position": dict(board=UU, ops=[dict(op="move_via", net="GND", at=[50, 30], to=[52, 33])], want="done", oracle=True),  # source: review 8, verify_edit_mutations case move_via
    "r08_delete_via_by_uuid": dict(board=UU, ops=[dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001")], want="done", oracle=True),  # source: review 8, verify_edit_mutations case delete_uuid
    "r08_locked_set_width_refused": dict(board=BASE, ops=[SW("L", "F.Cu", (15, 20), (20, 20), 0.2, 0.25)], want="refused", code="edit-locked"),  # source: review 8, locked_set_width_refused
    # review 8: move_footprint against pcbnew's own move (a turned, flipped footprint with a graphic and a rule area)
    "r08_move_footprint_matches_pcbnew": dict(board=("gate", "fp_rotated"), ops=[dict(op="move_footprint", ref="R5", from_=[30, 20], to=[33, 21.5])], want="any", check="fp_pcbnew"),  # source: review 8, move_fp_vs_pcbnew
    # review 9, check 4: legitimate edits the join rule must not refuse
    "r09_set_width_all_of_chain": dict(board=BASE, ops=[SW("W", "F.Cu", (15, 10), (30, 10), 0.4, 0.35), SW("W", "F.Cu", (30, 10), (38, 10), 0.4, 0.35), SW("W", "F.Cu", (38, 10), (45, 10), 0.25, 0.35)], want="pass", oracle=True),  # source: review 9, set_width_all_of_chain
    "r09_set_width_middle_only": dict(board=BASE, ops=[SW("W", "F.Cu", (30, 10), (38, 10), 0.4, 0.3)], want="pass", oracle=True),  # source: review 9, set_width_middle_only
    "r09_move_via_small_unlock": dict(board=BASE, ops=[dict(op="move_via", net="L", at=[20, 20], to=[20, 20.05], unlock=True)], want="pass", oracle=True),  # source: review 9, move_via_small_unlock
    "r09_move_via_relay_tracks": dict(board=BASE, ops=[dict(op="move_via", net="L", at=[20, 20], to=[21, 21], unlock=True), DT("L", "F.Cu", (15, 20), (20, 20), unlock=True), DT("L", "F.Cu", (20, 20), (45, 20)), DT("L", "B.Cu", (20, 20), (20, 24), unlock=True),
                                                    T("L", "F.Cu", 0.2, (15, 20), (21, 21)), T("L", "F.Cu", 0.2, (21, 21), (45, 20)), T("L", "B.Cu", 0.2, (21, 21), (20, 24))], want="pass", oracle=True),  # source: review 9, move_via_relay_tracks
    "r09_delete_all_dup_readd_two_segments": dict(board=DUP, ops=[DT("S", "F.Cu", (3, 30), (45, 30), all=True), T("S", "F.Cu", 0.2, (3, 30), (24, 30), (45, 30))], want="pass", oracle=True),  # source: review 9, delete_all_dup_readd_two_segments
    "r09_move_fp_with_track": dict(board=BASE, ops=[dict(op="move_footprint", ref="N1", from_=[20, 15], to=[20, 16]), T("N", "F.Cu", 0.2, (20, 16), (40, 15))], want="pass", oracle=True),  # source: review 9, move_fp_with_track
    "r09_move_fp_and_relay_its_track": dict(board=BASE, ops=[dict(op="move_footprint", ref="W1", from_=[15, 10], to=[15, 11]), DT("W", "F.Cu", (15, 10), (30, 10)), T("W", "F.Cu", 0.4, (15, 11), (30, 10))], want="pass", oracle=True),  # source: review 9, move_fp_and_relay_its_track
    "r09_move_stitching_via": dict(board=GZ, ops=[dict(op="move_via", net="GND", at=[5, 37], to=[6, 37])], want="pass"),  # source: review 9, move_stitching_via
    "r09_set_width_zone_fed_track": dict(board=("synth", "gzone", GND_B_TRACK), ops=[SW("GND", "B.Cu", (40, 33), (45, 33), 0.3, 0.4)], want="pass"),  # source: review 9, set_width_zone_fed_track
    # review 9, check 4: floating copper the rule must refuse
    "r09_floating_square_loop": dict(board=BASE, ops=[T("N", "F.Cu", 0.2, (25, 25), (28, 25), (28, 28), (25, 28), (25, 25))], want="refused", code="edit-unjoined"),  # source: review 9, floating_square_loop
    "r09_floating_track_between_new_vias": dict(board=BASE, ops=[V("N", (25, 25)), V("N", (28, 25)), T("N", "F.Cu", 0.2, (25, 25), (28, 25))], want="refused", code="edit-unjoined"),  # source: review 9, floating_track_between_new_vias
    "r09_floating_b_side_pair": dict(board=BASE, ops=[T("N", "B.Cu", 0.2, (25, 25), (28, 25)), T("N", "B.Cu", 0.2, (28, 25), (25, 25.0001))], want="refused", code="edit-unjoined"),  # source: review 9, floating_b_side_pair
    "r09_moved_via_onto_floating_new_track": dict(board=BASE, ops=[dict(op="move_via", net="L", at=[20, 20], to=[25, 25], unlock=True), T("L", "F.Cu", 0.2, (25, 25), (27, 25), (25, 25.0))], want="refused", code="edit-unjoined"),  # source: review 9, moved_via_onto_floating_new_track
    "r09_end_over_other_layer_track": dict(board=BASE, ops=[T("L", "F.Cu", 0.2, (45, 20), (45, 24), (25, 24))], want="refused", code="edit-unjoined"),  # source: review 9, end_over_other_layer_track
    # review 8, 5 (review 9's probes): fields that do not apply, uuids against positions
    "r09_delete_via_with_layer": dict(board=BASE, ops=[dict(op="delete", what="via", net="L", at=[20, 20], layer="F.Cu", unlock=True)], want="refused", code="edit-op"),  # source: review 9, delete_via_with_layer
    "r09_delete_track_uuid_only_start": dict(board=BASE, ops=[dict(op="delete", what="track", net="S", start=[3, 30])], want="refused", code="edit-op"),  # source: review 9, delete_track_uuid_only_start
    "r09_delete_track_uuid_right_ends_reversed": dict(board=UU, ops=[dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", layer="F.Cu", start=[55, 33], end=[50, 33])], want="pass", oracle=True),  # source: review 9, delete_track_uuid_right_ends_reversed
    "r09_delete_track_uuid_wrong_layer_only": dict(board=UU, ops=[dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", layer="B.Cu")], want="refused", code="edit-mismatch"),  # source: review 9, delete_track_uuid_wrong_layer_only
    "r09_delete_track_uuid_start_only": dict(board=UU, ops=[dict(op="delete", what="track", net="GND", uuid="bbbbbbbb-0000-4000-8000-000000000002", start=[50, 33])], want="refused", code="edit-mismatch"),  # source: review 9, delete_track_uuid_start_only
    "r09_delete_via_uuid_wrong_net": dict(board=UU, ops=[dict(op="delete", what="via", net="S", uuid="aaaaaaaa-0000-4000-8000-000000000001")], want="refused", code="edit-mismatch"),  # source: review 9, delete_via_uuid_wrong_net
    "r09_delete_via_uuid_right_at": dict(board=UU, ops=[dict(op="delete", what="via", net="GND", uuid="aaaaaaaa-0000-4000-8000-000000000001", at=[50, 30])], want="pass", oracle=True),  # source: review 9, delete_via_uuid_right_at
    # review 8, 14 (review 9's probes): arcs
    "r09_track_from_arc_mid_to_pad": dict(board=ARC, ops=[T("N", "F.Cu", 0.2, (30, 13), (40, 15))], want="pass"),  # source: review 9, track_from_arc_mid_to_pad
    "r09_track_near_arc_chord_not_arc": dict(board=ARC, ops=[T("N", "F.Cu", 0.2, (30, 15), (30, 18), free_end=True)], want="refused", code="edit-unjoined"),  # source: review 9, track_near_arc_chord_not_arc
    # review 10: the gate's fill carry-back on zones a key cannot tell apart; three runs, one file, pcbnew's fills
    "r10_dup_no_uuid": dict(board=("gate", "dup_no_uuid"), ops=ADD_S, **GATE3),  # source: review 10, dup_no_uuid
    "r10_dup_uuid": dict(board=("gate", "dup_uuid"), ops=ADD_S, **GATE3),  # source: review 10, dup_uuid
    "r10_second_poly_no_uuid": dict(board=("gate", "second_poly_no_uuid"), ops=ADD_S, **GATE3),  # source: review 10, second_poly_no_uuid
    "r10_same_ref_no_uuid": dict(board=("gate", "same_ref_no_uuid"), ops=ADD_S, **GATE3),  # source: review 10, same_ref_no_uuid
    "r10_same_ref_dup_zone_uuid": dict(board=("gate", "same_ref_dup_zone_uuid"), ops=ADD_S, **GATE3),  # source: review 10, same_ref_dup_zone_uuid
    "r10_top_dup_uuid": dict(board=("gate", "top_dup_uuid"), ops=ADD_S, **GATE3),  # source: review 10, top_dup_uuid
    "r10_move_fp_zone_no_uuid": dict(board=("gate", "move_fz"), ops=[dict(op="move_footprint", ref="FZ1", from_=[20, 25], to=[33.3333333, 25.1234567])], **GATE3),  # source: review 10, move_fp_zone_no_uuid
    "r10_move_fp_zone_no_uuid_half": dict(board=("gate", "move_fz"), ops=[dict(op="move_footprint", ref="FZ1", from_=[20, 25], to=[33.00005, 25.00005])], **GATE3),  # source: review 10, move_fp_zone_no_uuid_half
    "r10_keepouts_no_uuid": dict(board=("gate", "keepouts_no_uuid"), ops=ADD_S, **GATE3),  # source: review 10, keepouts_no_uuid
    "r10_repeated_point_no_uuid": dict(board=("gate", "repeated_point_no_uuid"), ops=ADD_S, **GATE3),  # source: review 10, repeated_point_no_uuid
    "r10_zone_layers_reversed_no_uuid": dict(board=("gate", "layers_reversed_no_uuid"), ops=ADD_S, want="done"),  # source: review 10, zone_layers_reversed_no_uuid
    "r10_via_in_filled_footprint_zone": dict(board=("gate", "fpzone_islands"), ops=[V("GND", (15, 20))], want="rejected"),  # source: review 10, via_in_filled_footprint_zone
    # review 10: joins through never-filled, stale or empty fills; the gate judges what the join rule lets through
    "r10_no_zone_track": dict(board=("gate", "join_nozone"), ops=G_TRACK, want="refused"),  # source: review 10, no_zone_track
    "r10_never_filled_track": dict(board=("gate", "join_zone"), ops=G_TRACK, want="rejected"),  # source: review 10, never_filled_track
    "r10_never_filled_via": dict(board=("gate", "join_zone"), ops=G_VIA, want="rejected"),  # source: review 10, never_filled_via
    "r10_stale_fill_track": dict(board=("gate", "join_stale"), ops=G_TRACK, want="rejected"),  # source: review 10, stale_fill_track
    "r10_stale_fill_via": dict(board=("gate", "join_stale"), ops=G_VIA, want="rejected"),  # source: review 10, stale_fill_via
    "r10_islands_kept_never_filled_track": dict(board=("gate", "join_islands"), ops=G_TRACK, want="rejected"),  # source: review 10, islands_kept_never_filled_track
    "r10_fp_zone_never_filled_via": dict(board=("gate", "join_fpzone"), ops=G_VIA, want="rejected"),  # source: review 10, fp_zone_never_filled_via
    "r10_track_on_B_under_F_zone": dict(board=("gate", "join_zone"), ops=[T("GND", "B.Cu", 0.25, (15, 15), (30, 20))], want="refused"),  # source: review 10, track_on_B_under_F_zone
    # review 10's reproductions of review 9, 3 and 7: copper fed only through a filled B.Cu pour
    "r10_move_stitching_via": dict(board=("gate", "stitch"), ops=[dict(op="move_via", net="GND", at=[20, 25], to=[22, 26])], want="done"),  # source: review 10, move_stitching_via
    "r10_move_feed_via": dict(board=("gate", "stitch"), ops=[dict(op="move_via", net="GND", at=[30, 14], to=[31, 14])], want="rejected"),  # source: review 10, move_feed_via
    "r10_set_width_fill_fed_track": dict(board=("gate", "stitch"), ops=[SW("GND", "B.Cu", (25, 30), (35, 30), 0.3, 0.5)], want="done"),  # source: review 10, set_width_fill_fed_track
    "r10_move_stitching_via_out_of_pour": dict(board=("gate", "stitch"), ops=[dict(op="move_via", net="GND", at=[20, 25], to=[55, 45])], want="refused"),  # source: review 10, move_stitching_via_out_of_pour
    # review 11: the gate's markers on never-filled, hand-written and copied zones
    "r11_dup_no_uuid_unfilled": dict(board=("gate", "dup_unfilled"), ops=ADD_S, **GATE3),  # source: review 11, dup_no_uuid_unfilled
    "r11_dup_no_uuid_handtext": dict(board=("gate", "dup_handtext"), ops=ADD_S, **GATE3),  # source: review 11, dup_no_uuid_handtext
    "r11_same_ref_same_pos": dict(board=("gate", "same_ref_same_pos"), ops=ADD_S, **GATE3),  # source: review 11, same_ref_same_pos
    "r11_move_fp_no_uuid": dict(board=("gate", "two_fz_no_uuid"), ops=[dict(op="move_footprint", ref="FZ2", from_=[55.0, 25.0], to=[55.0 - 1.23457, 25.0 + 0.00005])] + ADD_S, **GATE3),  # source: review 11, move_fp_no_uuid
    "r11_move_fp_no_uuid_2": dict(board=("gate", "two_fz_no_uuid"), ops=[dict(op="move_footprint", ref="FZ1", from_=[15.0, 25.0], to=[55.0, 25.0]), dict(op="move_footprint", ref="FZ2", from_=[55.0, 25.0], to=[15.0, 25.0])] + ADD_S, **GATE3),  # source: review 11, move_fp_no_uuid_2
    # review 12: markers against colliding ids, shared uuids, groups and pasted footprints; no marker reaches the file
    "r12_collide_marker_ids": dict(board=("gate", "r12_collide"), ops=ADD_S, **ID3),  # source: review 12, collide_marker_ids
    "r12_collide_marker_ids_unfilled": dict(board=("gate", "r12_collide_unfilled"), ops=ADD_S, **ID3),  # source: review 12, collide_marker_ids_unfilled
    "r12_dup_uuid_all_zones": dict(board=("gate", "r12_dupuuid"), ops=ADD_S, **ID3),  # source: review 12, dup_uuid_all_zones
    "r12_zones_in_group": dict(board=("gate", "r12_group"), ops=ADD_S, **ID3),  # source: review 12, zones_in_group
    "r12_fp_zone_moved": dict(board=("gate", "r12_fpmove"), ops=[dict(op="move_footprint", ref="FZ", from_=[60, 30], to=[58.5, 31.25])] + ADD_S, want="done", runs=2, check="markers"),  # source: review 12, fp_zone_moved
    "r12_zone_uuid_is_marker": dict(board=("gate", "r12_zone_has_marker"), ops=ADD_S, **ID3),  # source: review 12, zone_uuid_is_marker
    "r12_zone_without_polygon": dict(board=("gate", "r12_emptyzone"), ops=ADD_S, want="refused", words="has no outline"),  # source: review 12, zone_without_polygon
    "r12_pasted_fp_same_uuids": dict(board=("gate", "r12_pasted_fp"), ops=ADD_S, **ID3),  # source: review 12, pasted_fp_same_uuids
}


def run_m1(pcb, work, results):
    import difflib
    lib = os.path.join(here, "..", "lib")
    sys.path.insert(0, lib)
    from gate_board import no_fills, zone_uuids  # noqa: E402
    import shutil
    gb = os.path.join(lib, "gate_board.py")
    built = {}  # board spec: folder holding it, so each board is built once
    for name, c in M1_CASES.items():
        d = os.path.join(work, "m1", name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        board = os.path.join(d, "in.kicad_pcb")
        if c["board"] not in built:
            bd = os.path.join(work, "m1", "boards", str(len(built)))
            shutil.rmtree(bd, ignore_errors=True)
            os.makedirs(bd)
            kind, variant, *extra = c["board"]
            subprocess.run([sys.executable, os.path.join(lib, "synth_board.py") if kind == "synth" else gb, variant, os.path.join(bd, "in.kicad_pcb")], check=True, capture_output=True)
            if extra and extra[0]:
                t = open(os.path.join(bd, "in.kicad_pcb")).read().rstrip()
                open(os.path.join(bd, "in.kicad_pcb"), "w").write(t[:-1] + extra[0] + ")\n")
            built[c["board"]] = bd
        for f in os.listdir(built[c["board"]]):  # the board and its project (design rules)
            shutil.copy(os.path.join(built[c["board"]], f), d)
        opsf = os.path.join(d, "ops.json")
        json.dump(ops_json(c["ops"]), open(opsf, "w"))
        before, src = sha(board), open(board).read()
        want, problem, shas, first = c["want"], None, set(), None
        for k in range(c.get("runs", 1)):
            out = os.path.join(d, f"run{k}.out.kicad_pcb")
            for f in (out, out.replace(".kicad_pcb", ".rejected.kicad_pcb")):
                if os.path.exists(f):
                    os.remove(f)
            r = subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(d, f"w{k}"), "-o", out], capture_output=True, text=True)
            js, problems = check(r.stdout, r.returncode)
            if problems:
                problem = "output contract: " + "; ".join(problems)
                break
            got, err = js["outcome"], js.get("error", {})
            ok = {"pass": got in ("done", "rejected"), "not_unjoined": not (got == "refused" and err.get("code") == "edit-unjoined"), "any": True}.get(want, got == want)
            if not ok:
                problem = f"run {k}: expected {want}, got {got}: {err.get('code')} {err.get('message', '')[:200]} {js.get('data', {}).get('regressions')}"
            elif c.get("code") and err.get("code") != c["code"]:
                problem = f"run {k}: expected code {c['code']}, got {err.get('code')}: {err.get('message', '')[:200]}"
            elif c.get("words") and c["words"] not in err.get("message", ""):
                problem = f"run {k}: message does not say {c['words']!r}: {err.get('message', '')[:200]}"
            elif sha(board) != before:
                problem = "the input board changed"
            elif got == "refused" and os.path.exists(out):
                problem = "a refused edit wrote a board"
            elif c.get("oracle") and got in ("done", "rejected"):
                v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_edit.py"), board, opsf, js["data"]["written"]], capture_output=True, text=True)
                if v.returncode != 0:
                    problem = f"verify_edit failed: {v.stdout[-500:]}{v.stderr[-200:]}"
            if problem:
                break
            if got == "done" and os.path.exists(out):
                shas.add(sha(out))
                first = first or out
            if c.get("check") == "fp_pcbnew":
                info = lambda *a: json.loads(subprocess.run([sys.executable, gb, "fpinfo", *a], check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1])
                written = out if os.path.exists(out) else js.get("data", {}).get("written", out)
                got_i, want_i = info(written, "R5"), info(board, "R5", "33", "21.5")
                if got_i != want_i:
                    problem = f"move_footprint differs from pcbnew's move: {got_i} vs {want_i}"
        if not problem and c.get("check") in ("gate", "identity", "markers"):
            if len(shas) != 1:
                problem = f"{len(shas)} different files over {c['runs']} runs"
            else:
                fm = json.loads(subprocess.run([sys.executable, gb, "fills", first], check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1])
                t = open(first).read()
                if fm:
                    problem = f"fills differ from pcbnew's refill: {json.dumps(fm)[:300]}"
                elif c["check"] != "gate" and zone_uuids(t) != zone_uuids(src):
                    problem = f"zone uuids changed: {zone_uuids(src)} -> {zone_uuids(t)}"
                elif c["check"] != "gate" and "00000000-0000-4000-8000-" in t and "00000000-0000-4000-8000-" not in src:
                    problem = "a marker uuid reached the written board"
                elif c["check"] == "identity":
                    removed = [ln for ln in difflib.unified_diff(no_fills(src).splitlines(), no_fills(t).splitlines(), lineterm="", n=0) if ln.startswith("-") and not ln.startswith("---")]
                    if removed:
                        problem = f"lines outside fills removed: {removed[:5]}"
        results[name] = problem or "ok"
# ---- end of reviews 8 to 12 ----


if __name__ == "__main__":
    pcb, work = sys.argv[1:3]
    os.makedirs(work, exist_ok=True)
    results = {}
    for name, (ops, want, code, extra) in CASES.items():
        board = os.path.join(work, f"{name}.kicad_pcb")
        subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), VARIANT.get(name, "base"), board], check=True, capture_output=True)
        opsf = os.path.join(work, f"{name}.ops.json")
        json.dump(ops_json(ops), open(opsf, "w"))
        before = sha(board)
        out = os.path.join(work, f"{name}.out.kicad_pcb")
        r = subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(work, name + "_w"), "-o", out], capture_output=True, text=True)
        d, problems = check(r.stdout, r.returncode)
        if problems:
            results[name] = "output contract: " + "; ".join(problems)
            continue
        got = d["outcome"]
        err = d.get("error", {})
        if got != want:
            results[name] = f"expected {want}, got {got}: {err.get('code')} {err.get('message', '')[:200]} {d.get('data', {}).get('regressions')}"
        elif code and err.get("code") != code:
            results[name] = f"expected code {code}, got {err.get('code')}: {err.get('message', '')[:200]}"
        elif sha(board) != before:
            results[name] = "the input board changed"
        elif want == "refused" and os.path.exists(out):
            results[name] = "a refused edit wrote a board"
        elif want == "rejected" and (os.path.exists(out) or not os.path.exists(d.get("written", ""))):
            results[name] = "a rejected edit must write only the .rejected file"
        elif want == "done":
            v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_edit.py"), board, opsf, out], capture_output=True, text=True)
            if v.returncode != 0:
                results[name] = f"verify_edit failed: {v.stdout[-600:]}{v.stderr[-300:]}"
            elif extra == "twice" and sha(out) != (lambda o2: (subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(work, name + "_w2"), "-o", o2], capture_output=True), sha(o2))[1])(out + ".again.kicad_pcb"):
                results[name] = "two runs of the same edit gave different files"
            elif extra == "fixes unconnected N" and not any(f.startswith("unconnected_items N") for f in d["data"]["fixed"]):
                results[name] = f"the gate should report unconnected N fixed: {d['data']['fixed']}"
            else:
                results[name] = "ok"
        else:
            results[name] = "ok"
    run_m1(pcb, work, results)  # reviews 8 to 12
    # the gate's fill carry-back on a board with many kinds of zones (gate_zone_spec): edited three times, each
    # result is the input plus the edit outside the fills, byte for byte, every zone's fill equals
    # pcbnew's own refill, and the three runs give the same bytes
    import spec_board as SB
    for name, variant, strip, ops in GATE_ZONE_CASES:
        board = os.path.join(work, f"{name}.kicad_pcb")
        SB.build_board(board, gate_zone_spec(variant))
        if strip:
            strip_zone_uuids(board)
        opsf = os.path.join(work, f"{name}.ops.json")
        json.dump(ops, open(opsf, "w"))
        shas, why = set(), None
        for k in range(3):
            out = os.path.join(work, f"{name}_{k}.out.kicad_pcb")
            r = subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(work, f"{name}_{k}_w"), "-o", out], capture_output=True, text=True)
            d, problems = check(r.stdout, r.returncode)
            if problems:
                why = "output contract: " + "; ".join(problems)
                break
            if d.get("outcome") != "done":
                why = f"run {k + 1}: {d.get('outcome')} {d.get('error')} {d.get('data', {}).get('regressions')}"
                break
            shas.add(sha(out))
            if k == 0:
                # review 9's own oracle (check_splice.py): verify_edit compares footprints with their zones' fills, so
                # it cannot read a board whose footprint holds a copper zone
                fv = SB.fill_vs_pcbnew(out)
                if not SB.input_plus_appended(board, out) or fv["fill_mismatch"]:
                    why = f"not the input plus the edit outside the fills, or a fill not pcbnew's: {json.dumps(fv)[:400]}"
                    break
        if why is None and len(shas) != 1:
            why = f"three runs gave {len(shas)} different files"
        results[name] = why or "ok"
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
    sys.exit(0 if not bad else 1)
