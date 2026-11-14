"""Cases for `pcb route` on small synthetic boards (tests/lib/synth_board.py), from reviews 3 and 4. Each case
checks the command's outcome; every result it writes is then checked by tests/oracles/verify_route.py.

Usage: python3 route_cases.py pcb-binary freerouting.jar workdir
Prints one JSON summary; exit 1 on any failure.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402
REGION = "10,5,50,35"
# name: (board variant, extra route arguments, outcome, words in the error, nets for verify (targets, allowed))
CASES = {
    "rip_all_keeps_locked": ("base", ["--rip", "all", "--nets", "N"], "done", None, ("", "all")),
    "rip_one_net": ("base", ["--rip", "W", "--nets", "N"], "done", None, ("", "W,N")),
    "zoned_rip_all": ("gzone", ["--rip", "all"], "done", None, ("", "all")),
    "arc_refused": ("arc", ["--nets", "N"], "refused", "arcs", None),
    "non_ascii_refused": ("nonascii", ["--nets", "N"], "refused", "not ASCII", None),
    "unknown_net_refused": ("base", ["--nets", "NOPE"], "refused", "no net NOPE", None),
    "unknown_net_with_rip_all_refused": ("base", ["--rip", "all", "--nets", "NOPE"], "refused", "no net NOPE", None),
    "worse_result_rejected": ("tight", ["--nets", "N"], "rejected", None, None),
    # review 5, 3: the input is named like the rejected result's file; the gate must refuse, not overwrite it
    "rejected_onto_input_refused": ("tight", ["--nets", "N"], "refused", "is the input board", None),
    # Q walls on F.Cu and B.Cu leave N only the inner layers: kept to the outer layers it must stay open, and
    # allowed all four it must cross on an inner one (Freerouting 2.5 routes a DSN "power" layer, so the layer
    # limit has to reach it as --router.layers.routable)
    "layers_outer_only": ("four", ["--nets", "N"], "done", None, ("", "N")),
    "layers_inner_allowed": ("four", ["--nets", "N", "--layers", "F.Cu,In1.Cu,In2.Cu,B.Cu"], "done", None, ("", "N")),
    # review 6, K4: the board's custom rules file says N is at least 0.5 mm wide; the router lays it at 0.2, so the
    # gate, checking by the same rules, must reject the result
    "custom_rules_kept": ("base", ["--nets", "N"], "rejected", None, None),
    # 0.6.0: the same rules file with N routed and W ripped and routed again. Only N's copper breaks the rule, so N's is dropped,
    # W's is kept and the run is done (source: the comparison with Copper; before, one bad net cost the whole run)
    "partial_kept": ("base", ["--rip", "W", "--nets", "N,W"], "done", None, ("", "W")),
    # --width: N (no tracks, so the 0.2 mm default) at 0.3, and W (0.4 mm) ripped and routed again at 0.25
    "width_override_wider": ("base", ["--nets", "N", "--width", "N=0.3"], "done", None, ("", "N", "N=0.3")),
    "width_override_narrower": ("base", ["--rip", "W", "--nets", "W", "--width", "W=0.25"], "done", None, ("", "W", "W=0.25")),
    "width_override_unknown_net_refused": ("base", ["--nets", "N", "--width", "NOPE=0.3"], "refused", "no net NOPE", None),
    # 0.6.0: widths from pcb.toml with --project. width_mm as it is; current_a at the IPC-2221 width for the layers
    # the router may use (1 A on an outer layer: 0.3005 mm, so 0.31); --width replaces either. Before 0.6.0 a power
    # net was laid at the board's default width unless --width named it (source: the comparison with Copper)
    "project_width_mm": ("base", ["--nets", "N", "--project", "PROJECT:width_n"], "done", None, ("", "N", "N=0.35")),
    "project_current_width": ("base", ["--nets", "N", "--project", "PROJECT:amp_n"], "done", None, ("", "N", "N=0.31")),
    "project_width_flag_wins": ("base", ["--nets", "N", "--project", "PROJECT:amp_n", "--width", "N=0.25"], "done", None, ("", "N", "N=0.25")),
    # --prewire: N2 moved 2 mm down by an edit, then N routed to it; the edit's target checked like pcb edit
    "prewire_move_then_route": ("base", ["--nets", "N", "--prewire", "PREWIRE:move_n2"], "done", None, ("N", "N")),
    # a prewired track on a ripped net is the owner's choice: --rip removes the input's copper, never the prewire's
    "prewire_kept_through_rip": ("base", ["--rip", "N", "--nets", "N", "--prewire", "PREWIRE:stub_n"], "done", None, ("N", "N")),
    "prewire_bad_target_refused": ("base", ["--nets", "N", "--prewire", "PREWIRE:bad"], "refused", "N2 is at", None),
    # M5a (proposal R1): N is class critical in pcb.toml. The router does not take it by name; it does not run while
    # N is open; with N pre-wired it routes S and leaves N's track as laid
    "critical_named_refused": ("base", ["--nets", "N", "--project", "PROJECT:crit_n"], "refused", "class critical", None),
    "critical_open_refused": ("base", ["--nets", "S", "--project", "PROJECT:crit_n"], "refused", "not fully connected", None),
    "critical_prewired_kept": ("base", ["--nets", "S", "--prewire", "PREWIRE:wire_n", "--project", "PROJECT:crit_n"], "done", None, ("", "S")),
    # M5a (proposal R2): --staged. On the base board F.Cu alone connects N: one stage. On the four-layer board Q
    # walls F.Cu and B.Cu, so stage 1 leaves N open and stage 2 crosses on an inner layer; a 1 mm cap on runs off the
    # first layer rejects that crossing and leaves no output
    "staged_first_layer_enough": ("base", ["--nets", "N", "--staged"], "done", None, ("", "N")),
    "staged_second_stage": ("four", ["--nets", "N", "--staged", "--layers", "F.Cu,In1.Cu,In2.Cu,B.Cu"], "done", None, ("", "N")),
    "staged_cross_capped": ("four", ["--nets", "N", "--staged", "--layers", "F.Cu,In1.Cu,In2.Cu,B.Cu", "--max-cross-mm", "1"], "rejected", None, None),
    "staged_one_layer_refused": ("base", ["--nets", "N", "--staged", "--layers", "F.Cu"], "refused", "two or more", None),
}
PREWIRE = {
    "move_n2": [{"op": "move_footprint", "ref": "N2", "from": [40, 15], "to": [40, 17]}],
    "stub_n": [{"op": "add_track", "net": "N", "layer": "F.Cu", "width": 0.2, "points": [[20, 15], [30, 15]], "free_end": True}],
    "bad": [{"op": "move_footprint", "ref": "N2", "from": [41, 15], "to": [40, 17]}],
    "wire_n": [{"op": "add_track", "net": "N", "layer": "F.Cu", "width": 0.2, "points": [[20, 15], [40, 15]]}],
}
# pcb.toml files for --project
PROJECT_HEAD = 'schema = 1\n\n[project]\nname = "r"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = 2\nfab = "jlcpcb-2layer-1.6mm"\n\n[nets.N]\n'
PROJECT = {"crit_n": PROJECT_HEAD + 'class = "critical"\n', "width_n": PROJECT_HEAD + "width_mm = 0.35\n", "amp_n": PROJECT_HEAD + "current_a = 1.0\n"}
# custom rules files (.kicad_dru) written beside a case's board
N_WIDE = '(version 1)\n(rule "N wide"\n  (condition "A.NetName == \'N\'")\n  (constraint track_width (min 0.5mm)))\n'
DRU = {"custom_rules_kept": N_WIDE, "partial_kept": N_WIDE}
# case: (copper layers new N tracks may use, whether N must end connected)
LAYER_CHECKS = {
    "layers_outer_only": ({"F.Cu", "B.Cu"}, False),
    "layers_inner_allowed": ({"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}, True),
    "staged_second_stage": ({"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}, True),
}
LAYER_PROBE = """
import json, sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
b.BuildConnectivity()
layers = sorted({b.GetLayerName(t.GetLayer()) for t in b.GetTracks() if t.GetNetname() == "N" and t.GetClass() == "PCB_TRACK"})
print(json.dumps({"layers": layers, "unrouted": b.GetConnectivity().GetUnconnectedCount(True)}))
"""


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---- Reviews 8 to 12 (M1), moved from tests/regressions@e17bfac/r08 to r12; see docs/reviews/audit/AUDIT_m1.md ----
# Prewired copper through --rip, --width, and the choice between the two router runs. A case with `sessions` runs
# the stand-in java (tests/lib/fake_java/fakejava), which hands pcb the Specctra sessions written by mkses.py
# ("NET:LAYER:WIDTH:x,y;x,y", KiCad mm) for route_region and route_open, or "fail" / "sleep"; others run Freerouting.
# Each case: (synth_board variant, text appended to the board, route arguments, prewire ops or None, sessions or
# None, --timeout or None, check(js, data, written, files) -> True or a problem).
FAKE = os.path.join(here, "..", "lib", "fake_java")


def m1_segs(path, net):
    if not path or not os.path.exists(path):
        return []
    sys.path.insert(0, os.path.join(here, "..", "lib"))
    import kisexp
    src = kisexp.parse(open(path).read())
    return [(tuple(x.nums("start")), tuple(x.nums("end")), x.find("layer").arg(1), x.nums("width")[0]) for x in src.find_all("segment") if x.find("net").arg(1) == net]


def m1_has(path, net, a, c, width=None):
    return any(sorted([s, e]) == sorted([a, c]) and (width is None or abs(w - width) < 1e-6) for s, e, _, w in m1_segs(path, net))


def m1_vias(path, net):
    sys.path.insert(0, os.path.join(here, "..", "lib"))
    import kisexp
    return [tuple(x.nums("at")) for x in kisexp.parse(open(path).read()).find_all("via") if x.find("net").arg(1) == net] if path and os.path.exists(path) else []


def m1_branch(outcome, attempts=None, used=None, warn=None):
    """Review 9, check 6: the outcome, the attempts run and the one used, the written file the attempt reported."""
    def chk(js, data, dest, files):
        if js["outcome"] != outcome:
            return f"outcome {js['outcome']}, want {outcome}: {js.get('error')}"
        if outcome == "failed":
            return True
        att = data.get("attempts", [])
        if (len(att), data.get("attempt_used")) != (attempts, used):
            return f"attempts {len(att)} used {data.get('attempt_used')}, want {attempts} and {used}"
        wr = os.path.basename(data.get("written", "") or "")
        if wr not in files:
            return f"written file {wr!r} not in {files}"
        if outcome == "done" and ("out.rejected.kicad_pcb" in files or data.get("regressions")):
            return f"done but {files} {data.get('regressions')}"
        if outcome == "rejected" and ("out.kicad_pcb" in files or not data.get("regressions")):
            return f"rejected but {files} {data.get('regressions')}"
        if warn and warn not in [w["code"] for w in js.get("warnings", [])]:
            return f"no {warn} warning: {js.get('warnings')}"
        want = att[used]["added_segments"]
        d = os.path.dirname(dest)
        added = open(dest).read().count("(segment") - open(os.path.join(d, "in.kicad_pcb")).read().count("(segment")
        if want != data.get("added_segments") or added < want - data.get("ripped_segments", 0) - data.get("pruned_segments", 0):
            return f"the file holds {added} new segments, attempt {used} reported {want} (added_segments {data.get('added_segments')})"
        return True
    return chk


def m1_outcome(outcome):
    return lambda js, data, dest, files: True if js["outcome"] == outcome else f"outcome {js['outcome']}, want {outcome}: {js.get('error')} {data.get('regressions')}"


MT = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)
RIP_L = ["--rip", "L", "--nets", "L"]
S_OK, S_SHORT_LOOP = "S:F.Cu:0.2:30,34;30,30", "S:F.Cu:0.2:25,30;25,14.5;35,14.5;35,30"  # the loop crosses L twice
N_OK, N_SHORT = "N:F.Cu:0.2:20,15;40,15", "N:F.Cu:0.2:20,15;30,20;40,15"  # N_SHORT crosses L at (30,20)
L_ZONE = ('\t(zone (net "L") (layer "F.Cu") (uuid "11111111-2222-3333-4444-555555555555") (hatch edge 0.5) (connect_pads (clearance 0.2)) '
          '(min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 42 17) (xy 48 17) (xy 48 31) (xy 42 31))))\n')
L_HOLE = ('\t(zone (net "L") (layer "F.Cu") (uuid "11111111-2222-3333-4444-555555555556") (hatch edge 0.5) (connect_pads (clearance 0.2)) '
          '(min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 42 17) (xy 48 17) (xy 48 31) (xy 42 31))) '
          '(polygon (pts (xy 43 26) (xy 47 26) (xy 47 29.5) (xy 43 29.5))))\n')
both = lambda *w: {"route_region": list(w), "route_open": list(w)}
M1_CASES = {
    # review 8, 1 to 3 and 15: prewired copper on a ripped net is kept; --width twice is refused (Freerouting)
    "r08_prewired_set_width_survives_rip": ("base", "", ["--rip", "W", "--nets", "W"], [{"op": "set_width", "net": "W", "layer": "F.Cu", "start": [15, 10], "end": [30, 10], "from": 0.4, "to": 0.5}], None, None,
                                            lambda js, data, dest, files: m1_has(dest, "W", (15.0, 10.0), (30.0, 10.0), 0.5) or f"W: {m1_segs(dest, 'W')}"),  # source: review 8, prewired_set_width_survives_rip
    "r08_prewired_readd_survives_rip": ("base", "", ["--rip", "W", "--nets", "W"], [{"op": "delete", "what": "track", "net": "W", "layer": "F.Cu", "start": [30, 10], "end": [38, 10], "all": True}, MT("W", "F.Cu", 0.45, (30, 10), (38, 10))], None, None,
                                        lambda js, data, dest, files: m1_has(dest, "W", (30.0, 10.0), (38.0, 10.0), 0.45) or f"W: {m1_segs(dest, 'W')}"),  # source: review 8, prewired_readd_survives_rip
    "r08_prewired_stub_not_pruned": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (45, 23), free_end=True)], None, None,
                                     lambda js, data, dest, files: m1_has(dest, "L", (45.0, 20.0), (45.0, 23.0)) or f"L: {m1_segs(dest, 'L')}"),  # source: review 8, prewired_stub_not_pruned
    "r08_width_twice_refused": ("base", "", ["--nets", "N", "--width", "N=0.3", "--width", "N=0.25"], None, None, None, m1_outcome("refused")),  # source: review 8, width_twice_refused
    # review 9, check 6: the choice between the region run and the open-nets run (stand-in java), --nets N,S
    "r09_first_closes_all": ("base", "", ["--nets", "N,S"], None, {"route_region": [S_OK, N_OK]}, "10", m1_branch("done", 1, 0)),  # source: review 9, first_closes_all
    "r09_preferred_open_rejected_region_kept": ("base", "", ["--nets", "N,S"], None, {"route_region": [], "route_open": [N_SHORT]}, "10", m1_branch("done", 2, 0)),  # source: review 9, preferred_open_rejected_region_kept
    "r09_preferred_region_rejected_open_kept": ("base", "", ["--nets", "N,S"], None, {"route_region": [S_OK, S_SHORT_LOOP], "route_open": []}, "10", m1_branch("done", 2, 1)),  # source: review 9, preferred_region_rejected_open_kept
    "r09_both_rejected": ("base", "", ["--nets", "N,S"], None, {"route_region": [S_OK, S_SHORT_LOOP], "route_open": [S_OK, S_SHORT_LOOP, N_OK]}, "10", m1_branch("rejected", 2, 1)),  # source: review 9, both_rejected
    "r09_tie_first_kept": ("base", "", ["--nets", "N,S"], None, {"route_region": [S_OK], "route_open": [N_OK]}, "10", m1_branch("done", 2, 0)),  # source: review 9, tie_first_kept
    "r09_second_fails": ("base", "", ["--nets", "N,S"], None, {"route_region": [S_OK], "route_open": "fail"}, "10", m1_branch("done", 1, 0, "second-run-failed")),  # source: review 9, second_fails
    "r09_second_times_out": ("base", "", ["--nets", "N,S"], None, {"route_region": [S_OK], "route_open": "sleep"}, "10", m1_branch("done", 1, 0, "second-run-failed")),  # source: review 9, second_times_out
    "r09_first_fails": ("base", "", ["--nets", "N,S"], None, {"route_region": "fail", "route_open": [N_OK]}, "10", m1_branch("failed")),  # source: review 9, first_fails
    # review 9, check 3: prewire protection through --rip (p1 and p2 with Freerouting)
    "r09_p1_set_width_middle_track": ("base", "", ["--rip", "W", "--nets", "W"], [{"op": "set_width", "net": "W", "layer": "F.Cu", "start": [30, 10], "end": [38, 10], "to": 0.5, "from": 0.4}], None, "120",
                                      lambda js, data, dest, files: m1_has(dest, "W", (30.0, 10.0), (38.0, 10.0), 0.5) or f"W: {m1_segs(dest, 'W')}"),  # source: review 9, p1_set_width_middle_track
    "r09_p2_prewire_via_and_track_on_ripped_net": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (42, 22)), {"op": "add_via", "net": "L", "at": [42, 22], "size": 0.8, "drill": 0.4}, MT("L", "B.Cu", 0.2, (42, 22), (35, 22), free_end=True)], None, "120",
                                                   lambda js, data, dest, files: (m1_has(dest, "L", (45.0, 20.0), (42.0, 22.0)) and (42.0, 22.0) in m1_vias(dest, "L") and any(l == "B.Cu" and (42.0, 22.0) in (s, e) for s, e, l, w in m1_segs(dest, "L"))) or f"L: {m1_segs(dest, 'L')} vias {m1_vias(dest, 'L')}"),  # source: review 9, p2_prewire_via_and_track_on_ripped_net
    "r09_p3_router_joins_middle_of_prewire_stub": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 22), free_end=True)], {"route_region": ["L:F.Cu:0.2:20,20;42.5,21"]}, "120",
                                                   lambda js, data, dest, files: (js["outcome"] == "done" and not m1_has(dest, "L", (42.5, 21.0), (40.0, 22.0)) and m1_has(dest, "L", (45.0, 20.0), (42.5, 21.0))) or f"{js['outcome']} L: {m1_segs(dest, 'L')}"),  # source: review 9, p3_router_joins_middle_of_prewire_stub
    "r09_p4_prewire_tail_on_ripped_end": ("base", "", RIP_L, [MT("L", "B.Cu", 0.2, (30, 24), (33, 26), free_end=True)], {"route_region": ["L:F.Cu:0.2:20,20;45,20"]}, "120",
                                          lambda js, data, dest, files: m1_has(dest, "L", (30.0, 24.0), (33.0, 26.0)) or f"L: {m1_segs(dest, 'L')}"),  # source: review 9, p4_prewire_tail_on_ripped_end
    "r09_p5_input_still_ripped": ("base", "", RIP_L, [{"op": "set_width", "net": "W", "layer": "F.Cu", "start": [30, 10], "end": [38, 10], "to": 0.45, "from": 0.4}], {"route_region": ["L:F.Cu:0.2:20,20;30,22;45,20"]}, "120",
                                  lambda js, data, dest, files: (not m1_has(dest, "L", (20.0, 20.0), (45.0, 20.0)) and data.get("ripped_segments") == 2) or f"ripped {data.get('ripped_segments')} L: {m1_segs(dest, 'L')}"),  # source: review 9, p5_input_still_ripped
    # review 10 (closure of review 9, 9): the preferred run rejected, the first kept, no .rejected file of any kind left
    "r10_rejected_run_files_removed": ("base", "", ["--nets", "N"], None, {"route_region": [], "route_open": ["N:F.Cu:0.2:20,15;30,15;30,10;40,10;40,15"]}, "30",
                                       lambda js, data, dest, files: (js["outcome"] == "done" and not any(f.startswith("out.rejected") for f in files)) or f"{js['outcome']} {files}"),  # source: review 10, rejected_run_files_removed
    # review 10: multi-segment prewire stubs, the router joining at different places
    "r10_single_segment_stub": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 22), free_end=True)], {"route_region": ["L:F.Cu:0.2:20,20;42.5,21"]}, "60", m1_outcome("done")),  # source: review 10, single_segment_stub
    "r10_two_segment_stub": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 22), (36, 22), free_end=True)], {"route_region": ["L:F.Cu:0.2:20,20;42.5,21"]}, "60", m1_outcome("done")),  # source: review 10, two_segment_stub
    "r10_two_segment_stub_join_far": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 22), (36, 22), free_end=True)], {"route_region": ["L:F.Cu:0.2:20,20;38,22"]}, "60", m1_outcome("done")),  # source: review 10, two_segment_stub_join_far
    "r10_free_end_also_reached": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 22), free_end=True)], {"route_region": ["L:F.Cu:0.2:20,20;42.5,21", "L:F.Cu:0.2:42.5,21;40,22"]}, "60", m1_outcome("done")),  # source: review 10, free_end_also_reached
    # review 11: stubs anchored in a never-filled zone, at a pad, joined at a bend, ending on other input copper
    "r11_anchor_unfilled_zone_two_seg": ("base", L_ZONE, RIP_L, [MT("L", "F.Cu", 0.2, (44, 28), (40, 28), (34, 28), free_end=True)], both("L:F.Cu:0.2:20,20;37,28"), "60", m1_outcome("done")),  # source: review 11, anchor_unfilled_zone_two_seg
    "r11_anchor_unfilled_zone_one_seg": ("base", L_ZONE, RIP_L, [MT("L", "F.Cu", 0.2, (44, 28), (34, 28), free_end=True)], both("L:F.Cu:0.2:20,20;37,28"), "60", m1_outcome("done")),  # source: review 11, anchor_unfilled_zone_one_seg
    "r11_anchor_pad_two_seg": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 28), (34, 28), free_end=True)], both("L:F.Cu:0.2:20,20;37,28"), "60", m1_outcome("done")),  # source: review 11, anchor_pad_two_seg
    "r11_join_at_bend": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 28), (34, 28), free_end=True)], both("L:F.Cu:0.2:20,20;40,28"), "60", m1_outcome("done")),  # source: review 11, join_at_bend
    "r11_free_end_on_other_input": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (40, 26), (34, 26), free_end=True)], both("L:F.Cu:0.2:20,20;37,26"), "60", m1_outcome("done")),  # source: review 11, free_end_on_other_input
    # review 12: two stubs at one pad, a zone hole, an inner corner
    "r12_two_stubs_one_pad": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (48, 25), free_end=True), MT("L", "F.Cu", 0.2, (45, 20), (40, 28), (34, 28), free_end=True)], both("L:F.Cu:0.2:20,20;37,28"), "60",
                              lambda js, data, dest, files: any((s, e, l) == ((45.0, 20.0), (48.0, 25.0), "F.Cu") for s, e, l, w in m1_segs(dest, "L")) or f"stub 1 not kept: {m1_segs(dest, 'L')}"),  # source: review 12, two_stubs_one_pad: stub 1 kept
    "r12_anchor_zone_outside_hole": ("base", L_HOLE, RIP_L, [MT("L", "F.Cu", 0.2, (44, 24), (40, 24), (34, 24), free_end=True)], both("L:F.Cu:0.2:20,20;37,24"), "60", m1_outcome("done")),  # source: review 12, anchor_zone_outside_hole
    "r12_anchor_zone_in_hole": ("base", L_HOLE, RIP_L, [MT("L", "F.Cu", 0.2, (44, 28), (40, 28), (34, 28), free_end=True)], both("L:F.Cu:0.2:20,20;37,28"), "60", m1_outcome("refused")),  # source: review 12, anchor_zone_in_hole
    "r12_join_inner_corner_3seg": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (42, 26), (38, 26), (34, 26), free_end=True)], both("L:F.Cu:0.2:20,20;38,26"), "60", m1_outcome("done")),  # source: review 12, join_inner_corner_3seg
    "r12_one_stub_control": ("base", "", RIP_L, [MT("L", "F.Cu", 0.2, (45, 20), (48, 25), free_end=True)], both("L:F.Cu:0.2:20,20;45,20"), "60", m1_outcome("rejected")),  # source: review 12, one_stub_control
}


def run_m1(pcb, jar, work, results):
    built = {}  # (variant, extra): folder holding that board, so each board is built once
    for name, (variant, extra, args, prewire, sessions, timeout, chk) in M1_CASES.items():
        d = os.path.join(work, "m1", name)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        b = os.path.join(d, "in.kicad_pcb")
        if (variant, extra) not in built:
            bd = os.path.join(work, "m1", "boards", str(len(built)))
            shutil.rmtree(bd, ignore_errors=True)
            os.makedirs(bd)
            subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), variant, os.path.join(bd, "in.kicad_pcb")], check=True, capture_output=True)
            if extra:
                t = open(os.path.join(bd, "in.kicad_pcb")).read().rstrip()
                open(os.path.join(bd, "in.kicad_pcb"), "w").write(t[:-1] + extra + ")\n")
            built[(variant, extra)] = bd
        for f in os.listdir(built[(variant, extra)]):  # the board and its project (design rules)
            shutil.copy(os.path.join(built[(variant, extra)], f), d)
        cmd = [pcb, "--json", "route", b, "--region", REGION, "--freerouting", jar, "--work", os.path.join(d, "w"), "-o", os.path.join(d, "out.kicad_pcb"), *args]
        if prewire is not None:
            json.dump(prewire, open(os.path.join(d, "prewire.json"), "w"))
            cmd += ["--prewire", os.path.join(d, "prewire.json")]
        if timeout:
            cmd += ["--timeout", timeout]
        env = dict(os.environ)
        if sessions:
            env["FAKE_DIR"] = d
            cmd += ["--java", os.path.join(FAKE, "fakejava")]
            for tag, spec in sessions.items():
                if spec == "fail":
                    open(os.path.join(d, tag + ".fail"), "w").write("")
                    continue
                if spec == "sleep":
                    open(os.path.join(d, tag + ".sleep"), "w").write("30")
                    spec = []
                subprocess.run([sys.executable, os.path.join(FAKE, "mkses.py"), os.path.join(d, tag + ".ses"), *spec], check=True)
        before = sha(b)
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        js, problems = check(r.stdout, r.returncode)
        if problems:
            results[name] = "output contract: " + "; ".join(problems)
            continue
        data = js.get("data", {})
        files = sorted(f for f in os.listdir(d) if f.endswith((".kicad_pcb", ".kicad_pro")))
        got = chk(js, data, data.get("written") or js.get("written"), files)
        results[name] = "the input board changed" if sha(b) != before else ("ok" if got is True else str(got)[:400])
# ---- end of reviews 8 to 12 ----


if __name__ == "__main__":
    pcb, jar, work = sys.argv[1:4]
    os.makedirs(work, exist_ok=True)
    results = {}
    for name, (variant, args, want, words, verify) in CASES.items():
        board = os.path.join(work, f"{name}.kicad_pcb")
        if name == "rejected_onto_input_refused":
            board = os.path.join(work, f"{name}.out.rejected.kicad_pcb")
        subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), variant, board], check=True, capture_output=True)
        if name in DRU:
            open(os.path.splitext(board)[0] + ".kicad_dru", "w").write(DRU[name])
        args = list(args)
        for k, a in enumerate(args):
            if a.startswith("PREWIRE:"):
                pf = os.path.join(work, f"{name}.prewire.json")
                json.dump(PREWIRE[a.split(":")[1]], open(pf, "w"))
                args[k] = pf
            if a.startswith("PROJECT:"):
                pd = os.path.join(work, f"{name}_project")
                os.makedirs(pd, exist_ok=True)
                open(os.path.join(pd, "pcb.toml"), "w").write(PROJECT[a.split(":")[1]])
                args[k] = pd
        before = sha(board)
        out = os.path.join(work, f"{name}.out.kicad_pcb")
        r = subprocess.run([pcb, "--json", "route", board, "--region", REGION, "--freerouting", jar, "--work", os.path.join(work, name + "_w"), "-o", out, *args], capture_output=True, text=True)
        d, problems = check(r.stdout, r.returncode)
        if problems:
            results[name] = "output contract: " + "; ".join(problems)
            continue
        got = d["outcome"]
        msg = d.get("error", {}).get("message", "")
        if got != want:
            results[name] = f"expected {want}, got {got} (exit {r.returncode}): {msg or d.get('data', {}).get('regressions')}"
        elif words and words not in msg:
            results[name] = f"message does not say {words!r}: {msg}"
        elif sha(board) != before:
            results[name] = "the input board changed"
        elif want == "rejected" and (os.path.exists(out) or not os.path.exists(os.path.join(work, f"{name}.out.rejected.kicad_pcb"))):
            results[name] = "a rejected result must go to .rejected and leave the output unwritten"
        elif want == "done" and verify:
            base = board
            if "--prewire" in args:
                base = os.path.join(work, name + "_w", "prewired.kicad_pcb")
                ve = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_edit.py"), board, args[args.index("--prewire") + 1], base], capture_output=True, text=True)
                if ve.returncode != 0:
                    results[name] = f"verify_edit (prewire) failed: {ve.stdout[-500:]}"
                    continue
            v = subprocess.run([sys.executable, os.path.join(here, "..", "oracles", "verify_route.py"), base, out, REGION, *verify], capture_output=True, text=True)
            results[name] = "ok" if v.returncode == 0 else f"verify_route failed: {v.stdout[-600:]}{v.stderr[-300:]}"
            # a --width case must have laid copper at that width (verify_route checks only what was added)
            if results[name] == "ok" and len(verify) == 3:
                net, mm = verify[2].split("=")
                sys.path.insert(0, os.path.join(here, "..", "lib"))
                import kisexp
                src = kisexp.parse(open(out).read())
                new = [x for x in src.find_all("segment") if x.find("net").arg(1) == net and abs(x.nums("width")[0] - float(mm)) < 1e-6]
                if not new:
                    results[name] = f"no {net} track at {mm} mm in the result"
            if results[name] == "ok" and name == "staged_first_layer_enough":
                p = subprocess.run([sys.executable, "-c", LAYER_PROBE, out], capture_output=True, text=True)
                got_l = json.loads(p.stdout.strip().splitlines()[-1])
                if set(got_l["layers"]) != {"F.Cu"}:
                    results[name] = f"N should be routed on F.Cu alone: {got_l}"
            if results[name] == "ok" and name == "partial_kept":
                codes = [w["code"] for w in d.get("warnings", [])]
                if d["data"].get("dropped_nets") != ["N"] or "N" in d["data"]["nets_routed"] or "W" not in d["data"]["nets_routed"] or "route-partial" not in codes or "N" not in d["data"]["still_open"]:
                    results[name] = f"N's copper must be dropped and reported, W's kept: dropped {d['data'].get('dropped_nets')}, routed {d['data']['nets_routed']}, open {d['data']['still_open']}, warnings {codes}"
            if results[name] == "ok" and name == "critical_prewired_kept":
                sys.path.insert(0, os.path.join(here, "..", "lib"))
                import kisexp
                src = kisexp.parse(open(out).read())
                n_segs = [sorted([tuple(x.nums("start")), tuple(x.nums("end"))]) for x in src.find_all("segment") if x.find("net").arg(1) == "N"]
                if n_segs != [[(20.0, 15.0), (40.0, 15.0)]] or d["data"].get("critical_kept") != ["N"]:
                    results[name] = f"N must be the pre-wired track alone, and reported kept: {n_segs} {d['data'].get('critical_kept')}"
            if results[name] == "ok" and name == "prewire_kept_through_rip":
                sys.path.insert(0, os.path.join(here, "..", "lib"))
                import kisexp
                src = kisexp.parse(open(out).read())
                if not any(x.find("net").arg(1) == "N" and sorted([tuple(x.nums("start")), tuple(x.nums("end"))]) == [(20.0, 15.0), (30.0, 15.0)] for x in src.find_all("segment")):
                    results[name] = "the prewired N track (20,15)-(30,15) is not in the result"
            if results[name] == "ok" and name in LAYER_CHECKS:
                allowed, connected = LAYER_CHECKS[name]
                p = subprocess.run([sys.executable, "-c", LAYER_PROBE, out], capture_output=True, text=True)
                got_l = json.loads(p.stdout.strip().splitlines()[-1])
                if not set(got_l["layers"]) <= allowed:
                    results[name] = f"N was routed on {got_l['layers']}, outside {sorted(allowed)}"
                elif connected and (got_l["unrouted"] or not set(got_l["layers"]) - {"F.Cu", "B.Cu"}):
                    results[name] = f"N should cross on an inner layer: {got_l}"
                elif not connected and not got_l["unrouted"]:
                    results[name] = f"N cannot cross the walls on the outer layers, yet the board is fully connected: {got_l}"
        else:
            results[name] = "ok"
    run_m1(pcb, jar, work, results)  # reviews 8 to 12
    bad = {k: v for k, v in results.items() if v != "ok"}
    print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
    sys.exit(0 if not bad else 1)
