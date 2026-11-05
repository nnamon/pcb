"""Runs review 20's probes (confirmation of review 19's closures, and the areas they changed) and checks the outcome
each case must have. The probes print evidence, one JSON line per case; this file holds the verdicts. Exit 1 on any
miss. Cases for notes in docs/reviews/20_confirmation.md print under "notes" and do not fail the run.

The probes on the M4 project need its fixture flow run to the release once (route included, a few minutes). Set
PCB_R20_BASE to a project folder the flow has finished, or the first such probe runs it into workdir/_flow
(PCB_FREEROUTING_JAR must name Freerouting 2.5.0).

Usage: python3 check.py pcb-binary workdir [probe.py ...]
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
only = sys.argv[3:]
os.makedirs(work, exist_ok=True)
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
    if c is None:
        fails.append(f"{tag}: case missing")
        return
    if contracts(c):
        fails.append(f"{tag}: output contract {contracts(c)[:2]}")
    (passed if ok else fails).append(f"{tag}{' (' + what + ')' if what and not ok else ''}: {'ok' if ok else json.dumps(c, ensure_ascii=False)[:700]}")


def note(tag, c, ok, what):
    if c is None:
        notes.append(f"{tag}: case missing")
    elif not ok:
        notes.append(f"{tag}: {what}")


def out(r, o):
    return (r or {}).get("outcome") == o


s = cases("slot20.py")
if s is not None:
    for k in ("off_along_r0", "off_along_r90", "off_along_r180", "off_along_r270", "off_across_r0", "off_r90_board90", "off_r0_board30",
              "off_r270_board180", "off_slot_across_pad", "off_r0_bottom", "thin_ring", "broken_ring", "centred_r0", "project_fp_kicad_offset"):
        c = s.get(f"slot_{k}")
        ok = c is not None and out(c["sync"], "done") and c.get("local_slot_end_error_mm", 9) < 0.005 and c.get("local_copper_error_mm2", 9) < 0.001 \
            and c.get("board_slot_end_error_mm", 0) < 0.005 and c.get("board_copper_error_mm2", 0) < 0.001
        want(f"47 {k}: drill and copper where EasyEDA puts them", c, ok)
        u = (c or {}).get("parts", {}).get("solved") or []
        want(f"47 {k}: offset solver finds turn 0, offset 0, residual 0", c, c is not None and (k == "off_r0_bottom" or (
            len(u) == 1 and u[0]["residual_mm"] < 0.001 and u[0]["rotation_offset_deg"] == 0 and u[0]["cpl_offset_mm"] == [0.0, 0.0] and not c["parts"]["findings"])))
    for k in ("thin_ring", "broken_ring"):
        c = s.get(f"slot_{k}")
        want(f"47 {k}: check stops a slot whose offset thins the ring", c, c is not None and any("annular" in x or x.startswith("ring") for x in c["check"]["unwaived"]))
    for k in ("rect_rot30", "polygon_rot0"):
        c = s.get(f"slot_{k}")
        want(f"51 {k}: a slot in a custom pad is refused", c, c is not None and out(c["sync"], "refused") and c["sync"]["code"] == "footprint")
    c = s.get("slot_round_rot30")
    note("51 round hole in a pad turned 30 degrees", c, c is not None and "ring U1.1" not in c["check"]["unwaived"], "a plated custom pad still gets a ring finding from its 0.05 mm anchor")

p = cases("polarity20.py")
if p is not None:
    c = p.get("m4_no_polarity")
    want("48 the M4 board has no polarity finding", c, c is not None and out(c["parts"], "done") and not c["parts"]["findings"])
    for off in (0, 180):
        c = p.get(f"d9_by_shape_{off}")
        want(f"48 D9 on an A/K footprint at offset {off}: a finding, no release", c, c is not None and "D9 polarity" in c["parts"]["findings"] and not out(c["release"], "done"))
    c = p.get("r9_by_shape")
    note("48 a resistor on an A/B footprint", c, c is not None and not c["parts"]["findings"], "a polarity finding for a part with no polarity, which no waiver can cover")
    for k in ("soic_ep_turned180", "qfn_ep_turned90"):
        c = p.get(k)
        want(f"58 {k}: a part matched by shape whose pads repeat under a turn is not released at the wrong turn", c,
             c is not None and (c["parts"]["findings"] or not out(c.get("release"), "done")), "#58: released with the part turned")
    c = p.get("soic_ep_turned90_declared0")
    want("58 control: an SOIC turned 90 and declared 0 is a rotation finding", c, c is not None and "U9 rotation" in c["parts"]["findings"])
    c = p.get("soic_ep_not_turned")
    # designer's edit (closure of 58): a pattern that fits at two turns is a `turn` finding whatever is declared, so the
    # control is that finding alone, or a release
    want("58 control: the SOIC not turned releases", c, c is not None and (out(c.get("release"), "done") or c["parts"]["findings"] == ["U9 turn"]))

d = cases("dnp20.py")
if d is not None:
    c = d.get("flags_set")
    want("49 DNP and not-in-BOM flags reach the board; copper kept", c, c is not None and out(c["sync"], "done") and c["attrs"]["C2"] == ["not_in_bom"]
         and set(c["attrs"]["C3"]) == {"dnp", "not_in_bom", "not_in_pos"} and c["attrs"]["C6"] == [] and c["segments_before"] == c["segments_after"])
    want("49 the release leaves C2 and C3 out of the BOM and CPL, C6 in", c, c is not None and out(c["release"], "done")
         and "C2" not in c["bom_has"] and "C3" not in c["cpl_has"] and "C6" in c["bom_has"])
    c = d.get("flags_cleared")
    want("59 a flag cleared in the schematic is cleared on the board, or check stops it", c, c is not None and (c["attrs"]["C2"] == [] or c["check"]["unwaived"]),
         "#59: C2 stays out of the BOM after in_bom is set back")
    for k in ("hand_exclude_from_bom", "hand_exclude_from_pos"):
        c = d.get(k)
        want(f"59 {k}: a fitted part dropped by hand in pcbnew is stopped", c, c is not None and (c["check"]["unwaived"] or "C7" in (c["bom_has"] or [])),
             "#59: check, gate and release pass with C7 left out")
    c = d.get("dnp_field_no")
    want("60 a user field DNP = No does not make the part DNP", c, c is not None and c["attrs"]["C5"] == [], "#60: C5 left out of the BOM and CPL")
    c = d.get("schematic_changed_after_gate")
    want("61 a schematic changed after the gate stops the release", c, c is not None and not out(c["release"], "done"),
         "#61: the gate stays fresh and the release orders the old circuit")
    c = d.get("not_on_board")
    note("49 a part excluded from the board", c, c is not None and c["netlist"]["C4"] is None and out(c["sync"], "refused"), "KiCad leaves it out of the netlist; sync removes it")

r = cases("resync20.py")
if r is not None:
    for k in ("value_only", "lcsc_same_package"):
        c = r.get(k)
        want(f"55 {k}: replaced without --rip, copper kept, check and release pass", c, c is not None and out(c["sync"], "done") and c["replaced"] == ["R1"]
             and c["segments_before"] == c["segments_after"] and out(c["check"], "done") and out(c["release"], "done"))
    c = r.get("lcsc_same_title_other_pads")
    note("55 a part with other pads under the same package title", c, c is not None and not out(c["sync"], "done"),
         "sync keeps the copper (same lib id, same nets) though the pads moved 0.2 mm; DRC is left to judge")
    c = r.get("lcsc_other_title_other_pads")
    want("55 control: another package title needs --rip", c, c is not None and c["sync"]["code"] == "sync-copper")

t = cases("stale20.py")
if t is not None:
    for k in ("load_save", "j1_90_back", "u1_45_back", "u1_180_twice", "j1_360", "r1_flip_back", "all_90_back", "all_30x12"):
        c = t.get(f"harmless_{k}")
        want(f"50 harmless save {k}: nothing stale", c, c is not None and out(c["check"], "done") and not c["check"]["stale"])
    for k in ("window_round", "window_turned45", "window_roundrect", "window_turned90"):
        c = t.get(f"edited_{k}")
        want(f"50 {k}: stale paste", c, c is not None and c["windows"] == 4 and "paste" in c["check"]["stale"])

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1, ensure_ascii=False))
sys.exit(1 if fails else 0)
