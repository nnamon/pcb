"""Orientation sweep for `pcb import-tscircuit`, from the review 2 reviewer's t_orient check (review 5, 8).

A three-pad part (two rectangles of different sizes and a circle, off-centre so every turn and mirror shows) is placed
on each side at 0, 90, 180 and 270 degrees, with an off-centre courtyard. For each imported footprint:
  - its orientation is the tscircuit rotation, plus 180 on the back (KiCad's flip convention), and it is flipped only
    on the back;
  - every pad covers the same box and copper layer as the same library part placed by KiCad itself (pcbnew's own
    FOOTPRINT, Flip and SetOrientation), within 1 um;
  - its courtyard's corners cover the box of the tscircuit courtyard rectangle, within 1 um (after adding back the
    5 um KiCad 10 builds a courtyard inside its outline).

Usage: python3 orient_cases.py pcb-binary workdir
Prints one JSON summary; exit 1 on any mismatch.
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from circuit import C, rot_yup  # noqa: E402

import pcbnew  # noqa: E402

pcb, work = sys.argv[1:3]
os.makedirs(work, exist_ok=True)
W, H, CX, CY = 60, 40, 3, -2
MARGIN = 20.0
LIB = [("1", 1.0, 0.5, "rect", 0.4, 0.8), ("2", -0.8, 1.2, "rect", 0.6, 0.3), ("3", 0.2, -1.0, "circle", 0.5, 0.5)]


def K(x, y):
    return (x - CX + W / 2 + MARGIN, CY - y + H / 2 + MARGIN)


c = C(w=W, h=H, cx=CX, cy=CY)
meta = []
k = 0
for side in ("top", "bottom"):
    for rot in (0, 90, 180, 270):
        k += 1
        X, Y = -20 + k * 5, 5 if side == "top" else -8
        sc, pc = c.comp(f"U{k}", X, Y, rot, side)
        for num, lx, ly, sh, w, h in LIB:
            mx = -lx if side == "bottom" else lx
            dx, dy = rot_yup(mx, ly, rot)
            px, py = X + dx, Y + dy
            sp, pp = c.port(sc, pc, f"P{num}", int(num), px, py)
            if sh == "rect":
                ww, hh = (h, w) if rot in (90, 270) else (w, h)
                c.pad(pc, pp, px, py, "rect", side, width=ww, height=hh)
            else:
                c.pad(pc, pp, px, py, "circle", side, radius=w / 2)
        mx = -0.3 if side == "bottom" else 0.3
        dx, dy = rot_yup(mx, 0.2, rot)
        c.add({"type": "pcb_courtyard_rect", "pcb_component_id": pc, "center": {"x": X + dx, "y": Y + dy},
               "width": 4, "height": 2, "ccw_rotation": rot, "layer": side})
        meta.append((f"U{k}", side, rot, X, Y))
cj = os.path.join(work, "orient.json")
board = os.path.join(work, "orient.kicad_pcb")
c.dump(cj)
r = subprocess.run([pcb, "--json", "import-tscircuit", cj, "--layers", "2", "-o", board], capture_output=True, text=True)
if r.returncode != 0:
    print(json.dumps({"ok": False, "failed": {"import": r.stdout[-600:] + r.stderr[-300:]}}))
    sys.exit(1)

b = pcbnew.LoadBoard(board)
fps = {f.GetReference(): f for f in b.GetFootprints()}
bad = []
for ref, side, rot, X, Y in meta:
    fp = fps[ref]
    o = fp.GetOrientationDegrees() % 360
    exp = (rot + (180 if side == "bottom" else 0)) % 360
    if abs(o - exp) > 1e-6 or fp.IsFlipped() != (side == "bottom"):
        bad.append(f"{ref} {side} {rot}: orientation {o} flipped {fp.IsFlipped()}, want {exp} {side == 'bottom'}")
    # the same library part, placed by KiCad
    want = pcbnew.FOOTPRINT(b)
    for num, lx, ly, sh, w, h in LIB:
        p = pcbnew.PAD(want)
        p.SetNumber(num)
        p.SetShape(pcbnew.PAD_SHAPE_RECT if sh == "rect" else pcbnew.PAD_SHAPE_CIRCLE)
        p.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(w), pcbnew.FromMM(h)))
        p.SetLayerSet(p.SMDMask())
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        want.Add(p)
        p.SetFPRelativePosition(pcbnew.VECTOR2I(pcbnew.FromMM(lx), pcbnew.FromMM(-ly)))
    kx, ky = K(X, Y)
    pos = pcbnew.VECTOR2I(pcbnew.FromMM(kx), pcbnew.FromMM(ky))
    want.SetPosition(pos)
    if side == "bottom":
        want.Flip(pos, pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    want.SetOrientationDegrees(exp)
    got = {p.GetNumber(): p for p in fp.Pads()}
    for p in want.Pads():
        q = got.get(p.GetNumber())
        if q is None:
            bad.append(f"{ref} pad {p.GetNumber()} missing")
            continue
        a, g = p.GetBoundingBox(), q.GetBoundingBox()
        d = max(abs(a.GetLeft() - g.GetLeft()), abs(a.GetTop() - g.GetTop()), abs(a.GetRight() - g.GetRight()), abs(a.GetBottom() - g.GetBottom()))
        if d > 1000 or p.GetLayerSet().Seq()[0] != q.GetLayerSet().Seq()[0]:
            bad.append(f"{ref} {side} {rot} pad {p.GetNumber()}: {pcbnew.ToMM(d)} mm off, layer {q.GetLayerName()} want {p.GetLayerName()}")
    # the courtyard against the tscircuit rectangle
    mx = -0.3 if side == "bottom" else 0.3
    dx, dy = rot_yup(mx, 0.2, rot)
    cs = []
    for ex, ey in ((-2, -1), (2, -1), (2, 1), (-2, 1)):
        rx, ry = rot_yup(ex, ey, rot)
        cs.append(K(X + dx + rx, Y + dy + ry))
    fp.BuildCourtyardCaches()
    # the outline's own corners (BBox() also counts the outline's line width), grown back by KiCad 10's 5 um inset
    ol = fp.GetCourtyard(pcbnew.B_CrtYd if side == "bottom" else pcbnew.F_CrtYd).Outline(0)
    xs = [pcbnew.ToMM(ol.CPoint(i).x) for i in range(ol.PointCount())]
    ys = [pcbnew.ToMM(ol.CPoint(i).y) for i in range(ol.PointCount())]
    gotc = (min(xs) - 0.005, min(ys) - 0.005, max(xs) + 0.005, max(ys) + 0.005)
    wantc = (min(q[0] for q in cs), min(q[1] for q in cs), max(q[0] for q in cs), max(q[1] for q in cs))
    if max(abs(x - y) for x, y in zip(gotc, wantc)) > 0.001:
        bad.append(f"{ref} {side} {rot}: courtyard {gotc}, want {wantc}")
print(json.dumps({"ok": not bad, "footprints": len(meta), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
