"""Check of spike 3: a board with KiCad zones and the NFC coil as a net tie, against the board it came from.

Reads both with pcbnew and fails unless:
  A. the coil copper is unchanged: every NFC_COIL track of the base is, at the same ends and width, either copper
     inside L601's footprint or an NFC_AC1 track; every NFC_COIL via is an L601 pad of the same size and drill;
  B. no zone fill (any layer) enters the coil keep-out (its box plus 3.5 mm) or the Lyra antenna box;
  C. In1.Cu and In2.Cu are GND, and every GND via and plated GND hole outside the keep-outs lands in both planes;
  D. every plated GND hole has a thermal relief on each plane: fill covers under 80 % of the ring just outside it;
  E. no hole or via of another net is within 0.3 mm of either plane's fill;
  F. every zone's fill is in one piece per layer or each piece touches a pad, track or via of its net.
It also prints copper area per net and layer next to the old scripts' pours (r36p.json), for comparison only.

Usage: python3 verify_zones.py base.kicad_pcb zoned.kicad_pcb nfc_coil.json [r36p.json]
"""
import collections
import json
import sys

import pcbnew
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

IU = 1e6
base_p, zoned_p, coil_p = sys.argv[1:4]
old_p = sys.argv[4] if len(sys.argv) > 4 else None
coil = json.load(open(coil_p))
fails = []


def pad_poly(pd):
    """The pad's copper outline: circle, oval (capsule), or (round)rect as a turned rectangle; custom pads as
    their turned bounding rectangle."""
    w, h = pd.GetSize().x / IU, pd.GetSize().y / IU
    c = (pd.GetPosition().x / IU, pd.GetPosition().y / IU)
    sh = pd.GetShape()
    if sh == pcbnew.PAD_SHAPE_CIRCLE:
        g = Point(0, 0).buffer(w / 2)
    elif sh == pcbnew.PAD_SHAPE_OVAL:
        r = min(w, h) / 2
        g = (LineString([(-(w / 2 - r), 0), (w / 2 - r, 0)]) if w >= h else LineString([(0, -(h / 2 - r)), (0, h / 2 - r)])).buffer(r)
    else:
        g = box(-w / 2, -h / 2, w / 2, h / 2)
    g = rotate(g, -pd.GetOrientationDegrees(), origin=(0, 0))
    return translate(g, *c)


def xy(v):
    return (round(v.x / IU, 4), round(v.y / IU, 4))


def polys(sps):
    out = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        ext = [(o.CPoint(j).x / IU, o.CPoint(j).y / IU) for j in range(o.PointCount())]
        holes = []
        for h in range(sps.HoleCount(i)):
            hh = sps.Hole(i, h)
            holes.append([(hh.CPoint(j).x / IU, hh.CPoint(j).y / IU) for j in range(hh.PointCount())])
        out.append(Polygon(ext, holes).buffer(0))
    return out


base = pcbnew.LoadBoard(base_p)
coil_tracks = sorted((xy(t.GetStart()), xy(t.GetEnd()), t.GetWidth(), t.GetLayerName()) for t in base.GetTracks() if t.GetNetname() == "NFC_COIL" and t.GetClass() != "PCB_VIA")
coil_tracks = sorted(tuple(sorted((a, c))) + (w, l) for a, c, w, l in coil_tracks)
coil_vias = sorted((xy(t.GetPosition()), t.GetWidth(), t.GetDrillValue()) for t in base.GetTracks() if t.GetNetname() == "NFC_COIL" and t.GetClass() == "PCB_VIA")
del base

b = pcbnew.LoadBoard(zoned_p)
L = {name: b.GetLayerID(name) for name in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")}

# A
l601 = b.FindFootprintByReference("L601")
now = []
for g in l601.GraphicalItems():
    if g.GetLayerName().endswith(".Cu"):
        now.append(tuple(sorted((xy(g.GetStart()), xy(g.GetEnd())))) + (g.GetWidth(), g.GetLayerName()))
for t in b.GetTracks():
    if t.GetNetname() == "NFC_AC1" and t.GetClass() != "PCB_VIA":
        k = tuple(sorted((xy(t.GetStart()), xy(t.GetEnd())))) + (t.GetWidth(), t.GetLayerName())
        if k in coil_tracks:
            now.append(k)
if sorted(now) != coil_tracks:
    fails.append(f"A: coil copper differs: {len(coil_tracks)} segments before, {len(now)} matched after")
pads_now = sorted((xy(p.GetPosition()), p.GetSize().x, p.GetDrillSize().x) for p in l601.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH)
if pads_now != coil_vias:
    fails.append(f"A: coil vias {coil_vias} became pads {pads_now}")
if any(t.GetNetname() == "NFC_COIL" for t in b.GetTracks()):
    fails.append("A: NFC_COIL copper left on the board")
# the pad groups are not readable from Python; the file says it
if "(net_tie_pad_groups" not in open(zoned_p).read():
    fails.append("A: L601 is not a net tie")

# zone fills by net and layer
fill = collections.defaultdict(list)
for z in b.Zones():
    if z.GetIsRuleArea():
        continue
    for name, lid in L.items():
        if z.IsOnLayer(lid):
            fill[(z.GetNetname(), name)].extend(polys(z.GetFilledPolysList(lid)))
fill = {k: unary_union(v) for k, v in fill.items()}

# B
k = coil["keepout"]
X = lambda x: x + 20
Y = lambda y: 130 - y
coil_keep = box(X(k[0]), Y(k[3]), X(k[2]), Y(k[1])).buffer(3.5, join_style=2)
ant_keep = box(166, 45, 180, 73)
for (net, layer), f in fill.items():
    for name, kp in (("coil", coil_keep), ("antenna", ant_keep)):
        a = f.intersection(kp.buffer(-0.01)).area
        if a > 1e-6:
            fails.append(f"B: {net} fill on {layer} enters the {name} keep-out ({a:.3f} mm2)")

# C, D, E
for layer in ("In1.Cu", "In2.Cu"):
    nets_here = [n for (n, l) in fill if l == layer]
    if nets_here != ["GND"]:
        fails.append(f"C: {layer} carries {nets_here}, not only GND")
    plane = fill.get(("GND", layer), Polygon())
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA":
            continue
        p = Point(t.GetPosition().x / IU, t.GetPosition().y / IU)
        if coil_keep.contains(p) or ant_keep.contains(p):
            continue
        if t.GetNetname() == "GND":
            if not plane.contains(p):
                fails.append(f"C: GND via at {xy(t.GetPosition())} misses the {layer} plane")
        else:
            d = plane.distance(p) - t.GetWidth() / IU / 2
            if d < 0.3 - 1e-3:
                fails.append(f"E: {t.GetNetname()} via at {xy(t.GetPosition())} is {d:.3f} mm from the {layer} plane")
    for f in b.GetFootprints():
        for pd in f.Pads():
            if pd.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
                continue
            p = Point(pd.GetPosition().x / IU, pd.GetPosition().y / IU)
            if coil_keep.contains(p) or ant_keep.contains(p):
                continue
            shape = pad_poly(pd)
            if pd.GetNetname() == "GND":
                # the relief gap: 0.05-0.30 mm outside the pad, inside the plane's 0.35 mm thermal gap
                ring = shape.buffer(0.30).difference(shape.buffer(0.05))
                cov = plane.intersection(ring).area / ring.area
                if cov == 0:
                    fails.append(f"C: GND pad {f.GetReference()}.{pd.GetNumber()} not joined to the {layer} plane")
                elif cov > 0.8:
                    fails.append(f"D: GND pad {f.GetReference()}.{pd.GetNumber()} has no thermal relief on {layer} ({cov:.0%} covered)")
            elif pd.GetNetname():
                d = plane.distance(shape)
                if d < 0.3 - 1e-3:
                    fails.append(f"E: {pd.GetNetname()} pad {f.GetReference()}.{pd.GetNumber()} is {d:.3f} mm from the {layer} plane")

# F: every fill piece touches copper of its net
items = collections.defaultdict(list)
for t in b.GetTracks():
    for name, lid in L.items():
        if t.IsOnLayer(lid):
            if t.GetClass() == "PCB_VIA":
                items[(t.GetNetname(), name)].append(Point(t.GetPosition().x / IU, t.GetPosition().y / IU).buffer(t.GetWidth() / IU / 2))
            else:
                line = LineString([(t.GetStart().x / IU, t.GetStart().y / IU), (t.GetEnd().x / IU, t.GetEnd().y / IU)])
                items[(t.GetNetname(), name)].append(line.buffer(t.GetWidth() / IU / 2))
for f in b.GetFootprints():
    for pd in f.Pads():
        for name, lid in L.items():
            if pd.IsOnLayer(lid):
                items[(pd.GetNetname(), name)].append(pad_poly(pd))
for (net, layer), f in fill.items():
    pieces = list(f.geoms) if f.geom_type == "MultiPolygon" else [f]
    own = unary_union(items[(net, layer)]) if items[(net, layer)] else Polygon()
    loose = [p for p in pieces if p.area > 1e-4 and not p.buffer(1e-3).intersects(own)]
    if loose:
        fails.append(f"F: {net} on {layer} has {len(loose)} fill pieces touching none of its copper, first at {[round(v, 2) for v in loose[0].bounds]}")

# area comparison with the old pours
area = {k: round(v.area, 1) for k, v in fill.items()}
cmp = {}
if old_p:
    old = collections.defaultdict(list)
    for e in json.load(open(old_p)):
        if e["type"] == "pcb_copper_pour":
            for pg in e["polygons"]:
                old[(e["net_name"], "F.Cu" if e["layer"] == "top" else "B.Cu")].append(Polygon(pg["exterior"], pg.get("interiors", [])).buffer(0))
    for k2 in sorted(set(old) | {k for k in area if k[1] in ("F.Cu", "B.Cu")}):
        cmp[f"{k2[0]} {k2[1]}"] = {"old": round(unary_union(old[k2]).area, 1) if k2 in old else 0, "new": area.get(k2, 0)}

print(json.dumps({"ok": not fails, "fails": fails, "planes": {l: area.get(("GND", l)) for l in ("In1.Cu", "In2.Cu")}, "outer_vs_old": cmp}, indent=1))
sys.exit(0 if not fails else 1)
