"""pcb paste and pcb art on the paddle-keyer board: a second run, dropping rules, windows on a turned pad, and text
and polygons as they plot (polygons with holes, counters, bottom-side mirroring, cap height), read back from
kicad-cli's Gerbers with gerbonara.

Usage: python3 pa15.py workdir
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402
sys.path.insert(0, os.path.join(L.TESTS, "lib"))
import kisexp  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


def drop_tables(d, head):
    """Remove every `head` table from pcb.toml."""
    p = os.path.join(d, "pcb.toml")
    out, skip = [], False
    for ln in open(p).read().splitlines():
        if ln.startswith("["):
            skip = ln.strip() == head
        if not skip:
            out.append(ln)
    open(p, "w").write("\n".join(out) + "\n")


def fp_text(board, ref):
    t = open(board).read()
    root = kisexp.parse(t)
    for f in root.find_all("footprint"):
        for p in f.find_all("property"):
            if p.arg(1) == "Reference" and p.arg(2) == ref:
                return t[f.span[0]:f.span[1]]
    return None


# --- paste: a second run, and dropping the rules
d = L.paddle(work, "paste")
b = os.path.join(d, "board.kicad_pcb")
before = open(b, "rb").read()
r = L.pcb("paste", "--project", d, "--work", W("pw1"))
L.emit("paste_again", **L.slim(r), same_bytes=open(b, "rb").read() == before)

fresh = W("fresh.kicad_pcb")
L.pcb("import-tscircuit", os.path.join(L.FX, "circuit.json"), "--layers", "2", "--allow-cross-net", "", "-o", fresh)
drop_tables(d, "[[paste]]")
r = L.pcb("paste", "--project", d, "--work", W("pw2"))
L.emit("paste_dropped", **L.slim(r), u1_as_imported=fp_text(b, "U1") == fp_text(fresh, "U1"), j1_as_imported=fp_text(b, "J1") == fp_text(fresh, "J1"))

# --- windows on a turned pad: U1 at 30 degrees, a 3 x 1 row of 0.9 mm windows on its 3.2 mm pad 57
d = L.paddle(work, "turned")
b = os.path.join(d, "board.kicad_pcb")
drop_tables(d, "[[paste]]")
L.pcb("paste", "--project", d, "--work", W("tw1"))
L.post(b, 'b.FindFootprintByReference("U1").SetOrientationDegrees(30)')
L.toml_add(d, '[[paste]]\npad = "U1.57"\nwindows = [3, 1]\nsize_mm = 0.9\nweb_mm = 0.15\n')
r = L.pcb("paste", "--project", d, "--work", W("tw2"))
inside = L.pyq(b, '''
f = b.FindFootprintByReference("U1")
ep = [p for p in f.Pads() if p.GetNumber() == "57"][0]
cu = ep.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE)
out = []
for p in f.Pads():
    if p.GetNumber() == "" and p.IsOnLayer(pcbnew.F_Paste):
        poly = p.GetEffectivePolygon(pcbnew.F_Paste, pcbnew.ERROR_INSIDE)
        o = poly.Outline(0)
        pts = [o.CPoint(i) for i in range(o.PointCount())]
        out.append(all(cu.Contains(q) for q in pts))
print(json.dumps(out))
''')
L.emit("windows_turned", **L.slim(r), windows_inside_pad=inside)

# --- art: polygons with holes, text, read back from the Gerbers
from shapely.geometry import Polygon, MultiPolygon, box, shape  # noqa: E402
from shapely.affinity import scale as sscale, translate  # noqa: E402

d = L.paddle(work, "art")
b = os.path.join(d, "board.kicad_pcb")
# a 6 x 4 mm plate with three staggered holes, and a C shape with a hole; an island inside a ring
plate = Polygon([(0, 0), (6, 0), (6, 4), (0, 4)], [[(1, 1), (2, 1), (2, 2), (1, 2)], [(1.5, 2.5), (3, 2.5), (3, 3.5), (1.5, 3.5)], [(4, 0.5), (5, 0.5), (5, 3.5), (4, 3.5)]])
cshape = Polygon([(0, 5), (6, 5), (6, 6), (1, 6), (1, 8), (6, 8), (6, 9), (0, 9)], [[(0.3, 5.3), (0.7, 5.3), (0.7, 8.7), (0.3, 8.7)]])
ring = Polygon([(8, 0), (14, 0), (14, 6), (8, 6)], [[(9, 1), (13, 1), (13, 5), (9, 5)]])
island = Polygon([(10, 2), (12, 2), (12, 4), (10, 4)])
want = MultiPolygon([plate, cshape, ring, island])
os.makedirs(os.path.join(d, "art"), exist_ok=True)
json.dump({"type": "MultiPolygon", "coordinates": [[list(map(list, p.exterior.coords))] + [list(map(list, h.coords)) for h in p.interiors] for p in want.geoms]}, open(os.path.join(d, "art", "holes.json"), "w"))
# placed on the back silkscreen in the board frame, over an area of the board well inside the outline
L.toml_add(d, '[[art]]\nname = "holes"\nfile = "art/holes.json"\nframe = "board"\nlayers = ["F.Mask"]\n')
L.toml_add(d, '[[text]]\nname = "probe_f"\ntext = "F8R"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 2.0\nat = [20, -10]\nframe = "centre"\nlayer = "F.Mask"\n')
L.toml_add(d, '[[text]]\nname = "probe_b"\ntext = "F8R"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 2.0\nat = [20, -10]\nframe = "centre"\nlayer = "B.Mask"\n')
L.toml_add(d, '[[text]]\nname = "probe_h"\ntext = "H"\nfont = "fonts/Inter-ExtraBold.ttf"\ncap_mm = 1.5\ngrow_mm = 0.05\nat = [20, 5]\nframe = "centre"\nrot_deg = 90\nlayer = "B.Mask"\n')
# art on F.Mask in the board frame sits at x 0..14, y 0..9 (off the board), and needs no zone to move
r = L.pcb("art", "--project", d, "--work", W("aw1"))
again_before = open(b, "rb").read()
r2 = L.pcb("art", "--project", d, "--work", W("aw2"))
same = open(b, "rb").read() == again_before
import glob  # noqa: E402
rej = sorted(glob.glob(os.path.join(d, "*rejected*.kicad_pcb")))
g = L.export(rej[0] if r["outcome"] == "rejected" and rej else b, W("art_g"))
cx, cy = L.pyq(b, 'bb = b.GetBoardEdgesBoundingBox(); print(json.dumps([mm(bb.GetCenter().x), mm(bb.GetCenter().y)]))')
fm = L.gshape(L.find(g, r"F_Mask"))
# the GeoJSON is y down in the board frame; Gerbers are y up
got = fm.intersection(box(-1, -10, 15, 1))
exp = sscale(want, 1, -1, origin=(0, 0))
holes_err = got.symmetric_difference(exp).area
# text on F.Cu and B.Cu around (cx, cy + 10) in Gerber frame (y up: -cy + -10 + ... ); compare B with F mirrored about x = cx
fc, bc = L.gshape(L.find(g, r"F_Mask")), L.gshape(L.find(g, r"B_Mask"))
win = box(cx + 16, -cy - 10 - 1.6, cx + 24, -cy - 10 + 1.6)
ft, bt = fc.intersection(win), bc.intersection(win)
mirror_err = sscale(ft, -1, 1, origin=(cx + 20, 0)).symmetric_difference(bt).area
ftb = ft.bounds
# "8" and "R" have counters: holes in the plotted text
n_holes = sum(len(p.interiors) for p in getattr(ft, "geoms", [ft]))
bm = L.gshape(L.find(g, r"B_Mask"))
h = bm.intersection(box(cx + 18, -cy + 5 - 2, cx + 22, -cy + 5 + 2))
hb = h.bounds if not h.is_empty else None
L.emit("art", first=L.slim(r), second=L.slim(r2), second_same_bytes=same, holes_sym_diff_mm2=round(holes_err, 4), holes_area=round(exp.area, 3),
       text_mirror_sym_diff_mm2=round(mirror_err, 4), text_area=round(ft.area, 3), text_centre=[round((ftb[0] + ftb[2]) / 2 - cx - 20, 3), round((ftb[1] + ftb[3]) / 2 + cy, 3)] if ft.bounds else None,
       counters=n_holes, h_rot90_size=[round(hb[2] - hb[0], 3), round(hb[3] - hb[1], 3)] if hb else None)

# dropping an entry removes its group and shapes
drop_tables(d, "[[art]]")
r3 = L.pcb("art", "--project", d, "--work", W("aw3"))
t = open(b).read()
L.emit("art_dropped", **L.slim(r3), photo_group_left='"pcb:art:photo"' in t, holes_group_left='"pcb:art:holes"' in t, text_group_left='"pcb:art:probe_f"' in t)
