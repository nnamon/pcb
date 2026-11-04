"""The M4 release against what paddle-keyer v1.0.0 sent to JLCPCB, layer against layer: every v1.0.0 paste opening
inside a pad of the M4 board's paste, every M4 opening holding a v1.0.0 one, and every drilled hole (plated and not)
at the same place and size. The fixture's own oracle compares only BOM and CPL rows, which [[place]] copied from
v1.0.0's CPL; this compares copper.

Usage: python3 golden18.py workdir   (PCB_R18_RELEASE: the flow's release folder)
"""
import glob
import os
import sys
import zipfile

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely import affinity

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import TESTS, emit, fresh  # noqa: E402

work = sys.argv[1]
fresh(work)
rel = os.environ.get("PCB_R18_RELEASE")
GOLD = os.path.join(TESTS, "fixtures", "paddle_keyer_v1", "golden", "paddle-keyer_v1.0.0_gerbers.zip")


def shapes(path):
    from gerbonara import GerberFile
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
    from gerbonara.utils import MM
    out = []
    for o in GerberFile.open(path).objects:
        for p in o.to_primitives(MM):
            if not p.polarity_dark:
                continue
            if isinstance(p, Line):
                g = LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2) if (p.x1, p.y1) != (p.x2, p.y2) else Point(p.x1, p.y1).buffer(p.width / 2)
            elif isinstance(p, Circle):
                g = Point(p.x, p.y).buffer(p.r)
            elif isinstance(p, Rectangle):
                g = box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
                g = affinity.rotate(g, p.rotation, origin=(p.x, p.y), use_radians=True) if p.rotation else g
            elif isinstance(p, (Arc, ArcPoly)):
                p = p.to_arc_poly() if isinstance(p, Arc) else p
                pts = [tuple(q) for q, _, _ in p.approximate_arcs().segments]
                g = Polygon(pts).buffer(0) if len(pts) > 2 else None
            else:
                g = None
            if g is not None and not g.is_empty:
                out.append(g)
    return unary_union(out)


def holes(path):
    from gerbonara import ExcellonFile
    from gerbonara.utils import MM
    out = []
    for o in ExcellonFile.open(path).objects:
        for p in o.to_primitives(MM):
            if hasattr(p, "x1"):
                out.append(((p.x1 + p.x2) / 2, (p.y1 + p.y2) / 2, round(p.width, 3), round(((p.x2 - p.x1) ** 2 + (p.y2 - p.y1) ** 2) ** 0.5, 3)))
            else:
                out.append((p.x, p.y, round(2 * p.r, 3), 0.0))
    return out


def unpack(z, d):
    os.makedirs(d, exist_ok=True)
    zipfile.ZipFile(z).extractall(d)
    return d


g = unpack(GOLD, os.path.join(work, "gold"))
m = unpack(glob.glob(os.path.join(rel, "*_gerbers.zip"))[0], os.path.join(work, "m4"))
pick = lambda d, *names: next(os.path.join(d, f) for f in os.listdir(d) if any(n.lower() in f.lower() for n in names))
ge, me = shapes(pick(g, "Edge_Cuts")), shapes(pick(m, "Edge_Cuts"))
gc, mc = ge.envelope.centroid, me.envelope.centroid
gp = affinity.translate(shapes(pick(g, "F_Paste")), -gc.x, -gc.y)
mp = affinity.translate(shapes(pick(m, "F_Paste")), -mc.x, -mc.y)
gparts = list(getattr(gp, "geoms", [gp]))
mparts = list(getattr(mp, "geoms", [mp]))
outside = [(round(x.centroid.x, 3), round(x.centroid.y, 3)) for x in gparts if not mp.buffer(0.03).contains(x)]
def nearest(x):
    y = min(mparts, key=lambda q: q.centroid.distance(x.centroid))
    return y
offs = sorted(((round(x.centroid.distance(nearest(x).centroid), 3), (round(x.centroid.x, 2), round(x.centroid.y, 2)), [round(v, 2) for v in (x.bounds[2] - x.bounds[0], x.bounds[3] - x.bounds[1])],
               [round(v, 2) for v in (nearest(x).bounds[2] - nearest(x).bounds[0], nearest(x).bounds[3] - nearest(x).bounds[1])]) for x in gparts), reverse=True)
empty = [(round(x.centroid.x, 3), round(x.centroid.y, 3)) for x in mparts if not any(x.contains(y.centroid) for y in gparts)]
# designer's edit (CI): `pick` took whichever drill file the folder listed first, so on one filesystem the set held
# v1.0.0's vias (which routing places anew) and on another only its NPTH holes; read every drill file of both sets and
# compare component holes (over 0.4 mm), as the control means
gh = [(x - gc.x, y - gc.y, w, l) for f in sorted(glob.glob(os.path.join(g, "*.drl"))) for x, y, w, l in holes(f) if w > 0.4]
mh = [(x - mc.x, y - mc.y, w, l) for f in sorted(glob.glob(os.path.join(m, "*.drl"))) for x, y, w, l in holes(f) if w > 0.4]
# gerbonara also reports a slot written as a hole line and a G85 line (v1.0.0's files) as a hole at its start
gh = [h for h in gh if h[3] > 0 or not any(k[3] > 0 and abs(k[2] - h[2]) < 0.02 and ((k[0] - h[0]) ** 2 + (k[1] - h[1]) ** 2) ** 0.5 <= k[3] / 2 + 0.01 for k in gh)]
mh = [h for h in mh if h[3] > 0 or not any(k[3] > 0 and abs(k[2] - h[2]) < 0.02 and ((k[0] - h[0]) ** 2 + (k[1] - h[1]) ** 2) ** 0.5 <= k[3] / 2 + 0.01 for k in mh)]
unmatched = []
for h in gh:
    best = min(mh, key=lambda k: (k[0] - h[0]) ** 2 + (k[1] - h[1]) ** 2)
    dd = ((best[0] - h[0]) ** 2 + (best[1] - h[1]) ** 2) ** 0.5
    if dd > 0.02 or abs(best[2] - h[2]) > 0.02 or abs(best[3] - h[3]) > 0.02:
        unmatched.append({"v1": [round(v, 3) for v in h], "m4": [round(v, 3) for v in best], "off": round(dd, 3)})
emit("golden_copper", gold_paste=len(gparts), m4_paste=len(mparts), gold_outside_m4_paste=outside[:20], n_outside=len(outside), largest_centre_offsets=offs[:15], n_offset_over_0_05=sum(1 for o in offs if o[0] > 0.05), gold_paste_with_no_m4_pad=[o for o in offs if o[0] > 0.5],
     m4_paste_without_gold=empty[:20], n_empty=len(empty), gold_holes=len(gh), m4_holes=len(mh), holes_unmatched=unmatched[:12], n_holes_unmatched=len(unmatched),
     outline_sizes=[[round(v, 3) for v in ge.bounds], [round(v, 3) for v in me.bounds]])
