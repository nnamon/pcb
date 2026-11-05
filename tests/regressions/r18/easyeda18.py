"""EasyEDA footprint conversion against EasyEDA's own geometry: every pad outline and hole of the fixture's cached
parts, and hand-made components with turned pads, polygon pads and slots, put on a board by `pcb sync` and read
back with pcbnew. EasyEDA's geometry is read here from the PAD records directly: the outline points (field 10) for
RECT and POLYGON pads, the stadium for OVAL, and the slot's end points (field 14) for its direction.

Usage: python3 easyeda18.py workdir
"""
import glob
import json
import math
import os
import shutil
import sys

from shapely.geometry import LineString, Point, Polygon
from shapely import affinity

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import FX, U, eda_component, emit, fresh, pcb, pyq, slim, synth_project  # noqa: E402

work = sys.argv[1]
fresh(work)

READ = r'''
def lc(f):
    try:
        return f.GetFieldText("LCSC")
    except KeyError:
        return ""
out = {}
for f in b.GetFootprints():
    pos = f.GetPosition()
    pads = []
    for p in f.Pads():
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            pads.append({"n": "", "npth": True, "x": mm(p.GetPosition().x - pos.x), "y": mm(p.GetPosition().y - pos.y), "drill": [mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())]})
            continue
        lay = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        ps = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
        polys = []
        for k in range(ps.OutlineCount()):
            o = ps.Outline(k)
            polys.append([[mm(o.CPoint(i).x - pos.x), mm(o.CPoint(i).y - pos.y)] for i in range(o.PointCount())])
        d = None
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            d = {"size": [mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())], "ang": p.GetOrientationDegrees(), "x": mm(p.GetPosition().x - pos.x), "y": mm(p.GetPosition().y - pos.y)}
        pads.append({"n": p.GetNumber(), "polys": polys, "drill": d, "layer": "F" if lay == pcbnew.F_Cu else "B"})
    out[f.GetReference()] = {"rot": f.GetOrientationDegrees(), "flip": f.IsFlipped(), "lcsc": lc(f), "pads": pads}
print(json.dumps(out))
'''


def eda_pads(comp):
    """Each PAD as (number, shapely outline in mm y down about the origin, hole info)."""
    ds = comp["result"]["packageDetail"]["dataStr"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    L = lambda x, y: ((float(x) - ox) * U, (float(y) - oy) * U)
    out = []
    for s in ds["shape"]:
        f = s.split("~")
        if f[0] == "PAD":
            shape, cx, cy, w, h, layer, num = f[1], f[2], f[3], float(f[4]) * U, float(f[5]) * U, f[6], f[8]
            rot = float(f[11] or 0)
            c = L(cx, cy)
            pts = [float(v) for v in f[10].replace(",", " ").split()] if f[10].strip() else []
            pts = [L(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
            if shape in ("RECT", "POLYGON") and len(pts) >= 3:
                g = Polygon(pts)
            elif shape == "OVAL" and len(pts) == 2:
                # the stadium's centre line, as EasyEDA stores it
                g = LineString(pts).buffer(min(w, h) / 2, 64)
            elif shape in ("OVAL", "ELLIPSE"):
                r = min(w, h) / 2
                hl = max(w, h) / 2 - r
                base = LineString([(-hl, 0), (hl, 0)] if w >= h else [(0, -hl), (0, hl)]).buffer(r, 64) if hl > 1e-9 else Point(0, 0).buffer(r, 64)
                # EasyEDA's turn: clockwise on screen (y down), the sign pcb assumes; ambiguous only off quarter turns
                g = affinity.translate(affinity.rotate(base, rot, origin=(0, 0)), *c)
            else:
                g = affinity.translate(affinity.rotate(Polygon([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]), rot, origin=(0, 0)), *c)
            hole = None
            if f[9].strip() and float(f[9]) > 0:
                hr = float(f[9]) * U
                hlen = float(f[13]) * U if len(f) > 13 and f[13].strip() else 0
                hp = [float(v) for v in f[14].replace(",", " ").split()] if len(f) > 14 and f[14].strip() else []
                direction = None
                if hlen > 0 and len(hp) >= 4:
                    direction = math.degrees(math.atan2(hp[3] - hp[1], hp[2] - hp[0])) % 180
                hole = {"d": 2 * hr, "len": hlen, "dir": direction, "at": c}
            out.append((num, g, hole, layer, shape, rot))
    return out


def kicad_slot_dir(d):
    """The direction (degrees, y down frame, mod 180) of a KiCad oval drill: its long axis in the pad frame turned by
    the pad angle (anticlockwise on screen, so negative in a y-down frame)."""
    sx, sy = d["size"]
    if abs(sx - sy) < 1e-6:
        return None
    base = 0 if sx > sy else 90
    return (base - d["ang"]) % 180


def compare(ref, comp, kpads):
    misses = []
    ep = eda_pads(comp)
    kp = [p for p in kpads if not p.get("npth")]
    if len(ep) != len(kp):
        misses.append(f"{ref}: {len(ep)} EasyEDA pads, {len(kp)} on the board")
    used = set()
    for num, g, hole, layer, shape, rot in ep:
        best = None
        for i, p in enumerate(kp):
            if i in used or p["n"] != num:
                continue
            kg = Polygon(p["polys"][0]) if p["polys"] else None
            if kg is None:
                continue
            diff = g.symmetric_difference(kg).area
            if best is None or diff < best[0]:
                best = (diff, i, kg)
        if best is None:
            misses.append(f"{ref}.{num}: no board pad")
            continue
        used.add(best[1])
        diff, i, kg = best
        tol = max(0.002, 0.01 * g.area)
        if diff > tol:
            misses.append(f"{ref}.{num} {shape} rot {rot}: outline differs by {diff:.4f} mm2 (pad {g.area:.4f} mm2)")
        if (layer == "11") != (kp[i]["drill"] is not None):
            misses.append(f"{ref}.{num}: plated hole {'missing' if layer == '11' else 'extra'}")
        if hole and kp[i]["drill"]:
            d = kp[i]["drill"]
            want = sorted([hole["d"], hole["len"] if hole["len"] > 0 else hole["d"]])
            if max(abs(a - b) for a, b in zip(sorted(d["size"]), want)) > 2e-3:
                misses.append(f"{ref}.{num}: drill {d['size']} not {want}")
            if hole["dir"] is not None:
                kd = kicad_slot_dir(d)
                if kd is None or min(abs(kd - hole["dir"]), 180 - abs(kd - hole["dir"])) > 1:
                    misses.append(f"{ref}.{num}: slot runs at {kd} degrees, EasyEDA's hole points at {hole['dir']:.1f}")
    return misses


# 1. the fixture's 26 cached parts, as pcb sync puts them on a new board (all at angle 0, top)
d = os.path.join(work, "fixture")
shutil.copytree(FX, d, ignore=shutil.ignore_patterns("make_fixture.py"))
r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
kb = pyq(os.path.join(d, "board.kicad_pcb"), READ)
misses, checked = [], 0
for ref, f in kb.items():
    if not f["lcsc"]:
        continue
    comp = json.load(open(os.path.join(d, "parts", f"{f['lcsc']}.easyeda.json")))
    misses += compare(ref, comp, f["pads"])
    checked += 1
emit("fixture_parts", sync=slim(r), parts=checked, misses=misses[:30], n_misses=len(misses))

# 2. hand-made pads
def pad(shape, x, y, w, h, layer, num, hole_r=0, pts="", rot=0, hlen="", hpts="", plated="Y"):
    return f"PAD~{shape}~{x}~{y}~{w}~{h}~{layer}~~{num}~{hole_r}~{pts}~{rot}~g{num}~{hlen}~{hpts}~{plated}~0"


def rect_pts(cx, cy, w, h, rot):
    a = math.radians(rot)
    c = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    # EasyEDA: clockwise on screen, y down: x' = x cos - y sin, y' = x sin + y cos
    return " ".join(f"{cx + px * math.cos(a) - py * math.sin(a):.4f} {cy + px * math.sin(a) + py * math.cos(a):.4f}" for px, py in c)


cases = {
    "rect_30": [pad("RECT", 4000, 3000, 8, 4, 1, "1", pts=rect_pts(4000, 3000, 8, 4, 30), rot=30), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "rect_90_tht": [pad("RECT", 4000, 3000, 8, 4, 11, "1", hole_r=1.2, pts=rect_pts(4000, 3000, 8, 4, 90), rot=90), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "polygon_hole": [pad("POLYGON", 4000, 3000, 8, 8, 11, "1", hole_r=1.5, pts="3996 2996 4004 2996 4004 3004 4000 3006 3996 3004"), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "oval_slot_long": [pad("OVAL", 4000, 3000, 4, 8, 11, "1", hole_r=1.0, pts="4000 2998 4000 3002", hlen=6, hpts="4000 2998 4000 3002"), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "oval_slot_turned": [pad("OVAL", 4000, 3000, 4, 8, 11, "1", hole_r=1.0, pts="3998 3000 4002 3000", rot=90, hlen=6, hpts="3998 3000 4002 3000"), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    # a round pad with a slot across it: the slot's direction is only in its end points
    "round_slot_x": [pad("ELLIPSE", 4000, 3000, 8, 8, 11, "1", hole_r=1.0, hlen=6, hpts="3998 3000 4002 3000"), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    # a rectangular pad whose slot runs across its short side (a pad drawn wider than the slot is long)
    "rect_slot_across": [pad("RECT", 4000, 3000, 10, 8, 11, "1", hole_r=1.0, pts=rect_pts(4000, 3000, 10, 8, 0), hlen=6, hpts="4000 2998 4000 3002"), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "oval_45": [pad("OVAL", 4000, 3000, 4, 8, 1, "1", pts="3998.5858 2998.5858 4001.4142 3001.4142", rot=45), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "bottom_smd": [pad("RECT", 4000, 3000, 8, 4, 2, "1", pts=rect_pts(4000, 3000, 8, 4, 0)), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
    "unplated_pad": [pad("ELLIPSE", 4000, 3000, 8, 8, 11, "1", hole_r=2, plated="N"), pad("RECT", 4030, 3000, 4, 4, 1, "2", pts=rect_pts(4030, 3000, 4, 4, 0))],
}
for k, (name, pads) in enumerate(cases.items()):
    code = f"C7{k:06d}"
    comp = eda_component(pads, [("1", "A"), ("2", "B")])
    dd = os.path.join(work, name)
    os.makedirs(dd)
    synth_project(dd, [("U1", "x", "", code), ("R1", "r", "", code)], {"N1": [("U1", "1", "A"), ("R1", "1", "A")], "N2": [("U1", "2", "B"), ("R1", "2", "B")]}, {code: comp})
    r = pcb("sync", "--project", dd, "--work", os.path.join(dd, "w"))
    m = None
    if r["outcome"] == "done":
        kb = pyq(os.path.join(dd, "board.kicad_pcb"), READ)
        m = compare("U1", comp, kb["U1"]["pads"])
    emit(f"synthetic_{name}", sync=slim(r), misses=m)
