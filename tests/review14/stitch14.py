"""Review 14: stitching closures (review 13, findings 3, 4, 5, 9, 13) on synthetic boards, read back with pcbnew.
One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 stitch14.py workdir
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r14lib as L  # noqa: E402
from shapely.geometry import Point, Polygon  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

PLANES = """[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3
"""


def new_vias(path, net="GND"):
    return [v for v in L.shapes(path)["vias"] if v["net"] == net]


def pad_gaps(path, net="GND"):
    """For each pad (ref.num): the smallest gap from a new via's copper to the pad's copper on any layer."""
    s = L.shapes(path)
    vias = [v for v in s["vias"] if v["net"] == net]
    out = {}
    for p in s["pads"]:
        g = L.mp(p["polys"])
        if g.is_empty:
            continue
        key = f"{p['ref']}.{p['num']}"
        for v in vias:
            d = g.distance(Point(v["x"], v["y"])) - v["size"] / 2
            out[key] = min(out.get(key, 99.0), round(d, 3))
    return out, len(vias)


# 1. pads of every shape, turned, on the bottom, through-hole and custom: no via within the margin of any pad copper
spec = {"layers": 2, "fps": [
    {"ref": "A1", "at": (12, 12), "pads": [{"num": "1", "at": (12, 12), "size": (4, 4), "rot": 45, "net": "GND"}]},
    {"ref": "A2", "at": (24, 12), "pads": [{"num": "1", "at": (24, 12), "size": (4, 4), "shape": "circle", "net": "GND"}]},
    {"ref": "A3", "at": (36, 12), "pads": [{"num": "1", "at": (36, 12), "size": (5, 2), "shape": "oval", "rot": 30, "net": "GND"}]},
    {"ref": "A4", "at": (48, 12), "rot": 30, "pads": [{"num": "1", "at": (48, 12), "size": (4, 3), "shape": "roundrect", "net": "GND"}]},
    {"ref": "A5", "at": (12, 28), "side": "bottom", "pads": [{"num": "1", "at": (12, 28), "size": (4, 4), "rot": 20, "net": "GND"}]},
    {"ref": "A6", "at": (24, 28), "pads": [{"num": "1", "at": (24, 28), "size": (3, 3), "shape": "circle", "kind": "tht", "drill": 1.2, "net": "GND"}]},
    {"ref": "A8", "at": (48, 28), "pads": [{"num": "1", "at": (48, 28), "size": (3, 3), "rot": 45, "net": "SIG"}]}]}
CUSTOM = """
f = pcbnew.FOOTPRINT(b); f.SetReference("A7"); f.SetValue("A7"); f.SetPosition(V(36, 28)); b.Add(f)
p = pcbnew.PAD(f); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_CUSTOM); p.SetAnchorPadShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECT)
p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask()); p.SetSize(V(0.4, 0.4))
pts = pcbnew.VECTOR_VECTOR2I()
for x, y in [(-2, -2), (2, -2), (2, 2), (-2, 2)]:
    pts.append(V(x, y))
p.AddPrimitivePoly(pcbnew.F_Cu, pts, 0, True)
f.Add(p); p.SetPosition(V(36, 28)); p.SetNet(net("GND"))
"""
for name, code in [("pad_shapes", None), ("pad_custom", CUSTOM)]:
    d = L.build(os.path.join(work, name), spec, PLANES + """connect = "solid"

[[stitch]]
net = "GND"
pitch_mm = 1.0
size_mm = 0.6
drill_mm = 0.3
margin_mm = 0.3
""", code)
    v, code_, prob, out = L.zone(d)
    res = {}
    if v.get("outcome") in ("done", "rejected"):
        gaps, n = pad_gaps(v["data"]["written"])
        res = dict(n_vias=n, gaps=gaps, too_close=sorted(k for k, g in gaps.items() if g < 0.3 - 0.005))
    L.emit(name, contract=prob, **L.summary(v), **res)

# 2. keep-outs that forbid vias: from pcb.toml on one inner layer with grow_mm, drawn on the board by hand, and inside a
#    footprint (a module's antenna keep-out)
BASE4 = {"layers": 4, "fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}]}
PLANES4 = """[[zone]]
net = "GND"
layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
clearance_mm = 0.3

[[stitch]]
net = "GND"
pitch_mm = 1.5
size_mm = 0.6
drill_mm = 0.3
"""
RULE = """
z = pcbnew.ZONE({parent}); z.SetIsRuleArea(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowTracks(False); z.SetDoNotAllowZoneFills(False)
z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Cu); ls.AddLayer(pcbnew.B_Cu); z.SetLayerSet(ls)
o = z.Outline(); o.NewOutline()
for x, y in [(20, 10), (40, 10), (40, 30), (20, 30)]:
    o.Append(mm(x), mm(y))
z.SetZoneName("{name}")
"""
cases = [
    ("keepout_inner_grow", '[[keepout]]\nname = "k"\nrect = [21, 11, 39, 29]\ngrow_mm = 1.0\nlayers = ["In2.Cu"]\nforbid = ["via"]\n', None),
    ("keepout_board_rule_area", "", RULE.format(parent="b", name="hand") + "b.Add(z)\n"),
    ("keepout_footprint_rule_area", "", "f = pcbnew.FOOTPRINT(b); f.SetReference('M1'); f.SetValue('M1'); f.SetPosition(V(30, 20)); b.Add(f)\n"
     + RULE.format(parent="f", name="ant") + "f.Add(z)\n"),
]
for name, extra, code in cases:
    d = L.build(os.path.join(work, name), BASE4, PLANES4 + "\n" + extra, code)
    v, code_, prob, out = L.zone(d)
    res = {}
    if v.get("outcome") in ("done", "rejected"):
        vs = new_vias(v["data"]["written"])
        area = Polygon([(20, 10), (40, 10), (40, 30), (20, 30)])
        res = dict(n_vias=len(vs), in_keepout=sum(1 for x in vs if area.intersects(Point(x["x"], x["y"]).buffer(x["size"] / 2))))
    L.emit(name, contract=prob, **L.summary(v), **res)

# 3. grids: values that once hung the run, and a grid just under the limit, timed
for name, st in [("pitch_tiny", 'pitch_mm = 0.0001'), ("rect_inf", 'pitch_mm = 1.5\nrect = [0, 0, inf, 40]'), ("rect_neg_inf", 'pitch_mm = 1.5\nrect = [-inf, 0, 60, 40]'),
                 ("pitch_nan", 'pitch_mm = nan'), ("rect_huge", 'pitch_mm = 1.0\nrect = [-1e6, -1e6, 1e6, 1e6]'),
                 ("grid_near_limit", 'pitch_mm = 0.95\nrect = [-450, -450, 499, 499]')]:
    d = L.build(os.path.join(work, name), BASE4, PLANES4.split("[[stitch]]")[0] + f'[[stitch]]\nnet = "GND"\n{st}\nsize_mm = 0.6\ndrill_mm = 0.3\nmargin_mm = 0.3\n')
    t0 = time.time()
    v, code_, prob, out = L.zone(d, timeout=240)
    L.emit(name, contract=prob, **L.summary(v), seconds=round(time.time() - t0, 1))

# 4. two overlapping entries for one net with different via sizes, and an entry for a second net over both
spec2 = {"layers": 2, "fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
                              {"ref": "P1", "at": (55, 35), "pads": [{"num": "1", "at": (55, 35), "net": "PWR"}]}]}
d = L.build(os.path.join(work, "two_sizes"), spec2, """[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3
priority = 1

[[zone]]
net = "PWR"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3

[[stitch]]
net = "GND"
pitch_mm = 1.5
size_mm = 0.6
drill_mm = 0.3
rect = [0, 0, 40, 40]

[[stitch]]
net = "GND"
pitch_mm = 2.1
size_mm = 1.0
drill_mm = 0.5
rect = [10, 0, 60, 40]
""")
v, code_, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    vs = L.shapes(v["data"]["written"])["vias"]
    worst = 99.0
    for i, a in enumerate(vs):
        for c in vs[i + 1:]:
            gap = ((a["x"] - c["x"]) ** 2 + (a["y"] - c["y"]) ** 2) ** 0.5 - (a["size"] + c["size"]) / 2
            worst = min(worst, gap)
    res = dict(n_vias=len(vs), sizes=sorted({x["size"] for x in vs}), worst_edge_gap=round(worst, 3))
L.emit("two_sizes", contract=prob, **L.summary(v), **res)

# 5. the pitch floor at its boundary: pitch equal to size plus margin is valid input
for name, p, s, dr, m in [("pitch_eq_0p9", 0.9, 0.6, 0.3, 0.3), ("pitch_eq_0p85", 0.85, 0.55, 0.3, 0.3), ("pitch_eq_1p2", 1.2, 0.8, 0.4, 0.4), ("pitch_eq_1p1", 1.1, 0.8, 0.4, 0.3),
                          ("pitch_below", 0.85, 0.6, 0.3, 0.3)]:
    d = L.build(os.path.join(work, name), BASE4, PLANES4.split("[[stitch]]")[0] + f'[[stitch]]\nnet = "GND"\npitch_mm = {p}\nsize_mm = {s}\ndrill_mm = {dr}\nmargin_mm = {m}\nrect = [10, 10, 20, 20]\n')
    v, code_, prob, out = L.zone(d)
    L.emit(name, contract=prob, **L.summary(v), sum=s + m)

# 6. stitch-no-fill: the net filled on F.Cu only (warned, B.Cu named), on both layers (no warning), and on both but
#    with the stitch rect where only one layer has fill
for name, layers in [("nofill_one", '["F.Cu"]'), ("nofill_none_missing", '["F.Cu", "B.Cu"]')]:
    d = L.build(os.path.join(work, name), spec2, f'[[zone]]\nnet = "GND"\nlayers = {layers}\nclearance_mm = 0.3\n\n[[stitch]]\nnet = "GND"\npitch_mm = 2.0\nsize_mm = 0.6\ndrill_mm = 0.3\n')
    v, code_, prob, out = L.zone(d)
    msgs = [w.get("message", "") for w in v.get("warnings", []) if w.get("code") == "stitch-no-fill"]
    L.emit(name, contract=prob, **L.summary(v), unfilled=(v.get("data") or {}).get("stitch_unfilled"), messages=msgs)
