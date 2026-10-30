"""Check of a zoned board (KiCad zones, a net-tie footprint) against the board it came from.

All board facts come from the fixture file's [zones] table: keep-outs, the plane net and layers, the net tie, the
fills expected and the DRC kinds the zoned board may add. Reads both boards with pcbnew; fails unless:
  A. the net tie is right: the former net's tracks are, at the same ends and widths, either copper inside the tie
     footprint or tracks on its pads' nets; its vias are the footprint's plated pads; every pad has the net the
     fixture gives; the footprint's tie group is exactly the fixture's; nothing is left on the former net;
  B. no zone fill (any layer) enters a keep-out;
  C. the plane layers carry only the plane net, and every plane-net via and plated hole outside the keep-outs
     lands in each plane;
  D. every plated plane-net hole has a thermal relief on each plane (fill covers under 80 % of the ring just
     outside it), and no zone or pad of the plane net has thermal spokes under `spoke_min`;
  E. no hole or via of another net is within `min_gap` (default 0.3 mm) of a plane's fill;
  F. every fill piece touches a pad, track or via of its net;
  G. no saved fill comes closer to another net's copper than its zone's clearance, or to a non-plated hole than
     `npth_gap` (default 0.2 mm); a stale fill fails here;
  H. every fill the fixture expects exists, with at least its minimum area;
  I. KiCad DRC (zones refilled, one board per process) finds no more violations of any kind and nets than on the
     base, except the kinds the fixture allows, each with its reason.
It also prints copper area per net and layer next to an old pour file (circuit JSON), for comparison only.

Usage: python3 verify_zones.py base.kicad_pcb zoned.kicad_pcb fixture.toml [old_pours.json]
"""
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib

import pcbnew

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import kisexp  # noqa: E402
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

IU = 1e6


def drc_counts(path):
    """KiCad DRC by kind and the nets involved, zones refilled in memory (kicad-cli, tests/lib/kisexp.py)."""
    return kisexp.drc_counts(path)


if sys.argv[1] == "--drc":
    print(json.dumps(drc_counts(sys.argv[2])))
    sys.exit(0)

base_p, zoned_p, fixture_p = sys.argv[1:4]
old_p = sys.argv[4] if len(sys.argv) > 4 else None
Z = tomllib.load(open(fixture_p, "rb"))["zones"]
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


tie = Z.get("net_tie")
base = pcbnew.LoadBoard(base_p)
coil_tracks, coil_vias = [], []
if tie:
    coil_tracks = sorted((xy(t.GetStart()), xy(t.GetEnd()), t.GetWidth(), t.GetLayerName()) for t in base.GetTracks() if t.GetNetname() == tie["former_net"] and t.GetClass() != "PCB_VIA")
    coil_tracks = sorted(tuple(sorted((a, c))) + (w, l) for a, c, w, l in coil_tracks)
    coil_vias = sorted((xy(t.GetPosition()), t.GetWidth(pcbnew.F_Cu), t.GetDrillValue()) for t in base.GetTracks() if t.GetNetname() == tie["former_net"] and t.GetClass() == "PCB_VIA")
del base

b = pcbnew.LoadBoard(zoned_p)
L = {b.GetLayerName(lid): lid for lid in b.GetEnabledLayers().CuStack()}

# A
if tie:
    l601 = b.FindFootprintByReference(tie["footprint"])
    pad_nets = set(tie["pads"].values())
    now = []
    for g in l601.GraphicalItems():
        if g.GetLayerName().endswith(".Cu"):
            now.append(tuple(sorted((xy(g.GetStart()), xy(g.GetEnd())))) + (g.GetWidth(), g.GetLayerName()))
    for t in b.GetTracks():
        if t.GetNetname() in pad_nets and t.GetClass() != "PCB_VIA":
            k = tuple(sorted((xy(t.GetStart()), xy(t.GetEnd())))) + (t.GetWidth(), t.GetLayerName())
            if k in coil_tracks:
                now.append(k)
    if sorted(now) != coil_tracks:
        fails.append(f"A: tie copper differs: {len(coil_tracks)} segments before, {len(now)} matched after")
    pads_now = sorted((xy(p.GetPosition()), p.GetSize().x, p.GetDrillSize().x) for p in l601.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH)
    if pads_now != coil_vias:
        fails.append(f"A: former vias {coil_vias} became pads {pads_now}")
    for p in l601.Pads():
        want = tie["pads"].get(p.GetNumber())
        if want != p.GetNetname():
            fails.append(f"A: {tie['footprint']} pad {p.GetNumber()} is on {p.GetNetname()!r}, the fixture says {want!r}")
    if any(t.GetNetname() == tie["former_net"] for t in b.GetTracks()):
        fails.append(f"A: {tie['former_net']} copper left on the board")
    # the pad groups are not readable from Python: read them from the footprint's block in the file
    got = []
    for fp_ in kisexp.parse(open(zoned_p).read()).find_all("footprint"):
        if any(pr.arg(1) == "Reference" and pr.arg(2) == tie["footprint"] for pr in fp_.find_all("property")):
            g_ = fp_.find("net_tie_pad_groups")
            got = g_.items[1:] if g_ else []
    if got != [tie["group"]]:
        fails.append(f"A: {tie['footprint']} tie groups are {got}, the fixture says [{tie['group']!r}]")

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
keeps = [(k["name"], box(*k["rect"]).buffer(k.get("grow", 0), join_style=2) if k.get("grow") else box(*k["rect"])) for k in Z.get("keepouts", [])]
keep_all = unary_union([g for _, g in keeps]) if keeps else Polygon()
for (net, layer), f in fill.items():
    for name, kp in keeps:
        a = f.intersection(kp.buffer(-0.01)).area
        if a > 1e-6:
            fails.append(f"B: {net} fill on {layer} enters the {name} keep-out ({a:.3f} mm2)")

# C, D, E
plane_net = Z["planes"]["net"]
min_gap = Z["planes"].get("min_gap", 0.3)
for layer in Z["planes"]["layers"]:
    nets_here = [n for (n, l) in fill if l == layer]
    if nets_here != [plane_net]:
        fails.append(f"C: {layer} carries {nets_here}, not only {plane_net}")
    plane = fill.get((plane_net, layer), Polygon())
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA":
            continue
        p = Point(t.GetPosition().x / IU, t.GetPosition().y / IU)
        if keep_all.contains(p):
            continue
        if t.GetNetname() == plane_net:
            if not plane.contains(p):
                fails.append(f"C: {plane_net} via at {xy(t.GetPosition())} misses the {layer} plane")
        else:
            d = plane.distance(p) - t.GetWidth(b.GetLayerID(layer)) / IU / 2
            if d < min_gap - 1e-3:
                fails.append(f"E: {t.GetNetname()} via at {xy(t.GetPosition())} is {d:.3f} mm from the {layer} plane")
    for f in b.GetFootprints():
        for pd in f.Pads():
            if pd.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
                continue
            p = Point(pd.GetPosition().x / IU, pd.GetPosition().y / IU)
            if keep_all.contains(p):
                continue
            shape = pad_poly(pd)
            if pd.GetNetname() == plane_net:
                # the relief gap: a ring just outside the pad and inside the plane's thermal gap (review 5, 9)
                gap = Z["planes"].get("thermal_gap", Z["planes"].get("clearance", 0.35))
                ring = shape.buffer(gap * 6 / 7).difference(shape.buffer(gap / 7))
                cov = plane.intersection(ring).area / ring.area
                if cov == 0:
                    fails.append(f"C: {plane_net} pad {f.GetReference()}.{pd.GetNumber()} not joined to the {layer} plane")
                elif cov > 0.8:
                    fails.append(f"D: {plane_net} pad {f.GetReference()}.{pd.GetNumber()} has no thermal relief on {layer} ({cov:.0%} covered)")
            elif pd.GetNetname():
                d = plane.distance(shape)
                if d < min_gap - 1e-3:
                    fails.append(f"E: {pd.GetNetname()} pad {f.GetReference()}.{pd.GetNumber()} is {d:.3f} mm from the {layer} plane")

# F: every fill piece touches copper of its net
items = collections.defaultdict(list)
for t in b.GetTracks():
    for name, lid in L.items():
        if t.IsOnLayer(lid):
            if t.GetClass() == "PCB_VIA":
                items[(t.GetNetname(), name)].append(Point(t.GetPosition().x / IU, t.GetPosition().y / IU).buffer(t.GetWidth(lid) / IU / 2))
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

# D (spokes): zones of the plane net and pads overriding them
spoke_min = Z.get("spoke_min")
if spoke_min:
    for z in b.Zones():
        if not z.GetIsRuleArea() and z.GetNetname() == plane_net and z.GetThermalReliefSpokeWidth() / IU < spoke_min - 1e-6:
            fails.append(f"D: zone {z.GetZoneName()} has {z.GetThermalReliefSpokeWidth() / IU} mm spokes, under {spoke_min}")
    for f in b.GetFootprints():
        for pd in f.Pads():
            # KiCad 10: an optional override, None when the pad takes the zone's spoke width
            w_ = pd.GetLocalThermalSpokeWidthOverride() or 0
            if pd.GetNetname() == plane_net and 0 < w_ / IU < spoke_min - 1e-6:
                fails.append(f"D: pad {f.GetReference()}.{pd.GetNumber()} has {w_ / IU} mm spokes, under {spoke_min}")

# G: saved fill against other nets' copper, per zone, at that zone's clearance
other = collections.defaultdict(list)
for (net, layer), geoms in items.items():
    for g in geoms:
        other[layer].append((net, g))
trees = {layer: (STRtree([g for _, g in v]), v) for layer, v in other.items()}
for z in b.Zones():
    if z.GetIsRuleArea():
        continue
    clr = z.GetLocalClearance() / IU
    for name, lid in L.items():
        if not z.IsOnLayer(lid) or name not in trees:
            continue
        tree, v = trees[name]
        for poly in polys(z.GetFilledPolysList(lid)):
            for i in tree.query(poly.buffer(clr - 0.01)):
                net, g = v[i]
                # copper with no net is a non-plated hole's pad: held to `npth_gap`, not the zone clearance
                need = clr if net else Z.get("npth_gap", 0.2)
                if net != z.GetNetname() and poly.distance(g) < need - 0.01:
                    fails.append(f"G: {z.GetZoneName()} fill is {poly.distance(g):.3f} mm from {net or 'non-plated hole'} copper on {name}, needs {need}")
                    break

# H: expected fills
for e in Z.get("expect_fill", []):
    got = fill.get((e["net"], e["layer"]))
    a = got.area if got is not None else 0.0
    if a < e["min_area"]:
        fails.append(f"H: {e['net']} fill on {e['layer']} is {a:.1f} mm2, expected at least {e['min_area']}")

# I: DRC against the base, each board in its own process
def child_drc(path):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--drc", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"DRC of {path} failed: {r.stderr[-1500:]}")
    return collections.Counter(json.loads([ln for ln in r.stdout.splitlines() if ln.startswith("{")][-1]))


# each allowed kind names how many violations the zoned board may have of it (review 6, K2: a kind allowed without
# a count let any number of new violations through)
allowed = {}
for a in Z.get("drc_allowed", []):
    if not isinstance(a.get("max"), int):
        raise SystemExit(f"drc_allowed {a['kind']!r} needs a max count")
    allowed[a["kind"]] = a["max"]
d0, d1 = child_drc(base_p), child_drc(zoned_p)
for k in sorted(set(d0) | set(d1)):
    if d1[k] > d0[k] and d1[k] > allowed.get(k, d0[k]):
        fails.append(f"I: DRC {k} {d0[k]} -> {d1[k]}" + (f" (allowed {allowed[k]})" if k in allowed else ""))

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

print(json.dumps({"ok": not fails, "fails": fails, "planes": {l: area.get((plane_net, l)) for l in Z["planes"]["layers"]}, "drc": {"base": sum(d0.values()), "zoned": sum(d1.values())}, "areas": {f"{k[0]} {k[1]}": v for k, v in sorted(area.items())}, "outer_vs_old": cmp}, indent=1))
sys.exit(0 if not fails else 1)
