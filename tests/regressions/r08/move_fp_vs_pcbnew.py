"""Independent check of `pcb edit` move_footprint against KiCad's own move (review 8): a rotated, flipped footprint
with two pads, a silkscreen line and a rule area inside it is moved by pcb and by pcbnew's SetPosition; every pad,
the footprint's graphic and the rule area's outline must land at the same place in both.

Usage: python3 move_fp_vs_pcbnew.py pcb-binary workdir
"""
import json
import os
import subprocess
import sys

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(work, exist_ok=True)
src = os.path.join(work, "fp.kicad_pcb")
BUILD = r'''
import sys, pcbnew
mm = pcbnew.FromMM
b = pcbnew.NewBoard(sys.argv[1])
for i, (x0, y0, x1, y1) in enumerate([(0, 0, 60, 0), (60, 0, 60, 40), (60, 40, 0, 40), (0, 40, 0, 0)]):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0))); s.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1))); s.SetLayer(pcbnew.Edge_Cuts); b.Add(s)
net = pcbnew.NETINFO_ITEM(b, "A"); b.Add(net)
f = pcbnew.FOOTPRINT(b); f.SetReference("R5"); f.SetValue("R"); b.Add(f)
for k, x in (("1", -1.0), ("2", 1.5)):
    p = pcbnew.PAD(f); p.SetNumber(k); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
    p.SetSize(pcbnew.VECTOR2I(mm(0.8), mm(0.6))); f.Add(p); p.SetFPRelativePosition(pcbnew.VECTOR2I(mm(x), mm(0.3))); p.SetNet(net)
g = pcbnew.PCB_SHAPE(f); g.SetShape(pcbnew.SHAPE_T_SEGMENT); g.SetLayer(pcbnew.F_SilkS); f.Add(g)
g.SetStart(pcbnew.VECTOR2I(mm(-2), mm(-1))); g.SetEnd(pcbnew.VECTOR2I(mm(2), mm(-1)))
z = pcbnew.ZONE(f); z.SetIsRuleArea(True); z.SetDoNotAllowTracks(True); z.SetLayer(pcbnew.F_Cu)
o = z.Outline(); o.NewOutline()
for x, y in [(-1, 1), (1, 1), (1, 2), (-1, 2)]:
    o.Append(mm(x), mm(y))
f.Add(z)
f.SetPosition(pcbnew.VECTOR2I(mm(30), mm(20)))
f.SetOrientationDegrees(30)
f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
pcbnew.SaveBoard(sys.argv[1], b)
'''
subprocess.run([sys.executable, "-c", BUILD, src], check=True)
READ = r'''
import sys, json, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
f = [f for f in b.GetFootprints() if f.GetReference() == "R5"][0]
if len(sys.argv) > 2:
    f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(sys.argv[2])), pcbnew.FromMM(float(sys.argv[3]))))
r = lambda v: [round(pcbnew.ToMM(v.x), 4), round(pcbnew.ToMM(v.y), 4)]
out = {"pos": r(f.GetPosition()), "rot": f.GetOrientationDegrees(), "side": f.GetLayerName(),
       "pads": {p.GetNumber(): r(p.GetPosition()) for p in f.Pads()},
       "graphics": [[r(g.GetStart()), r(g.GetEnd())] for g in f.GraphicalItems() if g.GetClass() == "PCB_SHAPE"],
       "zones": [[r(z.Outline().CVertex(i)) for i in range(z.Outline().TotalVertices())] for z in f.Zones()]}
print(json.dumps(out))
'''
info = lambda *a: json.loads(subprocess.run([sys.executable, "-c", READ, *a], check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1])
before = info(src)
want = info(src, "33", "21.5")
ops = os.path.join(work, "ops.json")
json.dump([{"op": "move_footprint", "ref": "R5", "from": before["pos"], "to": [33, 21.5]}], open(ops, "w"))
out = os.path.join(work, "fp.out.kicad_pcb")
r = subprocess.run([pcb, "--json", "edit", src, "--ops", ops, "--work", os.path.join(work, "w"), "-o", out], capture_output=True, text=True)
d = json.loads(r.stdout)
got = info(out if os.path.exists(out) else d.get("written", out))
print(json.dumps({"outcome": d["outcome"], "regressions": d.get("data", {}).get("regressions"), "before": before, "pcbnew_move": want, "pcb_edit_move": got}, indent=1))
ok = got == want
print("PASS move_footprint matches pcbnew" if ok else "FAIL move_footprint differs from pcbnew's move")
sys.exit(0 if ok else 1)
