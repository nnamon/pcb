"""Review 11 gate probes: zone pairing when canonical text differs between the candidate and pcbnew's save.
usage: PCB_BIN=... python3 gate11.py WORKDIR"""
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review10"))
import pcbnew  # noqa: E402
from lib import B, PCB, edit, fill_check, strip_zone_uuids  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)
ADD_S = [{"op": "add_track", "net": "S", "layer": "F.Cu", "width": 0.2, "points": [[5, 45], [30, 45]]}]
only = sys.argv[2:]


def run(name, board, ops=ADD_S, runs=3):
    if only and name not in only:
        return
    shas, res = set(), {"case": name}
    for k in range(runs):
        out = os.path.join(work, f"{name}_{k}.out.kicad_pcb")
        d = edit(board, ops, out, os.path.join(work, f"{name}_{k}_w"))
        err = d.get("error")
        res.setdefault("outcomes", []).append((d.get("outcome"), err.get("message") if isinstance(err, dict) else err, (d.get("data") or {}).get("regressions")))
        if d.get("outcome") == "done" and os.path.exists(out):
            shas.add(hashlib.sha256(open(out, "rb").read()).hexdigest())
            res.setdefault("fill_mismatch", {})[k] = fill_check(out)
    res["distinct_files"] = len(shas)
    print(json.dumps(res, default=str))


def dup(fill, name, clear=(0.3, 2.0), prio=(0, 1)):
    g = B()
    g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
    g.fp("G1", 10, 10, "GND", tht=True)
    g.fp("V1", 20, 10, "VCC", tht=True)
    g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=clear[0], priority=prio[0])
    g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=clear[1], priority=prio[1])
    p = g.save(os.path.join(work, name + ".kicad_pcb"), fill=fill)
    strip_zone_uuids(p)
    return p


# G1: review 10's case 1, but the zones were never filled (a fresh tscircuit import has no fills)
run("dup_no_uuid_unfilled", dup(False, "dup_unfilled"))
# G2: control, filled
run("dup_no_uuid_filled", dup(True, "dup_filled"))

# G3: filled, then a hand edit that pcbnew rewrites on save: "(priority 0)" spelled out on both, and
# "(filled_areas_thickness no)" dropped etc. Done by text: add a redundant child to both zones.
p = dup(True, "dup_handtext")
t = open(p).read()
t = t.replace("(hatch edge 0.5)", "(hatch edge 0.5)\n\t\t(filled_areas_thickness no)")
open(p, "w").write(t)
run("dup_no_uuid_handtext", p)

# G4: two footprints with the same reference at the same position (a pasted duplicate), each with a GND zone of
# different clearance, uuids stripped; both owners have the same key
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
for c in (0.3, 1.5):
    f = g.fp("FZ", 20, 25, "GND", tht=True, extra_pads=[(23, 25, "VCC")])
    g.zone("GND", [pcbnew.B_Cu], (12, 18, 28, 32), parent=f, clearance=c)
p = g.save(os.path.join(work, "same_ref_same_pos.kicad_pcb"), fill=True)
strip_zone_uuids(p)
run("same_ref_same_pos", p)

# G5: footprint moved by the edit itself; its zone uuid stripped; another GND footprint zone elsewhere
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
f = g.fp("FZ1", 15, 25, "GND", tht=True, extra_pads=[(18, 25, "VCC")])
g.zone("GND", [pcbnew.B_Cu], (7, 18, 23, 32), parent=f, clearance=0.3)
f = g.fp("FZ2", 55, 25, "GND", tht=True, extra_pads=[(58, 25, "VCC")])
g.zone("GND", [pcbnew.B_Cu], (47, 18, 63, 32), parent=f, clearance=1.0)
f.SetOrientationDegrees(90)
p = g.save(os.path.join(work, "move_fp.kicad_pcb"), fill=True)
strip_zone_uuids(p)
bd = pcbnew.LoadBoard(p)
pos = {fp.GetReference(): (pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)) for fp in bd.GetFootprints()}
run("move_fp_no_uuid", p, ops=[{"op": "move_footprint", "ref": "FZ2", "from": list(pos["FZ2"]), "to": [pos["FZ2"][0] - 1.23457, pos["FZ2"][1] + 0.00005]}] + ADD_S)
run("move_fp_no_uuid_2", p, ops=[{"op": "move_footprint", "ref": "FZ1", "from": list(pos["FZ1"]), "to": [55.0, 25.0]},
                                 {"op": "move_footprint", "ref": "FZ2", "from": list(pos["FZ2"]), "to": [15.0, 25.0]}] + ADD_S)
