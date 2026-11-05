"""Runs review 14's probes (confirmation of review 13's closures) and checks the outcome each case must have. The
probes print evidence, one JSON line per case; this file holds the verdicts. Exit 1 on any miss. Cases for findings
marked NOTE in docs/reviews/14_review13_confirmation.md are printed under "notes" and do not fail the run.

Usage: python3 check.py pcb-binary workdir [probe.py ...]
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
only = sys.argv[3:]
env = dict(os.environ, PCB_BIN=pcb)
fails, notes, passed = [], [], []


def cases(script):
    if only and script not in only:
        return None
    r = subprocess.run([sys.executable, os.path.join(here, script), os.path.join(work, script[:-3])], capture_output=True, text=True, env=env)
    out = {}
    for ln in r.stdout.splitlines():
        if ln.startswith("{"):
            try:
                c = json.loads(ln)
                out[c["case"]] = c
            except json.JSONDecodeError:
                pass
    if r.returncode or not out:
        fails.append(f"{script}: exit {r.returncode}, {len(out)} cases: {r.stderr[-400:]}")
    return out


def want(tag, c, ok, finding=""):
    """A verdict: `ok` is what the case must show. Every case must also keep the output contract."""
    if c is None:
        fails.append(f"{tag}: case missing")
        return
    if c.get("contract"):
        fails.append(f"{tag}: output contract {c['contract']}")
    (passed if ok else fails).append(f"{tag}{' (' + finding + ')' if finding and not ok else ''}: {'ok' if ok else json.dumps(c)[:500]}")


def note(tag, c, ok, text):
    """A NOTE-level check: printed, never fails the run (the output contract still does)."""
    notes.append(f"{tag}: {'holds' if ok else text}: {json.dumps({k: v for k, v in (c or {}).items() if k not in ('case', 'contract')})[:300]}")
    if c and c.get("contract"):
        fails.append(f"{tag}: output contract {c['contract']}")


def out(c, *o):
    return c is not None and c.get("outcome") in o


def refused(c, code="config"):
    return out(c, "refused") and c.get("code") == code


# stitching: review 13, findings 3, 4, 5, 9, 13
s = cases("stitch14.py")
if s is not None:
    c = s.get("pad_shapes")
    want("stitch pad_shapes", c, out(c, "done") and c["too_close"] == [] and len(c["gaps"]) == 7, "#3")
    c = s.get("pad_custom")
    want("stitch pad_custom", c, out(c, "done") and c["too_close"] == [], "#3")
    c = s.get("keepout_inner_grow")
    want("stitch keepout_inner_grow", c, out(c, "done") and c["in_keepout"] == 0 and c["n_vias"] > 0, "#4")
    for k in ("keepout_board_rule_area", "keepout_footprint_rule_area"):
        c = s.get(k)
        want(f"stitch {k}", c, out(c, "done") and c["in_keepout"] == 0, "#4")
    for k in ("pitch_tiny", "rect_inf", "rect_neg_inf", "pitch_nan", "rect_huge"):
        c = s.get(k)
        want(f"stitch {k}", c, refused(c) and c["seconds"] < 10, "#5")
    c = s.get("grid_near_limit")
    want("stitch grid_near_limit", c, out(c, "done") and c["seconds"] < 60, "#5")
    c = s.get("two_sizes")
    want("stitch two_sizes", c, out(c, "done") and c["sizes"] == [0.6, 1.0] and c["worst_edge_gap"] >= 0.3 - 1e-3, "#9")
    c = s.get("pitch_below")
    want("stitch pitch_below", c, refused(c), "#9")
    for k in ("pitch_eq_0p9", "pitch_eq_1p1"):
        want(f"stitch {k}", s.get(k), out(s.get(k), "done"), "#9")
    for k in ("pitch_eq_0p85", "pitch_eq_1p2"):
        c = s.get(k)
        note(f"stitch {k}", c, not refused(c), "R14-4: pitch equal to size_mm plus margin_mm refused by a float sum")
    c = s.get("nofill_one")
    want("stitch nofill_one", c, out(c, "done") and c["unfilled"] == ["GND:B.Cu"] and c["warnings"] == ["stitch-no-fill"] and "GND:B.Cu" in c["messages"][0], "#13")
    c = s.get("nofill_none_missing")
    want("stitch nofill_none_missing", c, out(c, "done") and c["unfilled"] == [] and c["warnings"] == [], "#13")

# fills: findings 1, 6, 17 and fill-overlap
f = cases("fill14.py")
if f is not None:
    for k in ("same_prio_against", "same_prio_with", "hand_upper_high", "hand_upper_mid", "hand_lower_low", "fp_zone_high", "fp_zone_low"):
        c = f.get(k)
        want(f"fill {k}", c, out(c, "done") and c["refill_diff"] == {}, "#1")
    a, b = f.get("fp_zone_high") or {}, f.get("fp_zone_low") or {}
    want("fill fp_zone order matters", a or None, a.get("fp_zone_area") is not None and b.get("fp_zone_area") is not None and abs(a["fp_zone_area"] - b["fp_zone_area"]) > 1, "#1 (probe sensitivity)")
    c = f.get("hand_legacy")
    note("fill hand_legacy", c, out(c, "done") and c["refill_diff"] == {}, "R14-5: an 8-digit legacy zone uuid sorts by text in pcb, by value in KiCad")
    c = f.get("hand_no_uuid")
    note("fill hand_no_uuid", c, out(c, "done") and not any(c.get("refill_runs_differ", [True])), "R14-5: a zone with no uuid gets a random one at each KiCad load, so refills vary")
    for k, fc, bc in [("ko_inner_only", True, True), ("ko_front_only", False, True), ("ko_all", False, False)]:
        c = f.get(k)
        ins = (c or {}).get("inside") or {}
        want(f"fill {k}", c, out(c, "done") and c["refill_diff"] == {} and (ins.get("F.Cu", 0) > 1) == fc and (ins.get("B.Cu", 0) > 1) == bc, "#6")
    c = f.get("ov_same")
    want("fill ov_same", c, out(c, "done") and len(c["overlaps"]) == 1 and c["warnings"] == ["fill-overlap"] and "A and B on F.Cu" in c["messages"][0]
         and c["second_same_warnings"] and c["second_same_bytes"], "fill-overlap")
    for k in ("ov_distinct", "ov_apart"):
        c = f.get(k)
        want(f"fill {k}", c, out(c, "done") and c["overlaps"] == [] and c["warnings"] == [], "fill-overlap false positive")
    c = f.get("ov_three")
    want("fill ov_three", c, out(c, "done") and len(c["overlaps"]) == 3 and c["second_same_warnings"] and c["second_same_bytes"], "fill-overlap")
    for k in ("ov_plane", "ov_hand_zone", "ov_two_planes"):
        c = f.get(k)
        note(f"fill {k}", c, bool(c and c.get("overlaps")), "R14-1: zones of two nets overlapping at one priority, other than two fills, are not warned")
    c = f.get("oracle_regex")
    want("fill oracle_regex", c, c is not None and all(c.get(s_, {}).get("shape_change_seen") and c[s_].get("zone_flag_masked") and c[s_]["shape_flags_in_file"] >= 2
                                                       for s_ in ("check_splice.py", "gate12.py")), "#17")

# pad overrides: finding 7 and the property
o = cases("override14.py")
if o is not None:
    orig = (o.get("original") or {}).get("conns") or {}
    J = lambda c, k: ((c or {}).get("conns") or {}).get(k)
    c = o.get("change_none_then")
    want("override change_none_then", c, out(c, "done") and J(c, "J1.1@20.0") == 0 and J(c, "J1.2@22.54") == 2, "#7")
    c = o.get("change_changed")
    want("override change_changed", c, out(c, "done") and J(c, "J1.1@20.0") == 2 and J(c, "J1.2@22.54") == 0 and c["props"] == {"J1": ["1:-1;2:1", True]}, "#7")
    c = o.get("change_dropped")
    want("override change_dropped", c, out(c, "done") and c["conns"] == orig and c["props"] == {}, "#7")
    c = o.get("two_one_dropped")
    want("override two_one_dropped", c, out(c, "done") and J(c, "J1.1@20.0") == 2 and J(c, "J2.1@40.0") == -1 and J(c, "J2.2@42.54") == -1 and list(c["props"]) == ["J1"], "#7")
    c = o.get("two_resaved")
    want("override two_resaved", c, c is not None and c["text_kept"] and c["props"] == {"J1": ["1:-1", True]}, "#7")
    c = o.get("two_all_dropped_after_resave")
    want("override two_all_dropped_after_resave", c, out(c, "done") and c["conns"] == orig and c["props"] == {}, "#7")
    c = o.get("two_again_same")
    want("override two_again_same", c, out(c, "done") and c["same"], "#7")
    c = o.get("repeat_set")
    want("override repeat_set", c, out(c, "done") and J(c, "J3.2@30.0") == 2 and J(c, "J3.2@32.54") == 2, "#7")
    c = o.get("repeat_dropped")
    note("override repeat_dropped", c, out(c, "done") and c["conns"] == orig, "R14-2: two pads sharing a number restored to the first one's setting")
    c = o.get("diff_resave")
    want("override diff_resave", c, c is not None and c["footprints"] == [] and not c["copper"], "pcb:pad_override")
    c = o.get("edit_move")
    want("override edit_move", c, c is not None and c["edit_outcome"] == "done" and "J2" in c.get("props", {}) and c.get("after_drop") == orig and c.get("props_after_drop") == {}, "pcb:pad_override")

# net ties: findings 10, 11, 14
t = cases("tie14.py")
if t is not None:
    c = t.get("tht_tie")
    want("tie tht_tie", c, out(c, "done") and c["x_gone"] and c["pads"] == {"1": "A", "2": "B", "3": "B"} and c["t1_copper"] == [["B.Cu", [27.0, 20.0], [30.0, 22.0]]], "#10")
    c = t.get("tht_other_net")
    want("tie tht_other_net", c, refused(c), "#10, #14")
    c = t.get("bottom_under_top_pad")
    want("tie bottom_under_top_pad", c, out(c, "done") and len(c["t1_copper"]) == 2 and c["x_gone"], "#10")
    c = t.get("retype_other_parts")
    want("tie retype_other_parts", c, out(c, "done") and c["tracks"] == [["A", "F.Cu"]] and len(c["t1_copper"]) == 1, "#14")
    c = t.get("absorbed_pad_on_tie")
    want("tie absorbed_pad_on_tie", c, refused(c), "#14")
    c = t.get("vias_net_is_absorbed")
    note("tie vias_net_is_absorbed", c, refused(c), "R14-3: absorb_vias_net equal to absorb_net is done, and the absorbed net stays on via pads")

# pcb.toml refusals: findings 8, 12, 15
g = cases("config14.py")
if g is not None:
    for k, c in sorted(g.items()):
        fnd = "#8" if k.startswith("dup") else "#12" if k.startswith(("inf", "nan")) else "#15" if "forbid" in k else "valid input"
        if k.startswith("ok_"):
            want(f"config {k}", c, c["outcome"] in ("done", "rejected") and c["input_same"], fnd)
        else:
            want(f"config {k}", c, refused(c) and not c["out_exists"] and c["input_same"], fnd)

# the badge: findings 1, 2, 14
bd = cases("badge14.py")
if bd is not None:
    c = bd.get("badge_run")
    want("badge run", c, out(c, "done") and c["overlaps"] == [] and c["unfilled"] == [] and sorted(set(c["warnings"])) == ["drc-allowed"]
         and c["stitch"]["GND"] >= 190 and c["tie"].get("copper_segments") == 49 and c["tie"].get("retyped_tracks") == 2 and c["tie"].get("via_pads") == ["3", "4"], "#1, #14")
    c = bd.get("badge_refill")
    want("badge refill", c, c is not None and c["changed"] == {} and c["verify_exit"] == 0, "#1")
    c = bd.get("badge_refill_twice")
    want("badge refill_twice", c, c is not None and c["changed"] == {}, "#1")
    c = bd.get("badge_oracle_j")
    J_ = lambda k: isinstance((c or {}).get(k), list) and c[k][0] != 0 and "J" in c[k][1]
    want("badge oracle_j", c, c is not None and c["keep_floor"][0] == 0 and J_("below_floor") and J_("edge_gnd_smd") and J_("edge_gnd_tht")
         and J_("edge_other_net") and J_("in_keepout") and J_("keepout_edge"), "#2")
    c = bd.get("badge_oracle_d")
    want("badge oracle_d", c, c is not None and c["solid_refilled"][0] != 0 and "D" in c["solid_refilled"][1], "#2")
    note("badge oracle_d no refill", c, c is not None and "D" in c["solid_no_refill"][1], "R14-6: check D reads the saved fill, so a solid pad with a stale relief fill passes")

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1))
sys.exit(1 if fails else 0)
