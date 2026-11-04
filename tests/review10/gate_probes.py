"""Review 10: the gate's fill carry-back on zones that the key cannot tell apart, or whose key may change.
usage: python3 gate_probes.py WORKDIR
Each case builds a board, runs one edit three times, and reports the outcome, whether the three files are the same,
and any zone whose fill on file differs from pcbnew's refill of that file."""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew  # noqa: E402
from lib import B, edit, fill_check, strip_zone_uuids  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)
ADD_S = [{"op": "add_track", "net": "S", "layer": "F.Cu", "width": 0.2, "points": [[5, 45], [30, 45]]}]


def run(name, board, ops=ADD_S, runs=3):
    shas, outs, res = set(), [], {"case": name}
    for k in range(runs):
        out = os.path.join(work, f"{name}_{k}.out.kicad_pcb")
        d = edit(board, ops, out, os.path.join(work, f"{name}_{k}_w"))
        res.setdefault("outcomes", []).append((d.get("outcome"), d.get("error", {}).get("code") if isinstance(d.get("error"), dict) else d.get("error"), (d.get("data") or {}).get("regressions")))
        if d.get("outcome") == "done" and os.path.exists(out):
            shas.add(hashlib.sha256(open(out, "rb").read()).hexdigest())
            outs.append(out)
            if k == 0 or len(shas) > 1:
                res.setdefault("fill_mismatch", {})[k] = fill_check(out)
    res["distinct_files"] = len(shas)
    print(json.dumps(res, default=str))
    return res


# 1. duplicates: two GND zones, same net, layer and outline, no uuids, different clearance and priority;
#    a VCC pad inside makes their fills differ
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
g.fp("V1", 20, 10, "VCC", tht=True)
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=0.3, priority=0)
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=2.0, priority=1)
p = g.save(os.path.join(work, "dup.kicad_pcb"), fill=True)
strip_zone_uuids(p)
run("dup_no_uuid", p)

# 2. same, with uuids (control)
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
g.fp("V1", 20, 10, "VCC", tht=True)
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=0.3, priority=0)
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=2.0, priority=1)
p = g.save(os.path.join(work, "dup_u.kicad_pcb"), fill=True)
run("dup_uuid", p)

# 3. zones that differ only in a second outline polygon, no uuids
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
g.fp("G2", 50, 10, "GND", tht=True)
g.zone("GND", [pcbnew.F_Cu], [(2, 2, 38, 20)])
g.zone("GND", [pcbnew.F_Cu], [(2, 2, 38, 20), (42, 2, 78, 20)])
p = g.save(os.path.join(work, "second_poly.kicad_pcb"), fill=True)
strip_zone_uuids(p)
run("second_poly_no_uuid", p)

# 4. two footprints with the same reference, each holding a GND zone; zone uuids stripped
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
for x in (15, 55):
    f = g.fp("FZ", x, 25, "GND", tht=True, extra_pads=[(x + 3, 25, "VCC")])
    g.zone("GND", [pcbnew.B_Cu], (x - 8, 18, x + 8, 32), parent=f, clearance=0.3 if x == 15 else 1.0)
p = g.save(os.path.join(work, "same_ref.kicad_pcb"), fill=True)
strip_zone_uuids(p)
run("same_ref_no_uuid", p)

# 5. two footprints with the same reference whose zones carry the same uuid (a copied footprint)
p2 = os.path.join(work, "same_ref_dupuuid.kicad_pcb")
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
for x in (15, 55):
    f = g.fp("FZ", x, 25, "GND", tht=True, extra_pads=[(x + 3, 25, "VCC")])
    g.zone("GND", [pcbnew.B_Cu], (x - 8, 18, x + 8, 32), parent=f, clearance=0.3 if x == 15 else 1.0)
g.save(p2, fill=True)
import re  # noqa: E402
t = open(p2).read()
us = re.findall(r'\(zone\b[^()]*(?:\((?!uuid)[^()]*(?:\([^()]*\))*[^()]*\)[^()]*)*\(uuid "([^"]+)"\)', t)
if len(us) >= 2:
    t = t.replace(us[1], us[0])
    open(p2, "w").write(t)
run("same_ref_dup_zone_uuid", p2)

# 6. top-level zones sharing a uuid (copy-pasted text), different outlines
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
g.fp("G2", 50, 10, "GND", tht=True)
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
g.zone("GND", [pcbnew.F_Cu], (42, 2, 78, 20))
p = g.save(os.path.join(work, "dup_uuid_top.kicad_pcb"), fill=True)
t = open(p).read()
from lib import blocks  # noqa: E402
zu = [re.search(r'\(uuid "([^"]+)"\)', t[s:e]).group(1) for s, e in blocks(t, "zone")]
t = t.replace(zu[1], zu[0])
open(p, "w").write(t)
run("top_dup_uuid", p)

# 7. footprint with a zone moved in the same edit, zone uuids stripped, by an odd offset
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
f = g.fp("FZ1", 20, 25, "GND", tht=True)
g.zone("GND", [pcbnew.B_Cu], (12, 18, 28, 32), parent=f)
g.zone(None, [pcbnew.F_Cu], (13, 19, 16, 22), keepout=True, parent=f)
p = g.save(os.path.join(work, "move_fz.kicad_pcb"), fill=True)
strip_zone_uuids(p)
run("move_fp_zone_no_uuid", p, ops=[{"op": "move_footprint", "ref": "FZ1", "from": [20, 25], "to": [33.3333333, 25.1234567]}])
run("move_fp_zone_no_uuid_half", p, ops=[{"op": "move_footprint", "ref": "FZ1", "from": [20, 25], "to": [33.00005, 25.00005]}])

# 8. keep-out areas only, identical, no uuids (no fills to swap) plus one copper zone
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
g.zone(None, [pcbnew.F_Cu], (25, 5, 30, 15), keepout=True)
g.zone(None, [pcbnew.F_Cu], (25, 5, 30, 15), keepout=True)
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
p = g.save(os.path.join(work, "keepouts.kicad_pcb"), fill=True)
strip_zone_uuids(p)
run("keepouts_no_uuid", p)

# 9. a zone outline with a repeated point, no uuid
g = B()
g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
g.fp("G1", 10, 10, "GND", tht=True)
z = g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
p = g.save(os.path.join(work, "reppt.kicad_pcb"), fill=True)
t = open(p).read()
t = t.replace("(xy 38 2)", "(xy 38 2) (xy 38 2)", 1)
open(p, "w").write(t)
strip_zone_uuids(p)
run("repeated_point_no_uuid", p)
