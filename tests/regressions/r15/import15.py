"""pcb import-tscircuit's M3 additions: a renamed net whose traces reach another net's pad off the port's centre,
and footprint silkscreen on turned and bottom-side parts of the badge, placed by pcbnew against the circuit JSON.

Usage: python3 import15.py workdir
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402
sys.path.insert(0, os.path.join(L.TESTS, "lib"))
from circuit import C  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def base():
    c = C()
    sa, pa = c.comp("R1", -5, 0, 0, "top", resistance=1000)
    s1, p1 = c.port(sa, pa, "pin1", 1, -5.5, 0); c.pad(pa, p1, -5.5, 0, width=0.5, height=0.5)
    s2, p2 = c.port(sa, pa, "pin2", 2, -4.5, 0); c.pad(pa, p2, -4.5, 0, width=0.5, height=0.5)
    sb, pb = c.comp("R2", 5, 0, 0, "top", resistance=1000)
    s3, p3 = c.port(sb, pb, "pin1", 1, 4.5, 0); c.pad(pb, p3, 4.5, 0, width=0.5, height=0.5)
    s4, p4 = c.port(sb, pb, "pin2", 2, 5.5, 0); c.pad(pb, p4, 5.5, 0, width=0.5, height=0.5)
    return c, dict(s2=s2, s3=s3)


def wire(x, y, l="top", w=0.2):
    return {"route_type": "wire", "x": x, "y": y, "width": w, "layer": l}


def run(name, c):
    cj = os.path.join(work, name + ".json")
    c.dump(cj)
    out = os.path.join(work, name + ".kicad_pcb")
    r = L.pcb("import-tscircuit", cj, "--layers", "2", "-o", out)
    return r, out


# an unknown net name: one end on A's port, the other end inside B's pad 0.2 mm from its centre
c, i = base()
a = c.net("A"); b = c.net("B"); c.strace([i["s2"]], [a]); c.strace([i["s3"]], [b])
c.add({"type": "pcb_trace", "pcb_trace_id": "t1", "net_name": "Net-(R1", "route": [wire(-4.5, 0), wire(0, 0)]})
c.add({"type": "pcb_trace", "pcb_trace_id": "t2", "net_name": "Net-(R1", "route": [wire(0, 0), wire(4.3, 0)]})
r, out = run("rename_into_other_pad", c)
drc = None
if r["outcome"] == "done":
    import subprocess
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "-o", out + ".drc.json", out], capture_output=True)
    drc = sorted({v["type"] for v in json.load(open(out + ".drc.json"))["violations"]} & {"shorting_items", "clearance", "tracks_crossing"})
L.emit("rename_into_other_pad", **L.slim(r), drc=drc)

# the badge: footprint silkscreen on turned and bottom-side parts, against the circuit JSON
cj = os.path.join(L.TESTS, "fixtures", "badge_r36a", "circuit.json")
out = os.path.join(work, "badge.kicad_pcb")
r = L.pcb("import-tscircuit", cj, "--layers", "4", "--allow-cross-net", "NFC_COIL", "-o", out)
d = json.load(open(cj))
comp = {e["pcb_component_id"]: e for e in d if e.get("type") == "pcb_component"}
brd = [e for e in d if e.get("type") == "pcb_board"][0]
segs = []
for e in d:
    if e.get("type") == "pcb_silkscreen_path" and e.get("pcb_component_id") in comp:
        cp = comp[e["pcb_component_id"]]
        turned = (cp.get("rotation") or 0) % 360 != 0
        bottom = cp.get("layer") == "bottom"
        if not (turned or bottom):
            continue
        r_ = e["route"]
        for p, q in zip(r_, r_[1:]):
            segs.append(((p["x"], p["y"]), (q["x"], q["y"]), "B.SilkS" if e.get("layer") == "bottom" else "F.SilkS", bottom, turned))
kic = L.pyq(out, '''
out = []
for f in b.GetFootprints():
    for g in f.GraphicalItems():
        if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and g.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            out.append([mm(g.GetStart().x), mm(g.GetStart().y), mm(g.GetEnd().x), mm(g.GetEnd().y), b.GetLayerName(g.GetLayer())])
bb = b.GetBoardEdgesBoundingBox()
print(json.dumps({"segs": out, "bbox": [mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())]}))
''')
# tscircuit (y up, centred on the board's centre) to KiCad (y down): through the outline's centre
kx = (kic["bbox"][0] + kic["bbox"][2]) / 2 - brd["center"]["x"]
ky = (kic["bbox"][1] + kic["bbox"][3]) / 2 + brd["center"]["y"]
names = {"F.SilkS": "F.Silkscreen", "B.SilkS": "B.Silkscreen"}
miss = []
for (p, q, lay, bottom, turned) in segs:
    P, Q = (p[0] + kx, ky - p[1]), (q[0] + kx, ky - q[1])
    ok = any(k[4] == names[lay] and ((abs(k[0] - P[0]) < 2e-3 and abs(k[1] - P[1]) < 2e-3 and abs(k[2] - Q[0]) < 2e-3 and abs(k[3] - Q[1]) < 2e-3)
                                     or (abs(k[0] - Q[0]) < 2e-3 and abs(k[1] - Q[1]) < 2e-3 and abs(k[2] - P[0]) < 2e-3 and abs(k[3] - P[1]) < 2e-3)) for k in kic["segs"])
    if not ok:
        miss.append([round(P[0], 3), round(P[1], 3), lay, bottom, turned])
L.emit("badge_silk", **L.slim(r), checked=len(segs), bottom=sum(1 for s in segs if s[3]), turned=sum(1 for s in segs if s[4]), misplaced=len(miss), first=miss[:4])

# a bottom-side part turned 90 degrees, with bottom silkscreen (no real fixture has one)
c = C()
sa, pa = c.comp("U9", 3, 2, 90, "bottom")
sp1, pp1 = c.port(sa, pa, "pin1", 1, 3, 1); c.pad(pa, pp1, 3, 1, layer="bottom", width=0.6, height=0.4)
sp2, pp2 = c.port(sa, pa, "pin2", 2, 3, 3); c.pad(pa, pp2, 3, 3, layer="bottom", width=0.6, height=0.4)
c.strace([sp1], [c.net("N1")]); c.strace([sp2], [c.net("N2")])
route = [{"x": 2, "y": 0.5}, {"x": 4.5, "y": 0.5}, {"x": 4.5, "y": 3.5}]
c.add({"type": "pcb_silkscreen_path", "pcb_silkscreen_path_id": "s1", "pcb_component_id": pa, "layer": "bottom", "route": route, "stroke_width": 0.15})
r, out = run("bottom_silk", c)
k = L.pyq(out, """
out = []
for f in b.GetFootprints():
    for g in f.GraphicalItems():
        if g.GetShape() == pcbnew.SHAPE_T_SEGMENT and g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            out.append([round(mm(g.GetStart().x), 3), round(mm(g.GetStart().y), 3), round(mm(g.GetEnd().x), 3), round(mm(g.GetEnd().y), 3), b.GetLayerName(g.GetLayer())])
    pads = [[p.GetNumber(), round(mm(p.GetPosition().x), 3), round(mm(p.GetPosition().y), 3)] for p in f.Pads()]
bb = b.GetBoardEdgesBoundingBox()
print(json.dumps({"segs": out, "pads": pads, "c": [mm(bb.GetCenter().x), mm(bb.GetCenter().y)]}))
""")
cx_, cy_ = k["c"]
want = [[round(p["x"] + cx_, 3), round(cy_ - p["y"], 3)] for p in route]
want_segs = [[want[0][0], want[0][1], want[1][0], want[1][1]], [want[1][0], want[1][1], want[2][0], want[2][1]]]
got = [s[:4] for s in k["segs"]]
ok = all(any(max(abs(a - b_) for a, b_ in zip(w, g)) < 2e-3 or max(abs(a - b_) for a, b_ in zip(w[2:] + w[:2], g)) < 2e-3 for g in got) for w in want_segs)
L.emit("bottom_silk", **L.slim(r), placed=ok, layers=sorted({s[4] for s in k["segs"]}), want=want_segs, got=got, pads=k["pads"], pads_want=[[round(3 + cx_, 3), round(cy_ - 1, 3)], [round(3 + cx_, 3), round(cy_ - 3, 3)]])
