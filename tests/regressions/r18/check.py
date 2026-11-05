"""Runs review 18's probes (milestone M4, first review) and checks the outcome each case must have. The probes print
evidence, one JSON line per case; this file holds the verdicts. Exit 1 on any miss. Notes print under "notes" and
do not fail the run.

Usage: python3 check.py pcb-binary workdir [probe.py ...]

golden18.py, parts18.py and release18.py need the fixture flow run to the end; set PCB_R18_BASE to such a project
folder, or this runner runs the flow (fixture.toml's steps, Freerouting from PCB_FREEROUTING_JAR) into workdir/flow.
live18.py uses the network and runs only when named.
"""
import json
import os
import shutil
import subprocess
import sys
import tomllib

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
only = sys.argv[3:]
env = dict(os.environ, PCB_BIN=pcb)
fails, notes, passed = [], [], []
FX = os.path.join(here, "..", "..", "fixtures", "paddle_keyer_m4")


def base():
    if env.get("PCB_R18_BASE"):
        return env["PCB_R18_BASE"]
    p = os.path.join(work, "flow", "project")
    if not os.path.exists(os.path.join(p, "release")):
        if os.path.exists(os.path.join(work, "flow")):
            shutil.rmtree(os.path.join(work, "flow"))
        shutil.copytree(FX, p)
        for i, step in enumerate(tomllib.load(open(os.path.join(FX, "fixture.toml"), "rb"))["flow"]["steps"]):
            line = step.replace("{p}", p).replace("{w}", os.path.join(work, "flow", f"w{i}"))
            r = subprocess.run([pcb, "--json", *line.split()], capture_output=True, text=True)
            if r.returncode:
                fails.append(f"flow step {i} ({line[:40]}): exit {r.returncode}")
                break
    env["PCB_R18_BASE"] = p
    env["PCB_R18_RELEASE"] = os.path.join(p, "release")
    return p


def cases(script, needs_base=False, explicit=False):
    if (only and script not in only) or (explicit and script not in only):
        return None
    if needs_base:
        base()
        env.setdefault("PCB_R18_RELEASE", os.path.join(env["PCB_R18_BASE"], "release"))
    r = subprocess.run([sys.executable, "-W", "ignore", os.path.join(here, script), os.path.join(work, script[:-3])], capture_output=True, text=True, env=env)
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
    (passed if ok else fails).append(f"{tag}{' (' + what + ')' if what and not ok else ''}: {'ok' if ok else json.dumps(c)[:600]}")


def note(tag, c, ok, text):
    notes.append(f"{tag}: {'holds' if ok else text}: {json.dumps({k: v for k, v in (c or {}).items() if k != 'case'})[:400]}")


def out(r, *o):
    return isinstance(r, dict) and r.get("outcome") in o


p = cases("pins18.py")
if p is not None:
    c = p.get("c5446_fields")
    want("control: C5446's displayed pin numbers match the datasheet, its spice numbers do not", c,
         c is not None and {x["number"]: x["name"] for x in c["pins"]} == {"1": "GND", "2": "Vout", "3": "Vin"})
    c = p.get("spice_numbered_sync")
    want("1 a schematic numbered by the spice field (VIN on pad 2) is refused", c, c is not None and out(c["r"], "refused") and c["r"]["code"] == "pin-name",
         "#1: sync accepts VBUS on the XC6206's VOUT pad")
    c = p.get("datasheet_numbered_sync")
    note("1 the datasheet-numbered schematic passes without [parts.C5446] pins", c, c is not None and out(c["r"], "done"), "refused: the pin map is read from the spice field")
    for a, b in (("D+", "D-"), ("IN+", "IN-"), ("Q", "~Q"), ("VREF+", "VREF-"), ("CS", "CS#")):
        c = p.get(f"swap_{a}_{b}")
        want(f"2 a swap of {a} and {b} is refused", c, c is not None and out(c["r"], "refused") and c["r"]["code"] == "pin-name", "#2: names compared without sign or active-low mark")
    for a, b in (("SDA", "SCL"), ("CC1", "CC2"), ("A", "K")):
        c = p.get(f"swap_{a}_{b}")
        want(f"control: a swap of {a} and {b} is refused", c, c is not None and out(c["r"], "refused"))

e = cases("easyeda18.py")
if e is not None:
    c = e.get("fixture_parts")
    want("control: the fixture's 48 parts match EasyEDA's pad outlines, holes and slots", c, c is not None and c["n_misses"] == 0 and c["parts"] == 48)
    for k in ("rect_30", "rect_90_tht", "polygon_hole", "oval_slot_long", "oval_slot_turned", "bottom_smd"):
        c = e.get(f"synthetic_{k}")
        want(f"control: synthetic {k}", c, c is not None and out(c["sync"], "done") and c["misses"] == [])
    for k in ("round_slot_x", "rect_slot_across"):
        c = e.get(f"synthetic_{k}")
        want(f"3 synthetic {k}: the slot runs where EasyEDA's hole points put it", c, c is not None and (not out(c["sync"], "done") or c["misses"] == []), "#3: slot direction guessed from the pad's longer side")
    c = e.get("synthetic_oval_45")
    note("oval pad at 45 degrees", c, c is not None and out(c["sync"], "done"), "refused (footprint): a turned oval pad is not converted")
    c = e.get("synthetic_unplated_pad")
    note("unplated pad with copper", c, c is not None and out(c["sync"], "done"), "refused (footprint): an EasyEDA NPTH drawn as an unplated pad is not converted")

s = cases("sync18.py")
if s is not None:
    c = s.get("lcsc_change")
    want("4 a part's new LCSC code and value reach the board on re-sync", c, c is not None and c["after"]["lcsc"] == "C25744" and c["after"]["value"] == "10k",
         "#4: same package, so the footprint, LCSC and value are kept")

q = cases("parts18.py", needs_base=True)
if q is not None:
    c = q.get("control")
    want("control: parts on the flow's board", c, c is not None and out(c["r"], "done") and c["LED1"]["rotation_offset_deg"] == 0)
    c = q.get("two_pad_180")
    want("5 a 180 degree rotation offset on a polarised two-pad part is a finding", c, c is not None and out(c["r"], "rejected"), "#5: two-pad turns compared modulo 180")
    c = q.get("two_pad_offset_009")
    note("two-pad CPL offset 0.09 mm off", c, c is not None and out(c["r"], "rejected"), "passes: the offset tolerance for two-pad parts is 0.1 mm")
    for k in ("qfn_90", "qfn_180", "uson8_180", "sot23_180_renumbered"):
        c = q.get(k)
        want(f"control: by-shape {k} solves its true turn", c, c is not None and c["solved"]["rotation_offset_deg"] == c["true_offset"])
    c = q.get("crystal_180")
    note("by-shape match on a pattern with two equal turns", c, c is not None and (out(c["r"], "rejected") or c["solved"]["rotation_offset_deg"] == 180),
         "the first turn tried is taken, with no warning that the turn is ambiguous")

pl = cases("place18.py")
if pl is not None:
    c = pl.get("bottom_vs_kicad_flip")
    ok = c is not None and out(c["place"], "done") and all(all("mirrored" in x for x in v) for v in c["diffs"].values())
    want("control: bottom-side pads, angles, layers and drills equal KiCad's own flip", c, ok)
    note("bottom-side text mirrored", c, c is not None and all(v == [] for v in c["diffs"].values()), "reference text on the back is not mirrored (KiCad mirrors it)")

g = cases("golden18.py", needs_base=True)
if g is not None:
    c = g.get("golden_copper")
    want("control: every v1.0.0 hole at the same place and size", c, c is not None and c["n_holes_unmatched"] == 0)
    want("control: every M4 paste opening holds a v1.0.0 one", c, c is not None and c["n_empty"] == 0)
    want("6 v1.0.0's pin-in-paste openings on J1's shell legs are in the M4 release", c, c is not None and c["gold_paste_with_no_m4_pad"] == [],
         "#6: J1.13 and J1.14 have no paste; nothing checks THT pads of machine-placed parts")

rl = cases("release18.py", needs_base=True)
if rl is not None:
    c = rl.get("economic_after_gate")
    want("control: release re-checks the parts cache", c, c is not None and out(c["r"], "rejected", "refused"))
    c = rl.get("two_pad_180_release")
    want("5 LED1 and D1 are not released turned 180 degrees from v1.0.0", c, c is not None and not (out(c["release"], "done") and c["cpl_rotation"].get("LED1") != c["v1_rotation"]["LED1"]),
         "#5: released with LED1 and D1 reversed")

lv = cases("live18.py", explicit=True)
if lv is not None:
    c = lv.get("live")
    note("live fetch of three parts", c, c is not None and out(c["r"], "done") and all(isinstance(v, dict) and v["footprint_same"] for v in c["parts"].values()), "live data differs from the cache")

print(json.dumps({"passed": len(passed), "failed": len(fails), "fails": fails, "notes": notes}, indent=1))
sys.exit(1 if fails else 0)
