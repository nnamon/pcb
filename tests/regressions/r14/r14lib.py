"""Review 14's helpers, on top of review 13's (`r13lib`): a board post-processing step in pcbnew, a KiCad refill of a
copy, exact pad copper and fill shapes read with pcbnew, and per-zone fill areas. Nothing here uses pcb's own parser.
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "r13"))
sys.path.insert(0, os.path.join(here, "..", "..", "lib"))
import r13lib as L  # noqa: E402,F401
from r13lib import build as _build, emit, inspect, summary, write_toml, zone, drc, tie_groups  # noqa: E402,F401

PCB = L.PCB
HELPER = os.path.join(here, "..", "..", "..", "src", "kicad_helper.py")


def post(path, code):
    """Runs pcbnew code on the saved board (`b` the board, `mm` FromMM, `V` a point in mm, `net(name)`), then saves."""
    pre = ("import sys, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nmm = pcbnew.FromMM\nV = lambda x, y: pcbnew.VECTOR2I(mm(x), mm(y))\n"
           "def net(n):\n    ni = b.FindNet(n)\n    if ni is None:\n        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni)\n    return ni\n")
    r = subprocess.run([sys.executable, "-c", pre + code + "\npcbnew.SaveBoard(sys.argv[1], b)\n", path], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"post {path}: {r.stderr[-1500:]}")


def build(d, spec, toml_body, code=None):
    _build(d, spec, toml_body)
    if code:
        post(os.path.join(d, "board.kicad_pcb"), code)
    return d


def refill(src, dst):
    """A copy of `src` refilled by KiCad (the project file travels with it)."""
    shutil.copy(src, dst)
    pro = os.path.splitext(src)[0] + ".kicad_pro"
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(dst)[0] + ".kicad_pro")
    r = subprocess.run([sys.executable, HELPER, "fill", dst], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"refill {src}: {r.stderr[-800:]}")
    return dst


def resave(src, dst):
    """A copy of `src` loaded and saved by pcbnew, with no refill."""
    shutil.copy(src, dst)
    pro = os.path.splitext(src)[0] + ".kicad_pro"
    if os.path.exists(pro):
        shutil.copy(pro, os.path.splitext(dst)[0] + ".kicad_pro")
    subprocess.run([sys.executable, "-c", "import sys, pcbnew; b = pcbnew.LoadBoard(sys.argv[1]); pcbnew.SaveBoard(sys.argv[1], b)", dst], check=True, capture_output=True)
    return dst


SHAPES = r'''
import json, sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
IU = 1e6
def polys(ps):
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        out.append([[(o.CPoint(k).x / IU, o.CPoint(k).y / IU) for k in range(o.PointCount())],
                    [[(ps.Hole(i, h).CPoint(k).x / IU, ps.Hole(i, h).CPoint(k).y / IU) for k in range(ps.Hole(i, h).PointCount())] for h in range(ps.HoleCount(i))]])
    return out
r = {"pads": [], "vias": [], "zones": []}
for f in b.GetFootprints():
    for p in f.Pads():
        for layer in p.GetLayerSet().CuStack():
            ps = pcbnew.SHAPE_POLY_SET()
            p.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.002), pcbnew.ERROR_INSIDE)
            r["pads"].append({"ref": f.GetReference(), "num": p.GetNumber(), "net": p.GetNetname(), "layer": b.GetLayerName(layer), "polys": polys(ps)})
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        r["vias"].append({"net": t.GetNetname(), "x": t.GetPosition().x / IU, "y": t.GetPosition().y / IU, "size": t.GetWidth(pcbnew.F_Cu) / IU, "uuid": t.m_Uuid.AsString()})
for z in list(b.Zones()) + [z for f in b.GetFootprints() for z in f.Zones()]:
    e = {"name": z.GetZoneName(), "net": z.GetNetname(), "uuid": z.m_Uuid.AsString(), "rule": z.GetIsRuleArea(), "prio": z.GetAssignedPriority(), "fills": {}}
    if z.GetIsRuleArea():
        ol = z.Outline()
        e["outline"] = [(ol.CVertex(k).x / IU, ol.CVertex(k).y / IU) for k in range(ol.TotalVertices())]
        e["no_vias"] = z.GetDoNotAllowVias()
    for layer in z.GetLayerSet().CuStack():
        e["fills"][b.GetLayerName(layer)] = polys(z.GetFilledPolysList(layer))
    r["zones"].append(e)
print("JSON" + json.dumps(r))
'''


def shapes(path):
    o = subprocess.run([sys.executable, "-c", SHAPES, path], capture_output=True, text=True)
    if o.returncode:
        raise SystemExit(f"shapes {path}: {o.stderr[-1500:]}")
    return json.loads([ln for ln in o.stdout.splitlines() if ln.startswith("JSON")][-1][4:])


def mp(polys):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    ps = [Polygon(e, h).buffer(0) for e, h in polys if len(e) >= 3]
    return unary_union(ps) if ps else Polygon()


def zone_fills(path):
    """{(zone name or uuid, layer): shapely geometry} of every copper zone's saved fill."""
    s = shapes(path)
    return {((z["name"] or z["uuid"]), layer): mp(p) for z in s["zones"] if not z["rule"] for layer, p in z["fills"].items()}


def fill_diff(a, b):
    """Zones whose fill differs between two boards: {key: [area a, area b, symmetric difference area]} over 0.01 mm²."""
    fa, fb = zone_fills(a), zone_fills(b)
    out = {}
    for k in sorted(set(fa) | set(fb), key=str):
        ga, gb = fa.get(k), fb.get(k)
        from shapely.geometry import Polygon
        ga, gb = ga if ga is not None else Polygon(), gb if gb is not None else Polygon()
        x = ga.symmetric_difference(gb).area
        if x > 0.01:
            out[f"{k[0]}|{k[1]}"] = [round(ga.area, 2), round(gb.area, 2), round(x, 2)]
    return out

