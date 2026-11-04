"""Runs review 19's probes (confirmation of reviews 17 and 18's closures) and checks the outcome each case must have.
The probes print evidence, one JSON line per case; this file holds the verdicts. Exit 1 on any miss. Cases for notes
in reviews/19_confirmation.md print under "notes" and do not fail the run.

The probes on the M4 project need its fixture flow run to the release once (route included, a few minutes). Set
PCB_R19_BASE to a project folder the flow has finished, or the first such probe runs it into workdir/_flow
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


def note(tag, c, ok, text):
    notes.append(f"{tag}: {'holds' if ok else text}: {json.dumps({k: v for k, v in (c or {}).items() if k != 'case'}, ensure_ascii=False)[:400]}")


def out(c, *o):
    return isinstance(c, dict) and c.get("outcome") in o


def stale(c):
    return (c or {}).get("check", {}).get("stale", [])


s = cases("stale19.py")
if s is not None:
    for k in ("control", "kicad_save", "kicad_save_rerun_save", "kicad_refill_save", "kicad_move_back", "netlist_exported_unchanged", "board_turned_360"):
        c = s.get(k)
        want(f"39/41 harmless: {k} checks done, nothing stale", c, c is not None and out(c["check"], "done") and stale(c) == [])
    for k, cmd in (("pip_dropped", "paste"), ("aperture_moved", "paste"), ("art_point", "art"), ("art_layer", "art"), ("art_moved", "art"),
                   ("sync_value", "sync"), ("sync_lcsc", "sync"), ("sync_pin_dropped", "sync"), ("place_shift_005", "place"),
                   ("place_rot_180", "place"), ("board_moved_001", "place")):
        c = s.get(k)
        want(f"39/41 {k}: stale {cmd}", c, c is not None and cmd in stale(c) and not out(c["check"], "done"))
    c = s.get("record_copied")
    want("44 a record pasted from another run: stale art, no release", c, c is not None and "art" in stale(c) and not out(c["release"], "done"))
    for k in ("aperture_round", "aperture_turned"):
        c = s.get(k)
        note(f"39 {k}", c, c is not None and not out(c["check"], "done"), "the content comparison ignores a pad's shape and angle: U1's paste windows changed passes check")
    c = s.get("pip_margin")
    note("39 a paste margin closing the pin-in-paste openings", c, c is not None and not out(c["release"], "done"), "passes")
    c = s.get("footprint_changed_on_board")
    note("41 R1's land pattern changed on the board", c, c is not None and "sync" in stale(c), "check's circuit comparison does not look at the footprint (DRC and pcb parts find this one)")

f = cases("fab19.py")
if f is not None:
    c = f.get("pour_0_1")
    want("40 a 2-layer pour at the board's 0.1 mm: check finds clearance A GND", c, c is not None and "drc clearance A GND" in c["check"]["unwaived"])
    c = f.get("pour_0_3")
    want("40 control: the pour at 0.3 mm checks done", c, c is not None and out(c["check"], "done"))
    c = f.get("inner_hole_0_2")
    want("40 inner copper 0.2 mm from another net's hole: check finds hole_clearance A GND", c, c is not None and "drc hole_clearance A GND" in c["check"]["unwaived"])
    for k in ("custom_rule_0_5", "netclass_0_5"):
        c = f.get(k)
        want(f"40 {k}: the released fill keeps the board's own 0.5 mm", c, c is not None and out(c["release"], "done") and (c["released_gap_mm"] or 0) >= 0.499)

p = cases("pins19.py")
if p is not None:
    c = p.get("fixture_has_no_c5446_override")
    want("1 pins18.py's edit is a no-op: the fixture has no [parts.C5446] and no pins key", c, c is not None and not c["c5446_table"] and not c["any_pins_key"])
    c = p.get("datasheet_numbered")
    want("1 the datasheet-numbered XC6206 syncs with no override", c, c is not None and out(c["sync"], "done"))
    for k in ("spice_numbered", "partial_map"):
        c = p.get(k)
        want(f"1 {k}: the spice-numbered XC6206 is refused pin-name", c, c is not None and c["sync"]["code"] == "pin-name")
    for k in ("shown_vs_spice_spice_order",):
        c = p.get(k)
        want("1 a schematic following the spice numbers is refused", c, c is not None and c["code"] == "pin-name")
    for k in ("shown_vs_spice_shown_order", "blank_shown_falls_back"):
        c = p.get(k)
        want(f"1 {k}: syncs", c, c is not None and out(c, "done"))
    for k, c in p.items():
        if k.startswith("swap "):
            if k in ("swap GND VSS as VSS GND", "swap OUT OUT1 as OUT1 OUT"):
                note(f"2 {k}", c, c["code"] == "pin-name", "a swap of two distinct pins passes (a synonym, or a number that tells repeated pins apart)")
            else:
                want(f"2 {k} refused", c, c["code"] == "pin-name")
        if k.startswith("same "):
            if k in ("same CS# as ~{CS}", "same CS# as /CS", "same DVDD1 as DVDD"):
                want(f"2 {k}: syncs", c, out(c, "done"))
            else:
                note(f"2 {k}", c, out(c, "done"), "a correct spelling is refused")

sl = cases("slot19.py")
if sl is not None:
    for k in ("slot_rot0_along", "slot_rot0_across", "slot_rot90_along", "slot_rot0_big"):
        c = sl.get(k)
        want(f"3 {k}: the drill runs between the hole points", c, c is not None and c.get("slot_end_error_mm", 9) < 0.005 and c["slot_width_mm"] == c["want_width_mm"])
    c = sl.get("j1_slots")
    want("3 J1's four shell slots run between EasyEDA's hole points", c, c is not None and len(c["errors_mm"]) == 4 and all(e < 0.005 for _, e in c["errors_mm"]))
    c = sl.get("slot_diagonal")
    want("3 a slot across the pad's axes is refused", c, c is not None and out(c["sync"], "refused"))
    for k in ("slot_offset_along", "slot_offset_rot90"):
        c = sl.get(k)
        want(f"47 {k}: a slot off the pad's centre is drilled between its hole points, or refused", c,
             c is not None and (out(c["sync"], "refused") or c.get("slot_end_error_mm", 9) < 0.005), "#47: drilled at the pad centre")
    c = sl.get("slot_offset_along_checked")
    # designer's edit (closure of 47): the slot is now drilled where EasyEDA puts it, so check passing it (N1 aside) is
    # right; the verdict holds when the slot is in place or check stops it
    placed_ok = all((sl.get(k) or {}).get("slot_end_error_mm", 9) < 0.005 for k in ("slot_offset_along", "slot_offset_rot90"))
    want("47 the off-centre slot does not pass check (unconnected_items N1 is the board's own)", c, c is not None and (placed_ok or c["check"]["unwaived"] != ["drc unconnected_items N1"]), "#47: check passes it")
    for k in ("slot_rot45_along", "slot_rot30_along", "slot_rot135_along", "slot_rot30_across", "slot_rot30_big"):
        c = sl.get(k)
        note(f"3 {k}", c, c is not None and c.get("slot_end_error_mm", 9) < 0.005, "a pad off a quarter turn: the slot is drilled along the board's axes")
    for k in ("slot_rot30_big_checked", "slot_rot30_round_checked"):
        c = sl.get(k)
        note(f"3 {k}", c, c is not None and "ring U1.1" not in c["check"]["unwaived"], "every plated custom pad gets a ring finding (its 0.05 mm anchor), right drill or wrong")

t = cases("twopad19.py")
if t is not None:
    c = t.get("m4_led_d_180")
    want("5 LED1 and D1 declared 180 off: a rotation finding each, no release", c, c is not None and {"LED1 rotation", "D1 rotation"} <= set(c["parts"]["findings"]) and not out(c["release"], "done"))
    c = t.get("by_shape_offset_0")
    # designer's edit (closure of 48): a two-pad part matched by shape is now a polarity finding at any offset, so the
    # control is that finding and nothing else
    want("5 control: D9 on an A/K-numbered project footprint at offset 0", c, c is not None and (out(c["parts"], "done") or c["parts"]["findings"] == ["D9 polarity"]))
    c = t.get("by_shape_offset_180")
    want("48 D9 matched by shape, declared 180 off: a finding (its pins are A and K)", c, c is not None and c["parts"]["findings"], "#48: a diode matched by shape passes turned 180")
    c = t.get("m4_resistor_180")
    note("5 a resistor declared 180 off", c, c is not None and not c["parts"]["findings"], "refused: an unpolarised part matched by number needs offset 0 too")
    c = t.get("economic_unknown")
    want("18 note 5: a record with no componentProductType warns economic-unknown", c, c is not None and "economic-unknown" in c["warnings"])

r = cases("resync19.py")
if r is not None:
    c = r.get("lcsc_and_value")
    want("4 R1 5.1k C25905 to 10k C25744: replaced in place", c, c is not None and c["replaced"] == ["R1"] and c["after"]["R1"]["lcsc"] == "C25744" and c["after"]["R1"]["value"] == "10k"
         and all(c["after"]["R1"][k] == c["before"]["R1"][k] for k in ("x", "y", "rot", "layer", "nets")) and "sync" not in c["stale_after"])
    c = r.get("value_only")
    want("4 the value alone: replaced", c, c is not None and c["replaced"] == ["R1"] and c["after"]["R1"]["value"] == "5.10k")
    c = r.get("odd_values")
    want("4 values with quotes and non-ASCII: kept, and check sees no difference", c, c is not None and c["after"]["R2"]["value"] == "5.1kΩ ±1%" and c["after"]["R1"]["value"] == '5.1k "1%"' and "sync" not in c["stale_after"])
    c = r.get("bottom_part")
    want("4 a bottom-side part replaced stays where it is", c, c is not None and c["after"]["TP_FISH"]["layer"] == "B.Cu" and c["after"]["TP_FISH"]["x"] == c["before"]["TP_FISH"]["x"])
    c = r.get("paste_part")
    want("4 U1 replaced loses its paste windows, and check finds paste stale", c, c is not None and c["replaced"] == ["U1"] and "paste" in c["stale_after"])
    c = r.get("routed_rip")
    note("4 a value change on a routed board", c, c is not None and "GND" not in (c["ripped"].get("ripped_nets") or []), "needs --rip, which removes every track and via of the part's nets (GND included)")

d = cases("dnp19.py")
if d is not None:
    c = d.get("dnp_and_not_in_bom")
    want("49 a DNP part and a part not in the BOM are not ordered", c, c is not None and (not out(c["release"], "done") or c["released_bom_has"] == []), "#49: both in the released BOM and CPL")

o = cases("oracle19.py")
if o is not None:
    c = o.get("control")
    want("6 verify_against_v1.py passes the M4 release", c, c is not None and c["exit"] == 0)
    for k in ("pip_removed", "slot_moved_0_1", "ep_full_paste"):
        c = o.get(k)
        want(f"6 verify_against_v1.py fails {k}", c, c is not None and c["exit"] == 1)
    for k in ("pip_shrunk", "slot_turned"):
        c = o.get(k)
        note(f"6 verify_against_v1.py on {k}", c, c is not None and c["exit"] == 1, "passes: openings are compared by centre, holes by middle and diameter")

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1, ensure_ascii=False))
sys.exit(1 if fails else 0)
