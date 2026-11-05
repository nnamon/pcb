"""Review 10: more key cases for the gate's carry-back.
usage: python3 gate_probes2.py WORKDIR"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew  # noqa: E402
from lib import B, edit, fill_check, strip_zone_uuids  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)
OPS = [{"op": "add_track", "net": "S", "layer": "F.Cu", "width": 0.2, "points": [[5, 45], [30, 45]]}]

# 1. a two-layer zone written with its layers B.Cu first, no uuid (pcbnew writes F.Cu first)
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
g.zone("GND", [pcbnew.F_Cu, pcbnew.B_Cu], (2, 2, 38, 20))
p = g.save(os.path.join(work, "layers_rev.kicad_pcb"), fill=True)
strip_zone_uuids(p)
t = open(p).read().replace('(layers "F.Cu" "B.Cu")', '(layers "B.Cu" "F.Cu")')
open(p, "w").write(t)
d = edit(p, OPS, os.path.join(work, "layers_rev.out.kicad_pcb"), os.path.join(work, "lr_w"))
print(json.dumps({"case": "zone_layers_reversed_no_uuid", "outcome": d.get("outcome"), "error": d.get("error")}))

# 2. a stitching via into a filled footprint zone (the gate fills footprint zones; does edit count them for joins?)
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
f = g.fp("FZ1", 20, 25, "GND", tht=True)
g.zone("GND", [pcbnew.B_Cu], (12, 18, 28, 32), parent=f, islands=1)
p = g.save(os.path.join(work, "fpzone_via.kicad_pcb"), fill=True)
d = edit(p, [{"op": "add_via", "net": "GND", "at": [15, 20], "size": 0.6, "drill": 0.3}], os.path.join(work, "fpzone_via.out.kicad_pcb"), os.path.join(work, "fv_w"))
print(json.dumps({"case": "via_in_filled_footprint_zone", "outcome": d.get("outcome"), "error": d.get("error")}))
