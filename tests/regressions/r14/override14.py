"""Review 14: pad overrides and the `pcb:pad_override` property (review 13, finding 7): an override changed, one of two
dropped, a KiCad re-save between runs, a pad with its own setting, repeated pad numbers, and what diff and edit make
of the property. One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 override14.py workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import r14lib as L  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

THT = lambda x, y, num="1": {"num": num, "at": (x, y), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}
BASE = {"layers": 2, "fps": [
    {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
    {"ref": "J1", "at": (20, 20), "pads": [THT(20, 20, "1"), THT(22.54, 20, "2")]},
    {"ref": "J2", "at": (40, 20), "pads": [THT(40, 20, "1"), THT(42.54, 20, "2")]},
    {"ref": "J3", "at": (30, 30), "pads": [THT(30, 30, "2"), THT(32.54, 30, "2"), THT(35.08, 30, "3")]}]}
# J1 pad 2 has its own setting (thermal); J3's first pad "2" has its own setting (none), the second inherits
OWN = """
for f in b.GetFootprints():
    for p in f.Pads():
        if f.GetReference() == "J1" and p.GetNumber() == "2":
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        if f.GetReference() == "J3" and p.GetNumber() == "2" and abs(p.GetPosition().x - mm(30)) < 1000:
            p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)
"""
ZONES = '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\n'


def ov(*pairs):
    return "".join(f'\n[[pad_override]]\npad = "{p}"\nzone_connection = "{c}"\n' for p, c in pairs)


def conns(path):
    r = L.inspect(path)
    return {f"{ref}.{p['num']}@{round(p['x'], 2)}": p["conn"] for ref in ("J1", "J2", "J3") for p in r["fps"][ref]["pads"]}


def props(path):
    """{ref: (value, hidden)} of every pcb:pad_override property, read with pcbnew."""
    code = r'''
import sys, json, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
r = {}
for f in b.GetFootprints():
    fl = f.GetField("pcb:pad_override") if hasattr(f, "GetField") else None
    if fl is not None:
        r[f.GetReference()] = [fl.GetText(), not fl.IsVisible()]
print("JSON" + json.dumps(r))
'''
    o = subprocess.run([sys.executable, "-c", code, path], capture_output=True, text=True)
    if o.returncode:
        return {"error": o.stderr[-300:]}
    return json.loads([ln for ln in o.stdout.splitlines() if ln.startswith("JSON")][-1][4:])


def step(d, prev, toml, i):
    """A run in a new folder on `prev`'s board with `toml`; returns (reply, problems, output)."""
    s = os.path.join(d, f"step{i}")
    os.makedirs(s)
    shutil.copy(prev, os.path.join(s, "board.kicad_pcb"))
    pro = os.path.splitext(prev)[0] + ".kicad_pro"
    shutil.copy(pro if os.path.exists(pro) else os.path.join(d, "board.kicad_pro"), os.path.join(s, "board.kicad_pro"))
    L.write_toml(s, 2, toml)
    v, c, prob, out = L.zone(s)
    return v, prob, (v.get("data") or {}).get("written") or out


d = L.build(os.path.join(work, "seq"), BASE, ZONES, OWN)
orig = conns(os.path.join(d, "board.kicad_pcb"))
L.emit("original", contract=[], conns=orig)

# 1. changed, not dropped: J1.1 none -> solid -> dropped; J1.2 (own thermal) solid -> dropped
seq = [("none_then", ov(("J1.1", "none"), ("J1.2", "solid"))), ("changed", ov(("J1.1", "solid"), ("J1.2", "none"))), ("dropped", "")]
prev = os.path.join(d, "board.kicad_pcb")
for i, (name, body) in enumerate(seq):
    v, prob, prev = step(d, prev, ZONES + body, i)
    L.emit(f"change_{name}", contract=prob, **L.summary(v), conns=conns(prev) if v.get("outcome") in ("done", "rejected") else None, props=props(prev))

# 2. two footprints, then one dropped; then a KiCad re-save; then both dropped
d2 = L.build(os.path.join(work, "two"), BASE, ZONES, OWN)
v, prob, a = step(d2, os.path.join(d2, "board.kicad_pcb"), ZONES + ov(("J1.1", "solid"), ("J2.1", "none"), ("J2.2", "thermal")), 0)
L.emit("two_set", contract=prob, **L.summary(v), conns=conns(a), props=props(a))
v, prob, b1 = step(d2, a, ZONES + ov(("J1.1", "solid")), 1)
L.emit("two_one_dropped", contract=prob, **L.summary(v), conns=conns(b1), props=props(b1))
rs = L.resave(b1, os.path.join(d2, "resaved.kicad_pcb"))
txt = open(rs).read()
m = re.search(r'\(property "pcb:pad_override" "([^"]*)"[\s\S]*?\(hide yes\)', txt)
L.emit("two_resaved", contract=[], props=props(rs), text_kept=bool(m), text_value=m.group(1) if m else None)
v, prob, c1 = step(d2, rs, ZONES, 2)
L.emit("two_all_dropped_after_resave", contract=prob, **L.summary(v), conns=conns(c1), props=props(c1), original=orig)
# the same override twice: the second run gives the same bytes
v, prob, e1 = step(d2, a, ZONES + ov(("J1.1", "solid"), ("J2.1", "none"), ("J2.2", "thermal")), 3)
L.emit("two_again_same", contract=prob, **L.summary(v), same=open(e1, "rb").read() == open(a, "rb").read())

# 3. repeated pad numbers: J3 has two pads "2", one with its own setting (none) and one inheriting
d3 = L.build(os.path.join(work, "repeat"), BASE, ZONES, OWN)
v, prob, a3 = step(d3, os.path.join(d3, "board.kicad_pcb"), ZONES + ov(("J3.2", "solid")), 0)
L.emit("repeat_set", contract=prob, **L.summary(v), conns=conns(a3), props=props(a3))
v, prob, b3 = step(d3, a3, ZONES, 1)
L.emit("repeat_dropped", contract=prob, **L.summary(v), conns=conns(b3), props=props(b3), original=orig)

# 4. the property against diff and edit: diff of the zoned board with and without the property (same copper), diff
#    of a board against its own KiCad re-save, and move_footprint on an overridden footprint, then the entry dropped
PCB = L.PCB
v, prob, w1 = step(d2, os.path.join(d2, "board.kicad_pcb"), ZONES, 4)
r = subprocess.run([PCB, "--json", "diff", w1, a], capture_output=True, text=True)
dj = json.loads(r.stdout) if r.stdout.startswith("{") else {"raw": r.stdout[-300:]}
L.emit("diff_with_property", contract=[], outcome=dj.get("outcome"), footprints=(dj.get("data") or {}).get("footprints"), copper=bool((dj.get("data") or {}).get("copper")))
r = subprocess.run([PCB, "--json", "diff", b1, rs], capture_output=True, text=True)
dj = json.loads(r.stdout) if r.stdout.startswith("{") else {"raw": r.stdout[-300:]}
L.emit("diff_resave", contract=[], outcome=dj.get("outcome"), footprints=(dj.get("data") or {}).get("footprints"), copper=bool((dj.get("data") or {}).get("copper")))
ops = os.path.join(work, "ops.json")
json.dump([{"op": "move_footprint", "ref": "J2", "from": [40, 20], "to": [40, 24]}], open(ops, "w"))
moved = os.path.join(d2, "moved.kicad_pcb")
r = subprocess.run([PCB, "--json", "edit", a, "--ops", ops, "-o", moved, "--work", os.path.join(work, "editwork")], capture_output=True, text=True)
ej = json.loads(r.stdout) if r.stdout.startswith("{") else {"raw": r.stdout[-300:]}
res = {}
if ej.get("outcome") == "done":
    res = dict(props=props(moved), conns=conns(moved))
    v, prob, m2 = step(d2, moved, ZONES, 5)
    res.update(after_drop=conns(m2), props_after_drop=props(m2))
L.emit("edit_move", contract=[], edit_outcome=ej.get("outcome"), edit_error=(ej.get("error") or {}).get("message", "")[:200], **res)
