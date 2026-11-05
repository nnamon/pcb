"""The M4 release's fabrication layers that do not depend on routing, against paddle-keyer v1.0.0's ordered Gerbers,
read here with gerbonara and shapely (none of pcb's own Gerber code).

Same parts at the same places should give the same openings, whatever the footprint library drew:
  A. every component hole (over 0.4 mm; vias belong to the routing) of one set has a hole of the other within 0.05 mm, of the same diameter (0.05 mm) and plating;
  B. every paste opening of each set has its centre inside a paste opening of the other (pin-in-paste included);
  C. every solder-mask opening of each set has its centre inside a mask opening of the other.
Both sets are centred on their outlines.

Usage: python3 verify_against_v1.py release_gerbers.zip golden_gerbers.zip
"""
import json
import os
import re
import sys
import tempfile
import zipfile

from gerbonara import GerberFile
from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

fails = []


def unzip(z):
    d = tempfile.mkdtemp(prefix="v1cmp_")
    zipfile.ZipFile(z).extractall(d)
    return {f: os.path.join(d, f) for f in os.listdir(d)}


def shape(p):
    if isinstance(p, Line):
        return LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2) if (p.x1, p.y1) != (p.x2, p.y2) else Point(p.x1, p.y1).buffer(p.width / 2)
    if isinstance(p, Circle):
        return Point(p.x, p.y).buffer(p.r)
    if isinstance(p, Rectangle):
        g = box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
        return rotate(g, p.rotation, origin=(p.x, p.y), use_radians=True) if p.rotation else g
    if isinstance(p, Arc):
        p = p.to_arc_poly()
    if isinstance(p, ArcPoly):
        try:
            pts = [tuple(q) for q, _, _ in p.approximate_arcs().segments]
        except ZeroDivisionError:
            pts = [tuple(q) for q in p.outline]
        return Polygon(pts).buffer(0) if len(pts) >= 3 else None
    return None


def layer(path):
    g = GerberFile.open(path)
    dark = []
    for o in g.objects:
        for p in o.to_primitives(unit="mm"):
            s = shape(p)
            if s is not None and getattr(p, "polarity_dark", True):
                dark.append(s)
    return unary_union(dark)


def pick(files, pats):
    for n, p in files.items():
        if any(re.search(x, n, re.I) for x in pats):
            return p
    return None


def holes(files):
    out = []
    for n, p in files.items():
        if not n.lower().endswith(".drl"):
            continue
        plated = "npth" not in n.lower()
        t = open(p).read()
        tools = {m[0]: float(m[1]) for m in re.findall(r"^T(\d+)C([0-9.]+)", t, re.M)}
        cur, last = None, None
        lines = t.splitlines()
        for k, ln in enumerate(lines):
            m = re.match(r"^T(\d+)$", ln)
            if m:
                cur = tools.get(m[1])
                continue
            # a slot: X..Y..G85X..Y.. on one line, or a hole line followed by G85X..Y..; counted at its middle
            m = re.match(r"^X(-?[0-9.]+)Y(-?[0-9.]+)(?:G85X(-?[0-9.]+)Y(-?[0-9.]+))?$", ln)
            if m and cur is not None:
                x, y = float(m[1]), float(m[2])
                if m[3]:
                    x, y = (x + float(m[3])) / 2, (y + float(m[4])) / 2
                elif k + 1 < len(lines) and (n := re.match(r"^G85X(-?[0-9.]+)Y(-?[0-9.]+)$", lines[k + 1])):
                    x, y = (x + float(n[1])) / 2, (y + float(n[2])) / 2
                out.append((x, y, cur, plated))
    return out


def centre(files):
    e = layer(pick(files, [r"edge", r"\.gm1$", r"\.gko$"]))
    x0, y0, x1, y1 = e.bounds
    return (x0 + x1) / 2, (y0 + y1) / 2


a, b = unzip(sys.argv[1]), unzip(sys.argv[2])
ca, cb = centre(a), centre(b)
# A
# component holes: vias (0.4 mm and under) belong to the routing, which differs
ha = [(x - ca[0], y - ca[1], d, pl) for x, y, d, pl in holes(a) if d > 0.4]
hb = [(x - cb[0], y - cb[1], d, pl) for x, y, d, pl in holes(b) if d > 0.4]
for one, other, nm in ((ha, hb, "release"), (hb, ha, "v1.0.0")):
    for x, y, d, pl in one:
        if not any(abs(x - X) < 0.05 and abs(y - Y) < 0.05 and abs(d - D) < 0.05 and pl == PL for X, Y, D, PL in other):
            fails.append(f"A: {nm} hole at ({x:.3f}, {y:.3f}) d {d} {'PTH' if pl else 'NPTH'} has no match")
# B, C
for key, pats in (("B: F.Paste", [r"f[._-]?paste", r"\.gtp$"]), ("C: F.Mask", [r"f[._-]?mask", r"\.gts$"])):
    la = translate(layer(pick(a, pats)), -ca[0], -ca[1])
    lb = translate(layer(pick(b, pats)), -cb[0], -cb[1])
    for one, other, nm in ((la, lb, "release"), (lb, la, "v1.0.0")):
        for g in getattr(one, "geoms", [one]):
            c = g.representative_point()
            if not other.buffer(0.02).contains(c):
                fails.append(f"{key}: {nm} opening at ({c.x:.3f}, {c.y:.3f}), {g.area:.3f} mm², has no opening in the other set")

print(json.dumps({"holes": [len(ha), len(hb)], "fails": fails[:30], "n_fails": len(fails)}, indent=1))
sys.exit(1 if fails else 0)
