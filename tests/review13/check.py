"""Runs review 13's probes and checks the outcome each case must have (the probes print evidence, one JSON line per
case; this file holds the verdicts). Exit 1 on any miss. Cases marked NOTE in reviews/13_m2.md are printed under
"notes" and do not fail the run.

Usage: python3 check.py pcb-binary workdir
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
env = dict(os.environ, PCB_BIN=pcb)
fails, notes, passed = [], [], []


def cases(script):
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
    (passed if ok else fails).append(f"{tag}{' (' + finding + ')' if finding and not ok else ''}: {json.dumps(c)[:400] if not ok else 'ok'}")


def note(tag, c, text):
    notes.append(f"{tag}: {text}: {json.dumps({k: v for k, v in (c or {}).items() if k not in ('case', 'contract')})[:300]}")
    if c and c.get("contract"):
        fails.append(f"{tag}: output contract {c['contract']}")


def done(c):
    return c is not None and c.get("outcome") == "done"


def refused(c, code=None):
    return c is not None and c.get("outcome") == "refused" and (code is None or c.get("code") == code)


# stitching
s = cases("stitch13.py")
want("stitch via_in_pad", s.get("via_in_pad"), done(s.get("via_in_pad")) and s["via_in_pad"]["n_on_pad"] == 0, "#3")
want("stitch keepout_via", s.get("keepout_via"), done(s.get("keepout_via")) and s["keepout_via"]["vias_in_keepout"] == 0, "#4")
c = s.get("two_entries")
want("stitch two_entries", c, c is not None and (refused(c, "config") or (done(c) and c["duplicate_via_uuids"] == 0)), "#9")
note("stitch one_layer", s.get("one_layer"), "NOTE #13: no via anywhere, no warning")
c = s.get("margins")
want("stitch margins", c, done(c) and all(v[0] >= 0.3 - 1e-3 for v in c["worst"].values()) and len(c["worst"]) >= 6)
c = s.get("pitch_below_size")
want("stitch pitch_below_size", c, c is not None and c.get("outcome") in ("refused", "rejected"))
for k in ("pitch_tiny", "rect_inf", "rect_huge"):
    want(f"stitch {k}", s.get(k), refused(s.get(k), "config"), "#5")
c = s.get("resave")
want("stitch resave", c, done(c) and c.get("outcome2") == "done" and c["removed_vias"] == c["first"] == c["second"] and c["removed_zones"] == 2 and c["duplicate_places"] == 0)

# features
f = cases("feature13.py")
c = f.get("keepout_flags")
ka, kb = (c or {}).get("keepouts", {}).get("pcb:keepout:a", {}), (c or {}).get("keepouts", {}).get("pcb:keepout:b", {})
want("feature keepout_flags", c, done(c) and ka.get("layers") == ["F.Cu", "In2.Cu"] and ka.get("rect") == [38.5, 28.5, 51.5, 37.5]
     and (ka.get("no_tracks"), ka.get("no_vias"), ka.get("no_fps"), ka.get("no_pour"), ka.get("no_pads")) == (True, True, True, False, False)
     and kb.get("layers") == ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"] and (kb.get("no_pour"), kb.get("no_tracks"), kb.get("no_vias"), kb.get("no_fps")) == (True, False, False, False))
c = f.get("keepout_layer_clip")
want("feature keepout_layer_clip", c, done(c) and (c.get("p_fill_inside_inner_keepout_on_fcu") or 0) > 15, "#6")
c = f.get("zone_settings")
z = (c or {}).get("zones", {})
want("feature zone_settings", c, z.get("pcb:zone:GND:In1.Cu", {}).get("clearance") == 0.45 and z["pcb:zone:GND:In1.Cu"]["gap"] == 0.4 and z["pcb:zone:GND:In1.Cu"]["spoke"] == 0.6
     and z["pcb:zone:GND:In1.Cu"]["priority"] == 7 and z["pcb:zone:GND:In1.Cu"]["min_width"] == 0.33 and z["pcb:zone:GND:In1.Cu"]["connect"] == 2
     and z.get("pcb:zone:GND:In2.Cu", {}).get("connect") == 0 and z.get("pcb:zone:GND:B.Cu", {}).get("connect") == 1 and all(v["islands"] == 0 for v in z.values()))
c = f.get("fill_priority")
want("feature fill_priority", c, done(c) and c["p_area"] > 5 and c["q_area"] < 0.5 and c["p_outside_board"] == 0)
c = f.get("pad_override")
want("feature pad_override", c, done(c) and c.get("conn") == {"1": 0, "2": 2})
want("feature pad_override_dropped", c, done(c) and c.get("conn_after_dropped") == {"1": -1, "2": -1}, "#7")
c = f.get("changed")
want("feature changed", c, done(c) and c.get("removed") == 5 and c.get("names") == ["mine", "pcb:zone:GND:F.Cu"] and c.get("hand_via") and c.get("hand_zone_text_kept"))
for k in ("dup_zone", "dup_keepout", "dup_layer"):
    c = f.get(k)
    want(f"feature {k}", c, c is not None and (refused(c, "config") or (done(c) and c.get("duplicate_zone_uuids") == 0)), "#8")
note("feature forbid_nothing", f.get("forbid_nothing"), "NOTE #15: a keep-out that forbids nothing is accepted")
c = f.get("same_priority_refill")
want("feature same_priority_refill", c, done(c) and all(abs(c["saved"][n] - c["refilled"][n]) < 0.5 for n in c.get("nets", [])), "#1")

# net ties
t = cases("tie13.py")
for k in ("turn_0_top", "turn_90_top", "turn_30_top", "turn_0_bottom", "turn_135_bottom"):
    c = t.get(k)
    want(f"tie {k}", c, done(c) and c["copper_plus_tracks_match"] and c["via_pads_match"] and c["x_gone"] and c["again_same"])
note("tie third_net", t.get("third_net"), "NOTE #14: a run between pads of two other footprints became tie copper; only the gate stops it")
note("tie junction", t.get("junction"), "NOTE #14: runs ending at a junction become copper, never retyped")
note("tie absorbed_has_pad", t.get("absorbed_has_pad"), "NOTE #14: an absorbed net with pads stays on the board")
c = t.get("vias_only")
want("tie vias_only", c, c is not None and {k: v[:3] for k, v in c.get("pads", {}).items() if k in ("3", "4", "5")} == {"3": [29.0, 19.5, "B"], "4": [29.0, 20.5, "B"], "5": [31.0, 21.0, "B"]})
c = t.get("under_pad")
want("tie under_pad", c, done(c) and c.get("bcu_tracks") == ["B", "B"] and c.get("bcu_copper") == [], "#10")
want("tie vias_net_missing", t.get("vias_net_missing"), refused(t.get("vias_net_missing"), "config"), "#11")

# refusals, paths, allowance
r = cases("refuse13.py")
for k, code in [("unknown_key", "config"), ("zone_clearance_nan", "config"), ("min_width_zero", "config"), ("connect_bad", "config"), ("fill_layer_missing", "config"),
                ("keepout_layer_missing", "config"), ("keepout_layers_word", "config"), ("stitch_net_missing", "config"), ("stitch_drill_ge_size", "config"),
                ("allow_max_negative", "config"), ("width_rule_unknown_net", "config"), ("pad_override_no_dot", "config"), ("schema_2", "config"), ("no_pcb_toml", "config"),
                ("board_missing", None), ("out_is_folder", "usage"), ("out_folder_missing", "usage"), ("work_is_file", "usage"), ("out_is_candidate", "output-in-work")]:
    c = r.get(k)
    want(f"refuse {k}", c, refused(c, code) and not c["input_changed"] and (k == "out_is_candidate" or not c["out_exists"]))
for k in ("zone_clearance_inf", "thermal_gap_inf", "keepout_rect_inf"):
    note(f"refuse {k}", r.get(k), "NOTE #12: an infinite value passes the checks and the run fails in KiCad")
for k in ("allow_unknown_net", "allow_unknown_kind"):
    note(f"refuse {k}", r.get(k), "NOTE #16: an allowance naming no net or kind KiCad has is accepted")
c = r.get("project_as_file")
want("refuse project_as_file", c, done(c))
c = r.get("out_default_overwrites")
want("refuse out_default_overwrites", c, done(c) and c["files"] == ["board.kicad_pcb"])
c = r.get("rejected_onto_input")
want("refuse rejected_onto_input", c, c is not None and c.get("outcome") == "rejected" and not c["input_changed"] and "board.rejected.kicad_pcb" in c["files"])
A = lambda k: r.get(k)
want("allow control", A("allow_control"), done(A("allow_control")))
want("allow none", A("allow_none"), (A("allow_none") or {}).get("outcome") == "rejected")
for k, n in (("allow_at_max_1", 1), ("allow_at_max_2", 1)):
    c = A(k)
    want(f"allow {k}", c, done(c) and len(c["allowed"]) == n and "drc-allowed" in c["warnings"])
want("allow above_max_2", A("allow_above_max_2"), (A("allow_above_max_2") or {}).get("outcome") == "rejected")
c = A("allow_with_real_regression")
want("allow with_real_regression", c, c is not None and c.get("outcome") == "rejected" and c["allowed"] == ["unconnected_items GND: 0 -> 1"] and c["regressions"] == ["unconnected_items AGND: 0 -> 1"])
want("allow kind_not_grown", A("allow_kind_not_grown"), done(A("allow_kind_not_grown")) and not A("allow_kind_not_grown")["allowed"])
want("allow wrong_net", A("allow_wrong_net"), (A("allow_wrong_net") or {}).get("outcome") == "rejected")
want("allow typo", A("allow_unknown_kind_typo"), (A("allow_unknown_kind_typo") or {}).get("outcome") == "rejected")
note("allow any_nets_max_1", A("allow_any_nets_max_1"), "NOTE #16: with no nets, max applies to each net set apart")
note("allow ratchet_2", A("ratchet_2"), "NOTE #16: each run may add max over its own input")

# fill flag
fl = cases("fill13.py")
c = fl.get("pcbnew_writes_flag")
want("fill pcbnew_writes_flag", c, done(c) and c["pcbnew_flags"] == c["written_flags"] >= 1)
c = fl.get("flag_meaning")
want("fill flag_meaning", c, c is not None and c["flag"]["is_filled"] and not c["noflag"]["is_filled"] and c["flag"]["area"] == c["noflag"]["area"] and c["flag"]["drc"] == c["noflag"]["drc"])
c = fl.get("check_splice_masks_shape_fill")
want("fill check_splice_masks_shape_fill", c, c is not None and c.get("prefix_identical") is False, "#17")

# the badge
b = cases("badge13.py")
c = b.get("badge_zone")
# the via count follows the fills, which follow the fill priorities (202 at review, 203 once every overlap had its
# own priority, review 13 closure); the fixture's floor is 190
want("badge zone", c, done(c) and sorted(c["allowed"]) == ["clearance <no net> NFC_AC1: 0 -> 2", "starved_thermal GND: 0 -> 2"] and list(c["stitch"]) == ["GND"] and c["stitch"]["GND"] >= 190
     and c["zone_kinds"] == {"keepout": 2, "zone": 4, "fill": 34} and c["before"] == 144 and c["after"] == 27)
want("badge verify_zones", b.get("badge_verify_zones"), (b.get("badge_verify_zones") or {}).get("exit") == 0)
c = b.get("badge_allowed_items")
st = [i["items"][1] for i in (c or {}).get("items", {}).get("starved_thermal", [])]
cl = [i["items"] for i in (c or {}).get("items", {}).get("clearance", [])]
want("badge allowed_items", c, sorted(st) == ["PTH pad 2 [GND] of J701", "PTH pad 4 [GND] of J102"] and len(cl) == 2 and all("PTH pad 3 [NFC_AC1] of L601" in x for x in cl))
c = b.get("badge_stitch")
want("badge stitch", c, c is not None and c["n"] >= 190 and c["n"] == (b.get("badge_zone") or {}).get("stitch", {}).get("GND") and c["n_on_pad"] == 0 and c["in_keepout"] == 0 and not c["near_other_pad"])
c = b.get("badge_oracle_stitch")
want("badge oracle_stitch", c, c is not None and c["removed_exit"] not in (0, None) and c["on_pad_exit"] not in (0, None), "#2")
c = b.get("badge_refill")
want("badge refill", c, c is not None and c["verify_exit"] == 0 and not c["changed_areas"], "#1")
c = b.get("badge_j102_solid")
want("badge j102_solid", c, c is not None and c.get("verify_exit") == 1 and len(c.get("d_fails", [])) == 2)

print(json.dumps({"ok": not fails, "failed": fails, "notes": notes, "passed": len(passed)}, indent=1))
sys.exit(0 if not fails else 1)
