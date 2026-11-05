"""Plated slots from EasyEDA's hole points (review 18, closure 3): synthetic pads through `pcb sync`, then the drill as
pcbnew sees it (its effective hole segment, in board coordinates) against the hole points EasyEDA gives, and the
pad's copper against EasyEDA's own pad outline (field 10). Also J1's four real shell slots.

Usage: python3 slot19.py workdir
"""
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import FX4, U, board, eda, emit, fresh, pcb, project, pyq, slim, smd  # noqa: E402

work = sys.argv[1]
fresh(work)
OX, OY = 4000.0, 3000.0


def tht(num, x, y, w, h, rot, hole_r, slot, hp, shape="RECT"):
    """An EasyEDA plated pad; rot clockwise on screen (y down). Field 10 is its outline, turned."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts += [x + dx * c - dy * s, y + dx * s + dy * c]
    hps = " ".join(f"{v:.4f}" for v in hp) if hp else ""
    return f"PAD~{shape}~{x}~{y}~{w}~{h}~11~~{num}~{hole_r}~{' '.join(f'{v:.4f}' for v in pts)}~{rot}~g{num}~{slot}~{hps}~Y~0", pts


def holepts(x, y, rot_dir, length):
    """Hole points: the slot's centre line, `length` units long, at angle rot_dir clockwise on screen."""
    c, s = math.cos(math.radians(rot_dir)), math.sin(math.radians(rot_dir))
    return [x - c * length / 2, y - s * length / 2, x + c * length / 2, y + s * length / 2]


QUERY = '''
out = {}
for f in b.GetFootprints():
    if f.GetReference() != "U1":
        continue
    o = f.GetPosition()
    for p in f.Pads():
        sh = p.GetEffectiveHoleShape()
        seg = sh.GetSeg()
        poly = p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE)
        ol = poly.Outline(0)
        out[p.GetNumber()] = {"a": [TM(seg.A.x - o.x), TM(seg.A.y - o.y)], "b": [TM(seg.B.x - o.x), TM(seg.B.y - o.y)],
                              "w": TM(sh.GetWidth()), "drill": [TM(p.GetDrillSizeX()), TM(p.GetDrillSizeY())],
                              "angle": p.GetOrientationDegrees(), "fp_angle": f.GetOrientationDegrees(),
                              "copper": [[TM(ol.CPoint(i).x - o.x), TM(ol.CPoint(i).y - o.y)] for i in range(ol.PointCount())]}
print(json.dumps(out))
'''


def compare(got, hp, hole_r, outline):
    """Largest distance between pcbnew's hole segment ends and EasyEDA's hole points (either order), the width, and
    the largest distance from EasyEDA's outline corners to pcbnew's pad copper (mm)."""
    from shapely.geometry import Point, Polygon
    e = [((hp[0] - OX) * U, (hp[1] - OY) * U), ((hp[2] - OX) * U, (hp[3] - OY) * U)]
    a, b = tuple(got["a"]), tuple(got["b"])
    d = min(max(math.dist(a, e[0]), math.dist(b, e[1])), max(math.dist(a, e[1]), math.dist(b, e[0])))
    cu = Polygon(got["copper"])
    corners = [((outline[i] - OX) * U, (outline[i + 1] - OY) * U) for i in range(0, 8, 2)]
    return {"slot_end_error_mm": round(d, 4), "slot_width_mm": round(got["w"], 4), "want_width_mm": round(2 * hole_r * U, 4),
            "outline_error_mm": round(max(cu.exterior.distance(Point(p)) for p in corners), 4), "drill": got["drill"], "angle": got["angle"]}


CASES = [
    # name, pad (w, h, rot), slot direction (clockwise on screen), slot length (hole-point spacing), centre offset
    ("rot0_along", (10, 4, 0), 0, 4, (0, 0)),
    ("rot0_across", (10, 8, 0), 90, 2, (0, 0)),
    ("rot45_along", (10, 4, 45), 45, 4, (0, 0)),
    ("rot30_along", (10, 4, 30), 30, 4, (0, 0)),
    ("rot30_across", (10, 8, 30), 120, 2, (0, 0)),
    ("rot90_along", (10, 4, 90), 90, 4, (0, 0)),
    ("rot135_along", (10, 4, 135), 135, 4, (0, 0)),
    ("rot30_big", (16, 10, 30), 30, 4, (0, 0)),
    ("rot0_big", (16, 10, 0), 0, 4, (0, 0)),
    ("offset_along", (14, 6, 0), 0, 3, (2, 0)),
    ("offset_rot90", (14, 6, 90), 90, 3, (0, 2)),
]
for name, (w, h, rot), sdir, length, (dx, dy) in CASES:
    hr = 1.2
    x, y = OX + 20, OY + 20
    hp = holepts(x + dx, y + dy, sdir, length)
    rec, outline = tht("1", x, y, w, h, rot, hr, length * 1.0 + 2 * hr, hp)
    filler = eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])
    d = project(os.path.join(work, name), [("U1", "x", "", "C9100001"), ("R1", "r", "", "C11")],
                {"N1": [("U1", "1", ""), ("R1", "1", "")]}, {"C9100001": eda([rec], [("1", "1", "P")]), "C11": filler})
    r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
    res = {"sync": slim(r)}
    if r["outcome"] == "done":
        got = pyq(board(d), QUERY)["1"]
        res.update(compare(got, hp, hr, outline))
    emit(f"slot_{name}", **res)

# a slot not along either axis of its pad: refused
rec, _ = tht("1", OX + 20, OY + 20, 10, 4, 0, 1.2, 6.4, holepts(OX + 20, OY + 20, 30, 4))
d = project(os.path.join(work, "diagonal"), [("U1", "x", "", "C9100001"), ("R1", "r", "", "C11")], {"N1": [("U1", "1", ""), ("R1", "1", "")]},
            {"C9100001": eda([rec], [("1", "1", "P")]), "C11": eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])})
emit("slot_diagonal", sync=slim(pcb("sync", "--project", d, "--work", os.path.join(d, "w"))))

# J1's real shell slots (C2765186), in the M4 fixture's sync
d = os.path.join(work, "j1")
shutil.copytree(FX4, d, ignore=shutil.ignore_patterns("make_fixture.py"))
r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
comp = json.load(open(os.path.join(FX4, "parts", "C2765186.easyeda.json")))["result"]["packageDetail"]["dataStr"]
ox, oy = float(comp["head"]["x"]), float(comp["head"]["y"])
OX, OY = ox, oy
got = pyq(board(d), QUERY.replace('"U1"', '"J1"').replace("out[p.GetNumber()] =", "out.setdefault(p.GetNumber(), []).append(").replace(
    '"copper": [[TM(ol.CPoint(i).x - o.x), TM(ol.CPoint(i).y - o.y)] for i in range(ol.PointCount())]}', '"copper": [[TM(ol.CPoint(i).x - o.x), TM(ol.CPoint(i).y - o.y)] for i in range(ol.PointCount())]})'))
errs = []
for s in comp["shape"]:
    f = s.split("~")
    if f[0] == "PAD" and f[13] not in ("", "0"):
        hp = [float(v) for v in f[14].split()]
        best = min(compare(g, hp, float(f[9]), [float(v) for v in f[10].split()][:8] if len(f[10].split()) >= 8 else [float(f[2])] * 8)["slot_end_error_mm"] for g in got[f[8]])
        errs.append([f[8], best])
emit("j1_slots", sync=slim(r), errors_mm=errs)

# a round hole in a pad turned 30 degrees (no slot): written as a custom pad
rec, _ = tht("1", OX + 20, OY + 20, 16, 10, 30, 1.2, 0, None)
d = project(os.path.join(work, "rot30_round"), [("U1", "x", "", "C9100001"), ("R1", "r", "", "C11")], {"N1": [("U1", "1", ""), ("R1", "1", "")]},
            {"C9100001": eda([rec], [("1", "1", "P")]), "C11": eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])})
emit("slot_rot30_round", sync=slim(pcb("sync", "--project", d, "--work", os.path.join(d, "w"))))

# do the wrong drills reach a board that passes pcb check? The part placed on the board, checked
# the board has no copper between the parts, so unconnected_items N1 is expected in every case
for name in ("rot0_big", "rot30_round", "rot30_big", "rot45_along", "rot30_along", "offset_along"):
    d = os.path.join(work, name)
    with open(os.path.join(d, "pcb.toml"), "a") as fh:
        fh.write('\n[[place]]\nref = "U1"\nat = [0, 0]\nrot_deg = 0\nside = "top"\n\n[[place]]\nref = "R1"\nat = [8, 8]\nrot_deg = 0\nside = "top"\n')
    p = pcb("place", "--project", d, "--work", os.path.join(d, "wp"))
    from r19lib import check as _check, short as _short
    c = _check(d, os.path.join(d, "wc"))
    emit(f"slot_{name}_checked", place=slim(p), check=_short(c))
