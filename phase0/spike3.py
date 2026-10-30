"""Spike 3: KiCad zones in place of the pour, plane and fill scripts, and the NFC coil as a net-tie footprint.

A prototype in Python with pcbnew, to prove the approach before it goes into `pcb`. On a copy of the board:
1. the NFC coil's spiral becomes copper inside L601's footprint, a net tie for pads 1 and 3; its vias become pads 3 and 4;
2. rule areas keep pours out of the coil area (plus 3.5 mm) and the Lyra antenna area, on every copper layer;
3. In1.Cu and In2.Cu get solid GND planes (0.35 mm clearance, thermal reliefs on plated GND holes);
4. each power net gets a fill within GROW mm of its own copper on each outer layer (solid to its pads);
5. F.Cu and B.Cu get GND pours below the power fills (0.25 mm clearance, thermal reliefs, islands removed);
6. the board is saved unfilled; `kicad_helper.py fill` fills it in a fresh process.

Usage: python3 spike3.py in.kicad_pcb nfc_coil.json out.kicad_pcb
"""
import json
import sys

import pcbnew
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

IU = 1e6
mm = lambda v: int(round(v * IU))
src, coil_json, out = sys.argv[1:4]
coil = json.load(open(coil_json))
b = pcbnew.LoadBoard(src)

# nfc_coil.json is in board coordinates with y up from the bottom-left corner; KiCad = (x + 20, 130 - y) here.
X = lambda x: x + 20
Y = lambda y: 130 - y


def net(name):
    n = b.FindNet(name)
    assert n, name
    return n


# 1. coil into L601 as a net tie. The top-layer spiral runs from pad 1 (NFC_AC0) to the via at its inner end, so it
# joins two nets and becomes copper inside the footprint. Its two vias become footprint pads 3 and 4, and the bottom
# bridge and the short top link stay ordinary NFC_AC1 tracks between pads 3, 4 and 2, so KiCad's connectivity sees them.
l601 = b.FindFootprintByReference("L601")
ac1 = net("NFC_AC1")
coil_tracks = [t for t in b.GetTracks() if t.GetNetname() == "NFC_COIL"]
vias = [t for t in coil_tracks if t.GetClass() == "PCB_VIA"]
vpos = [(v.GetPosition().x, v.GetPosition().y) for v in vias]
pad2 = next(p for p in l601.Pads() if p.GetNumber() == "2")
spiral = bridge = 0
for i, v in enumerate(sorted(vias, key=lambda v: v.GetPosition().x)):
    p = pcbnew.PAD(l601)
    p.SetNumber(str(3 + i))
    p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    p.SetSize(pcbnew.VECTOR2I(v.GetWidth(pcbnew.F_Cu), v.GetWidth(pcbnew.F_Cu)))
    p.SetDrillSize(pcbnew.VECTOR2I(v.GetDrillValue(), v.GetDrillValue()))
    p.SetLayerSet(pcbnew.PAD.PTHMask())
    p.SetNet(ac1)
    l601.Add(p)
    # KiCad 10: the board position, after Add; KiCad keeps the footprint-local one from it
    p.SetPosition(v.GetPosition())
    b.Remove(v)
for t in coil_tracks:
    if t.GetClass() == "PCB_VIA":
        continue
    ends = [(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)]
    is_link = t.GetLayer() == pcbnew.F_Cu and any(e in vpos for e in ends) and any(e == (pad2.GetPosition().x, pad2.GetPosition().y) for e in ends)
    if t.GetLayer() == pcbnew.B_Cu or is_link:
        t.SetNet(ac1)
        bridge += 1
        continue
    s_ = pcbnew.PCB_SHAPE(l601)
    s_.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s_.SetStart(t.GetStart())
    s_.SetEnd(t.GetEnd())
    s_.SetWidth(t.GetWidth())
    s_.SetLayer(t.GetLayer())
    l601.Add(s_)
    b.Remove(t)
    spiral += 1
l601.ClearNetTiePadGroups()
l601.AddNetTiePadGroup("1, 3")
print(f"coil: {spiral} spiral segments into L601, {len(vias)} vias as pads 3-4, {bridge} bridge/link tracks on NFC_AC1")

# 2. keep-out rule areas
k = coil["keepout"]
coil_keep = box(X(k[0]), Y(k[3]), X(k[2]), Y(k[1])).buffer(3.5, join_style=2)
ant_keep = box(X(146 - 80 + 80), Y(85), X(160), Y(57))  # Lyra antenna keep-out, circuit (66..80, 2..30)
keepouts = [("coil", coil_keep), ("antenna", ant_keep)]


def add_outline(z, poly):
    o = z.Outline()
    o.NewOutline()
    for x, y in list(poly.exterior.coords)[:-1]:
        o.Append(mm(x), mm(y))


for name, poly in keepouts:
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    # the board's copper layers only: AllCuMask() includes layers this 4-layer board does not have
    cu = pcbnew.LSET()
    for layer in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
        cu.AddLayer(layer)
    z.SetLayerSet(cu)
    z.SetZoneName(f"keepout_{name}")
    add_outline(z, poly)
    b.Add(z)

# board outline
outline = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(outline, False)  # KiCad 10: no inferred outline; the board has Edge.Cuts
board_pts = [(outline.COutline(0).CPoint(i).x / IU, outline.COutline(0).CPoint(i).y / IU) for i in range(outline.COutline(0).PointCount())]
board_poly = Polygon(board_pts)


def zone(net_name, layer, prio, clearance, min_w, conn, gap=0.3, spoke=0.5, poly=board_poly, name=""):
    """One zone per polygon: a zone given several outlines from Python was saved with only the first."""
    polys = [poly] if poly.geom_type == "Polygon" else [g for g in poly.geoms if g.geom_type == "Polygon"]
    for i, pg in enumerate(polys):
        z = pcbnew.ZONE(b)
        z.SetNet(net(net_name))
        z.SetLayer(layer)
        z.SetAssignedPriority(prio)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(min_w))
        z.SetPadConnection(conn)
        z.SetThermalReliefGap(mm(gap))
        z.SetThermalReliefSpokeWidth(mm(spoke))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetZoneName((name or f"{net_name}_{b.GetLayerName(layer)}") + (f"_{i}" if len(polys) > 1 else ""))
        o = z.Outline()
        o.NewOutline()
        for x, y in list(pg.exterior.coords)[:-1]:
            o.Append(mm(x), mm(y))
        b.Add(z)
    return len(polys)


# 3. inner GND planes
for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
    zone("GND", layer, 0, 0.35, 0.25, pcbnew.ZONE_CONNECTION_THERMAL, gap=0.35, spoke=0.5)

# 4. power fills: outline = own copper on the layer grown by GROW
GROW_NET = {"BAT_RAW": 2.0, "BAT_F": 2.5, "VBAT": 2.5, "SW_BOOST": 1.0}
FAT = ["BAT_RAW", "BAT_F", "VBAT", "SW_BOOST", "VBOOST", "VBUS", "VBUS_F", "V5", "LYRA_5V", "V5_LED_SW", "V5_LED", "V5_LYRA", "LYRA_5V_D"]


def copper(net_name, layer):
    """The net's copper on a layer: tracks as round-capped lines, vias as discs, pads as their turned bounding
    rectangles. Only the outline of a fill comes from this; KiCad does the clearances."""
    parts = []
    for t in b.GetTracks():
        if t.GetNetname() != net_name or not t.IsOnLayer(layer):
            continue
        if t.GetClass() == "PCB_VIA":
            parts.append(Point(t.GetPosition().x / IU, t.GetPosition().y / IU).buffer(t.GetWidth(layer) / IU / 2))
        else:
            parts.append(LineString([(t.GetStart().x / IU, t.GetStart().y / IU), (t.GetEnd().x / IU, t.GetEnd().y / IU)]).buffer(t.GetWidth() / IU / 2))
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() == net_name and p.IsOnLayer(layer):
                w, h = p.GetSize(layer).x / IU, p.GetSize(layer).y / IU
                r = box(-w / 2, -h / 2, w / 2, h / 2)
                r = rotate(r, -p.GetOrientationDegrees(), origin=(0, 0))
                parts.append(translate(r, p.GetPosition().x / IU, p.GetPosition().y / IU))
    return unary_union(parts)


keep_all = unary_union([p for _, p in keepouts])
fills = 0
for name in FAT:
    if not b.FindNet(name):
        continue
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        c = copper(name, layer)
        if c.is_empty:
            continue
        poly = c.buffer(GROW_NET.get(name, 1.0), join_style=1).intersection(board_poly).difference(keep_all).buffer(0)
        poly = poly.simplify(0.01)
        if poly.is_empty:
            continue
        fills += zone(name, layer, 2, 0.25, 0.3, pcbnew.ZONE_CONNECTION_FULL, poly=poly)
print(f"power fills: {fills} zones")

# 5. outer GND pours
for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    zone("GND", layer, 1, 0.25, 0.25, pcbnew.ZONE_CONNECTION_THERMAL, gap=0.3, spoke=0.5)

# 6. fill and save
# 6. save unfilled; KiCad fills in a fresh process (kicad_helper.py fill). Filled here, right after the zones are
# created, KiCad kept islands its own DRC then reported as isolated copper; loaded fresh, it removes them.
b.Save(out)
print(f"saved {out} with {len(b.Zones())} zones, unfilled")
