"""Off-centre plated slots (review 19, closure 47) and slots in pads off a quarter turn (closure 51).

Synthetic EasyEDA parts through `pcb sync` and `pcb place`, then the drill and copper as pcbnew sees them, in the
footprint's own frame (the footprint turned back to 0 in pcbnew), against EasyEDA's hole points and pad outline.
Then `pcb parts` (the offset solver: JLCPCB's pads against the board's) and `pcb check` on the same boards. A slot
placed so near its pad's end that the copper ring there is thin, or broken, checks whether anything sees the offset.

Usage: python3 slot20.py workdir
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r20lib import U, board, check, eda, emit, fresh, pcb, pcbnew_run, project, slim, smd  # noqa: E402

work = sys.argv[1]
fresh(work)
OX, OY = 4000.0, 3000.0


def tht(num, x, y, w, h, rot, hole_r, slot, hp, shape="RECT"):
    """An EasyEDA plated pad, rot clockwise on screen (y down); field 10 its outline, turned."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts += [x + dx * c - dy * s, y + dx * s + dy * c]
    hps = " ".join(f"{v:.4f}" for v in hp) if hp else ""
    return f"PAD~{shape}~{x}~{y}~{w}~{h}~11~~{num}~{hole_r}~{' '.join(f'{v:.4f}' for v in pts)}~{rot}~g{num}~{slot}~{hps}~Y~0", pts


QUERY = '''
f = fp("U1")
o = f.GetPosition()
board_angle = f.GetOrientationDegrees()
def grab():
    out = {}
    for p in f.Pads():
        if p.GetNumber() != "1":
            continue
        sh = p.GetEffectiveHoleShape(); seg = sh.GetSeg()
        ol = p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE).Outline(0)
        out = {"a": [TM(seg.A.x - o.x), TM(seg.A.y - o.y)], "b": [TM(seg.B.x - o.x), TM(seg.B.y - o.y)], "w": TM(sh.GetWidth()),
               "at": [TM(p.GetPosition().x - o.x), TM(p.GetPosition().y - o.y)],
               "copper": [[TM(ol.CPoint(i).x - o.x), TM(ol.CPoint(i).y - o.y)] for i in range(ol.PointCount())]}
    return out
on_board = grab()
f.SetOrientationDegrees(0)
local = grab()
print(json.dumps({"board_angle": board_angle, "on_board": on_board, "local": local}))
'''


def kturn(x, y, deg):
    """KiCad's turn of a footprint-frame point onto the board (y down, positive anticlockwise on screen)."""
    a = math.radians(deg)
    return (x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a))


def measure(got, hp, outline, deg):
    from shapely.geometry import Polygon
    e = [((hp[0] - OX) * U, (hp[1] - OY) * U), ((hp[2] - OX) * U, (hp[3] - OY) * U)]
    want_cu = Polygon([((outline[i] - OX) * U, (outline[i + 1] - OY) * U) for i in range(0, 8, 2)])
    res = {}
    for frame, g, ends, cu in (("local", got["local"], e, want_cu),
                               ("board", got["on_board"], [kturn(*p, deg) for p in e], Polygon([kturn(*p, deg) for p in want_cu.exterior.coords]))):
        a, b = tuple(g["a"]), tuple(g["b"])
        res[f"{frame}_slot_end_error_mm"] = round(min(max(math.dist(a, ends[0]), math.dist(b, ends[1])), max(math.dist(a, ends[1]), math.dist(b, ends[0]))), 4)
        res[f"{frame}_copper_error_mm2"] = round(Polygon(g["copper"]).symmetric_difference(cu).area, 4)
    return res


FILL = [smd("2", 3960, 3000), smd("3", 3970, 3000)]
SYM = [("1", "1", "P"), ("2", "2", "Q"), ("3", "3", "R")]


def part(rec):
    return eda([rec] + FILL, SYM)


def case(name, pad, sdir, length, off, place_rot=0, side="top", hole_r=1.2, fpname=None):
    """pad (w, h, rot) in EasyEDA units; slot direction clockwise on screen; hole-point spacing; slot centre off the pad centre."""
    w, h, rot = pad
    x, y = OX + 20, OY + 20
    cx, cy = x + off[0], y + off[1]
    c, s = math.cos(math.radians(sdir)), math.sin(math.radians(sdir))
    hp = [cx - c * length / 2, cy - s * length / 2, cx + c * length / 2, cy + s * length / 2]
    rec, outline = tht("1", x, y, w, h, rot, hole_r, length + 2 * hole_r, hp)
    d = project(os.path.join(work, name), [("U1", "x", f"r20:{fpname}" if fpname else "", "C9200001"), ("R1", "r", "", "C11")],
                {"N1": [("U1", "1", ""), ("R1", "1", "")], "N2": [("U1", "2", ""), ("R1", "2", "")], "N3": [("U1", "3", "")]},
                {"C9200001": part(rec), "C11": eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])},
                place=[("U1", 0, 0, place_rot, side), ("R1", 9, 9, 0, "top")], footprints={fpname: FPS[fpname]} if fpname else None)
    if side == "bottom":
        # a hand-fitted part may go on the bottom
        t = open(os.path.join(d, "pcb.toml")).read().replace('machine_sides = ["top"]', 'machine_sides = ["top"]\nhand_fit = ["U1"]')
        open(os.path.join(d, "pcb.toml"), "w").write(t)
    s1 = pcb("sync", "--project", d, "--work", os.path.join(d, "ws"))
    res = {"sync": slim(s1)}
    if s1["outcome"] == "done":
        res["place"] = slim(pcb("place", "--project", d, "--work", os.path.join(d, "wp")))
        got = pcbnew_run(board(d), QUERY, save=False)
        res["board_angle"] = got["board_angle"]
        if side == "top":
            res.update(measure(got, hp, outline, got["board_angle"]))
        else:
            # mirrored: the footprint frame is flipped (y or x mirrored, whichever pcb used); the smaller miss of the two
            from shapely.geometry import Polygon
            g = got["local"]
            e = [((hp[0] - OX) * U, (hp[1] - OY) * U), ((hp[2] - OX) * U, (hp[3] - OY) * U)]
            wc = [((outline[i] - OX) * U, (outline[i + 1] - OY) * U) for i in range(0, 8, 2)]
            best = None
            for mx, my in ((1, -1), (-1, 1)):
                ends = [(mx * x, my * y) for x, y in e]
                a, b = tuple(g["a"]), tuple(g["b"])
                err = min(max(math.dist(a, ends[0]), math.dist(b, ends[1])), max(math.dist(a, ends[1]), math.dist(b, ends[0])))
                cu = Polygon(g["copper"]).symmetric_difference(Polygon([(mx * x, my * y) for x, y in wc])).area
                if best is None or err + cu < best[0] + best[1]:
                    best = (round(err, 4), round(cu, 4), (mx, my))
            res["local_slot_end_error_mm"], res["local_copper_error_mm2"], res["mirror"] = best
        pr = pcb("parts", "--project", d, "--work", os.path.join(d, "wpa"))
        res["parts"] = {"outcome": pr["outcome"], "findings": [f["item"] for f in pr["data"].get("findings", [])],
                        "solved": [s for s in pr["data"].get("solved", []) if s["reference"] == "U1"]}
        c = check(d, os.path.join(d, "wc"))
        res["check"] = {"outcome": c["outcome"], "unwaived": c["unwaived"], "msg": c["msg"]}
    emit(f"slot_{name}", **res)


# a project footprint drawn as KiCad draws an off-centre slot (pad at the hole, copper moved by the drill's offset),
# by hand from the same EasyEDA numbers as off_along_r0: hole at (5.588, 5.08), copper centre (5.08, 5.08)
HEAD = '(footprint "{n}" (version 20260206) (generator "r20") (layer "F.Cu")\n  (attr smd)\n' \
       '  (property "Reference" "REF**" (at 0 0 0) (layer "F.SilkS") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n' \
       '  (property "Value" "x" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n' \
       '  (fp_rect (start -11 -2) (end 8 2) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))\n'
SMD2 = '  (pad "2" smd rect (at -10.16 0) (size 1.016 1.524) (layers "F.Cu" "F.Paste" "F.Mask"))\n' \
       '  (pad "3" smd rect (at -7.62 0) (size 1.016 1.524) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
FPS = {"OFFK": HEAD.format(n="OFFK") + '  (pad "1" thru_hole rect (at 5.588 5.08) (size 3.556 1.524) (drill oval 1.3716 0.6096 (offset -0.508 0)) (layers "*.Cu" "*.Mask"))\n' + SMD2 + ")\n"}
case("project_fp_kicad_offset", (14, 6, 0), 0, 3, (2, 0), fpname="OFFK")

# off-centre slots: pad turns 0 to 270, slot along the pad, centre moved along it or across it, footprint turned on the board
case("off_along_r0", (14, 6, 0), 0, 3, (2, 0))
case("off_along_r90", (14, 6, 90), 90, 3, (0, 2))
case("off_along_r180", (14, 6, 180), 180, 3, (-2, 0))
case("off_along_r270", (14, 6, 270), 270, 3, (0, -2))
case("off_across_r0", (14, 8, 0), 0, 3, (1, 1))
case("off_r90_board90", (14, 6, 90), 90, 3, (0, 2), place_rot=90)
case("off_r0_board30", (14, 6, 0), 0, 3, (2, 0), place_rot=30)
case("off_r270_board180", (14, 6, 270), 270, 3, (0, -2), place_rot=180)
case("off_slot_across_pad", (10, 14, 0), 0, 2, (0, 3))
case("off_r0_bottom", (14, 6, 0), 0, 3, (2, 0), side="bottom")
# the slot's near end close to the copper's end: ring 0.1 mm there (pad 7 units half-length, slot 2.7, offset 3.906)
case("thin_ring", (14, 6, 0), 0, 3, (3.906, 0))
# the slot's end past the copper's end by 0.1 mm
case("broken_ring", (14, 6, 0), 0, 3, (4.694, 0))
# control: centred
case("centred_r0", (14, 6, 0), 0, 3, (0, 0))

# closure 51: a slot in a pad off a quarter turn, or drawn as a polygon, is refused
for name, shape, rot in (("rect_rot30", "RECT", 30), ("polygon_rot0", "POLYGON", 0)):
    x, y = OX + 20, OY + 20
    rec, _ = tht("1", x, y, 14, 6, rot, 1.2, 5.4, [x - 1.5 * math.cos(math.radians(rot)), y - 1.5 * math.sin(math.radians(rot)),
                                                   x + 1.5 * math.cos(math.radians(rot)), y + 1.5 * math.sin(math.radians(rot))], shape=shape)
    d = project(os.path.join(work, name), [("U1", "x", "", "C9200001")], {"N1": [("U1", "1", "")]}, {"C9200001": part(rec)})
    emit(f"slot_{name}", sync=slim(pcb("sync", "--project", d, "--work", os.path.join(d, "ws"))))

# a round hole in a pad turned 30 degrees: the custom pad's ring finding (review 19, 51's second half)
x, y = OX + 20, OY + 20
rec, _ = tht("1", x, y, 16, 10, 30, 1.2, 0, None)
d = project(os.path.join(work, "round_rot30"), [("U1", "x", "", "C9200001"), ("R1", "r", "", "C11")],
            {"N1": [("U1", "1", ""), ("R1", "1", "")]},
            {"C9200001": eda([rec], [("1", "1", "P")]), "C11": eda([smd("1", 4000, 3000), smd("2", 4010, 3000)], [("1", "1", "1"), ("2", "2", "2")])},
            place=[("U1", 0, 0, 0, "top"), ("R1", 9, 9, 0, "top")])
s1 = pcb("sync", "--project", d, "--work", os.path.join(d, "ws"))
pcb("place", "--project", d, "--work", os.path.join(d, "wp"))
c = check(d, os.path.join(d, "wc"))
emit("slot_round_rot30", sync=slim(s1), check={"outcome": c["outcome"], "unwaived": c["unwaived"]})
