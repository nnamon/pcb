"""Runs review 17's probes (confirmation of review 16's closures, milestone M3) and checks the outcome each case
must have. The probes print evidence, one JSON line per case; this file holds the verdicts. Exit 1 on any miss.
Cases for notes in reviews/17_m3_confirmation.md print under "notes" and do not fail the run.

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
        fails.append(f"{script}: exit {r.returncode}, {len(out)} cases: {r.stderr[-800:]}")
    return out


def contracts(c):
    found = []

    def walk(v):
        if isinstance(v, dict):
            if v.get("contract"):
                found.append(v["contract"])
            for x in v.values():
                walk(x)
    walk(c or {})
    return found


def want(tag, c, ok, what=""):
    """`ok` is what the case must show; the output contract must hold in every pcb run the case reports."""
    if c is None:
        fails.append(f"{tag}: case missing")
        return
    if contracts(c):
        fails.append(f"{tag}: output contract {contracts(c)[:2]}")
    (passed if ok else fails).append(f"{tag}{' (' + what + ')' if what and not ok else ''}: {'ok' if ok else json.dumps(c)[:700]}")


def note(tag, c, ok, text):
    notes.append(f"{tag}: {'holds' if ok else text}: {json.dumps({k: v for k, v in (c or {}).items() if k != 'case'})[:400]}")


def out(c, *o):
    return isinstance(c, dict) and c.get("outcome") in o


def oc(c, k):
    return out((c or {}).get(k), "done")


s = cases("stale17.py")
if s is not None:
    c = s.get("control")
    want("control: base project checks clean, records 3 inputs, releases", c, c is not None and out(c["check"], "done") and len(c["records"]) == 3 and out(c["release"], "done"))
    for k in ("version", "label_moved", "paste_dropped", "zone_clearance", "label_removed"):
        c = s.get("stale_" + k)
        want(f"25/29 stale_{k}: found stale, gate refused", c, c is not None and c["stale"] and not oc(c, "gate") and not oc(c, "release"))
    c = s.get("stale_waived")
    want("25/29 a waiver cannot cover stale", c, c is not None and not oc(c, "gate"))
    c = s.get("kicad_save")
    want("stale record survives a pcbnew save, no false stale", c, c is not None and c["records_after"] == c["records_before"] and c["stale"] == [] and c["unwaived"] == [])
    c = s.get("record_moved")
    want("stale record moved on the board still read", c, c is not None and c["stale"] == [])
    c = s.get("label_deleted")
    want("39 the version label deleted after pcb art does not release", c, c is not None and not oc(c, "release"), "#39: the record says art ran; nothing checks its output is on the board")
    c = s.get("paste_undone")
    want("39 U1.57's paste windows undone after pcb paste does not release", c, c is not None and not oc(c, "release"), "#39: full paste on the exposed pad released")
    c = s.get("record_copied")
    note("44 a record copied from another run", c, c is not None and not out(c["check"], "done"), "a record line pasted in is trusted; the board prints v1.0.0 and releases as 1.0.1")
    c = s.get("place_not_applied")
    want("41 a [[place]] entry moved and not applied is stale", c, c is not None and out(c["check_before"], "done") and not out(c["check_after"], "done"), "#41: [[place]] has no inputs record")

r = cases("release17.py")
if r is not None:
    c = r.get("reproducible")
    want("release twice: same files but KiCad's date lines; board untouched", c, c is not None and out(c["r1"], "done") and out(c["r2"], "done") and c["differing"] == [] and c["board_untouched_by_release"])
    c = r.get("fill_stale")
    want("30 a stale fill releases as a fresh fill: no copper at the hole, same as the refilled board", c, c is not None and out(c["stale"]["release"], "done")
         and all(v == 0 for v in c["copper_within_0_1mm_of_hole_mm2"].values()) and c["copper_within_0_1mm_of_hole_mm2"] and out(c["stale_vs_fresh"], "done"))
    c = r.get("rejected_numbered")
    want("35 rejected releases numbered, earlier kept with the owner's file", c, c is not None and c["folders"] == ["short_out.rejected", "short_out.rejected.2", "short_out.rejected.3"]
         and c["owner_file_kept"] and not c["out_exists"])

k = cases("check17.py")
if k is not None:
    c = k.get("netclass_one_net")
    want("28 a netclass clearance on one net survives pcb check", c, c is not None and c["kicad_clearance"] > 0 and c["clearance_found"] >= c["kicad_clearance"])
    c = k.get("own_track_width")
    want("28 a board rule for track width survives pcb check", c, c is not None and c["kicad_track_width"] > 0 and c["track_width_found"] >= c["kicad_track_width"])
    c = k.get("own_clearance_rule")
    want("28 review 16's VBUS 0.5 mm rule survives pcb check", c, c is not None and c["clearance_found"] >= c["kicad_clearance"] > 0)
    c = k.get("netclass_default_truncated")
    want("28 the 0.3 mm Default netclass stops the gate (drc-truncated from the own run)", c, c is not None and c["check"]["code"] == "drc-truncated" and "check_own" in c["check"]["msg"] and not out(c["gate"], "done"))
    c = k.get("own_rule_looser")
    want("28 a board rule looser than the fab's: the fab run still finds the clearance", c, c is not None and out(c["check"], "rejected") and "drc clearance A B" in c["unwaived"])
    c = k.get("drc_exclusions")
    want("DRC exclusions in the project file do not hide a violation", c, c is not None and c["kicad_error_level_after_exclusion"] == 0 and "drc clearance A B" in c["unwaived"])
    c = k.get("pro_ignores_open")
    want("37 unconnected_items ignored in the project file: check still finds the open", c, c is not None and any(u.startswith("drc unconnected_items") for u in c["unwaived"]))
    c = k.get("pro_ignores_short")
    want("37 shorting_items ignored in the project file: check still finds the short", c, c is not None and any(u.startswith("drc shorting_items") for u in c["unwaived"]))

b = cases("readback17.py")
if b is not None:
    c = b.get("npth_round")
    want("30 npth_copper: 0.05 and 0.09 mm found, 0.12 mm not", c, c is not None and [tuple(x) for x in c["hits"]] == [tuple(x) for x in c["want"]])
    c = b.get("npth_slot")
    want("30 npth_copper measures slots as stadiums, upright and turned", c, c is not None and sorted(tuple(x) for x in c["hits"]) == sorted(tuple(x) for x in c["want_near"]))
    c = b.get("pour_own_rules")
    want("40 a 2-layer pour at the board's 0.1 mm does not release", c, c is not None and not out(c["release"], "done"))
    note("40 pcb check on the same pour", c, c is not None and not out(c["check"], "done"), "pcb check passes a fill at 0.1 mm that only the read-back rejects")
    c = b.get("inner_hole_clearance")
    want("40 inner copper 0.3 mm from another net's component hole in the released files", c, c is not None and not (out(c["release"], "done") and (c["in1_gap_to_hole_mm"] or 1) < 0.3 - 1e-3),
         "#40: release fills with the board's rules; the fab run judged a fill made with the fab's")
    c = b.get("slack_widths")
    want("32 read-back finds 0.149 and 0.145 mm tracks, not 0.15 mm", c, c is not None and c["trace_y"] == [1.0, 5.0])
    note("32 silkscreen lines of 0.13 and 0.14 mm both found", c, c is not None and -9.0 in c["silk_y"] and -5.0 in c["silk_y"], "a 0.13 or 0.14 mm silkscreen line passes")

m = cases("compare17.py")
if m is not None:
    for kk, o in (("slot_turned_90", "rejected"), ("slot_turned_10", "rejected"), ("slot_reversed", "done")):
        c = m.get(kk)
        want(f"31 {kk}: {o}", c, out(c, o))
    c = m.get("slot_turned_3")
    note("31 a slot turned 3 degrees", c, out(c, "rejected"), "a 3 degree turn compares equal")
    c = m.get("route_vs_alternate")
    want("routed slots against G85 slots differ", c, out(c, "rejected"))
    for kk in ("route_slot_turned", "route_slot_deleted"):
        c = m.get(kk)
        note(f"42 {kk}", c, out(c, "rejected", "refused"), "KiCad's route-format slots are skipped by the Excellon reader: two routed sets compare done with a slot turned or gone")
    for kk in ("unread_second_fcu", "unread_comment_layer", "unread_unnamed_gbr_no_x2"):
        c = m.get(kk)
        want(f"34 {kk}: refused", c, out(c, "refused") and c["code"] == "gerber-set")
    for kk in ("unread_inner_g1_no_x2", "unread_drill_as_txt"):
        c = m.get(kk)
        note(f"43 {kk}", c, out(c, "refused", "rejected"), "a file the comparison does not read is not refused (name outside .gbr/.g??/.gm1, or a drill file not .drl/.xln/.exc)")
    c = m.get("unread_third_drl")
    want("34 a third .drl file is read", c, out(c, "rejected"))

g = cases("gate17.py")
if g is not None:
    c = g.get("multiline_max")
    want("33 a waiver's max raised after a header-shaped line in a string: stale", c, c is not None and c["fresh_before"] == [True] and c["fresh_after"] == [False])
    c = g.get("layout_only")
    want("33 comments, table order and key order leave the gate fresh", c, c is not None and c["fresh_before"] == [True] and c["fresh_after"] == [True])
    c = g.get("why_changed")
    want("33 a waiver's reason reworded: stale", c, c is not None and c["fresh_after"] == [False])

i = cases("import17.py")
if i is not None:
    c = i.get("silk_line_rect")
    want("36 silkscreen lines and rectangles where the circuit puts them (turned, bottom, board)", c, out(c, "done") and c["missing"] == [] and c["wanted"] == 15)
    note("45 a filled silkscreen rectangle", c, c is not None and any(x[1] is True for x in c.get("filled_rect", [])), "is_filled is dropped: imported as a 0.1 mm outline, no warning")
    c = i.get("rename_through_pad_checked")
    want("38 a renamed trace through another net's pad stops at pcb check", c, c is not None and out(c["imported"], "done") and "drc shorting_items A B" in c["unwaived"])

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1))
sys.exit(1 if fails else 0)
