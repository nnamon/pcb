"""pcb import-tscircuit's silkscreen lines and rectangles (closure 36): on a part turned 90 degrees, on a part on
the bottom, and on the board, each stroke where the circuit JSON puts it (absolute, tscircuit's frame) with its
width and side; and a filled rectangle.

Usage: python3 import17.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r17lib as L  # noqa: E402
from circuit import C  # noqa: E402  (tests/lib: element builders only)

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

c = C()
sa, pa = c.comp("U9", 3, 2, 90, "top")
s1, p1 = c.port(sa, pa, "pin1", 1, 3, 1); c.pad(pa, p1, 3, 1, width=0.6, height=0.4)
s2, p2 = c.port(sa, pa, "pin2", 2, 3, 3); c.pad(pa, p2, 3, 3, width=0.6, height=0.4)
sb, pb = c.comp("U8", -6, 8, 0, "bottom")
s3, p3 = c.port(sb, pb, "pin1", 1, -7, 8); c.pad(pb, p3, -7, 8, layer="bottom", width=0.6, height=0.4)
s4, p4 = c.port(sb, pb, "pin2", 2, -5, 8); c.pad(pb, p4, -5, 8, layer="bottom", width=0.6, height=0.4)
for e in c.d:
    if e.get("type") == "pcb_port" and e["pcb_port_id"] in (p3, p4):
        e["layers"] = ["bottom"]
c.strace([s1], [c.net("N1")]); c.strace([s2], [c.net("N2")]); c.strace([s3], [c.net("N3")]); c.strace([s4], [c.net("N4")])

want = []  # (name, layer, (x1, y1, x2, y2) in tscircuit's frame, width)


def line(name, comp, layer, x1, y1, x2, y2, w):
    e = {"type": "pcb_silkscreen_line", "pcb_silkscreen_line_id": name, "layer": layer, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "stroke_width": w}
    if comp:
        e["pcb_component_id"] = comp
    c.add(e)
    want.append((name, layer, (x1, y1, x2, y2), w))


def rect(name, comp, layer, cx, cy, w, h, sw, filled=False):
    e = {"type": "pcb_silkscreen_rect", "pcb_silkscreen_rect_id": name, "layer": layer, "center": {"x": cx, "y": cy}, "width": w, "height": h, "stroke_width": sw, "is_filled": filled}
    if comp:
        e["pcb_component_id"] = comp
    c.add(e)
    p = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    for i in range(4):
        want.append((f"{name}.{i}", layer, p[i] + p[(i + 1) % 4], sw))


line("top_line", pa, "top", -5, -5, 5, -5, 0.2)
rect("top_rect", pa, "top", -8, 0, 3, 2, 0.254)
line("bot_line", pb, "bottom", -8, 9, -4, 9, 0.2)
rect("bot_rect", pb, "bottom", -6, 10.5, 2, 1, 0.18)
line("board_line", None, "top", 10, -10, 15, -10, 0.3)
rect("board_rect", None, "bottom", 12, 10, 4, 2, 0.2)
c.add({"type": "pcb_silkscreen_rect", "pcb_silkscreen_rect_id": "filled", "pcb_component_id": pa, "layer": "top", "center": {"x": -12, "y": -8}, "width": 1, "height": 1, "stroke_width": 0.1, "is_filled": True})

cj = os.path.join(work, "silk.json")
c.dump(cj)
out = os.path.join(work, "silk.kicad_pcb")
r = L.pcb("import-tscircuit", cj, "--layers", "2", "-o", out)
k = L.pyq(out, '''
segs = []
def take(g, where):
    if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and g.GetClass() == "PCB_SHAPE":
        segs.append(dict(where=where, layer="top" if g.GetLayer() == pcbnew.F_SilkS else "bottom", shape=g.GetShapeStr(), filled=g.IsSolidFill() if hasattr(g, "IsSolidFill") else str(g.GetFillMode()),
                         pts=[round(MM(g.GetStart().x), 3), round(MM(g.GetStart().y), 3), round(MM(g.GetEnd().x), 3), round(MM(g.GetEnd().y), 3)], w=round(MM(g.GetWidth()), 3)))
for f in b.GetFootprints():
    for g in f.GraphicalItems():
        take(g, f.GetReference())
for g in b.GetDrawings():
    take(g, "board")
bb = b.GetBoardEdgesBoundingBox()
print(json.dumps({"segs": segs, "c": [MM(bb.GetCenter().x), MM(bb.GetCenter().y)]}))
''') if r["outcome"] == "done" else {"segs": [], "c": [0, 0]}
cx, cy = k["c"]


def kicad(x, y):
    return (round(x + cx, 3), round(cy - y, 3))


miss = []
for name, layer, (x1, y1, x2, y2), w in want:
    a, b = kicad(x1, y1), kicad(x2, y2)
    ok = any(s["layer"] == layer and abs(s["w"] - w) < 1e-3 and (max(abs(u - v) for u, v in zip(a + b, s["pts"])) < 2e-3 or max(abs(u - v) for u, v in zip(b + a, s["pts"])) < 2e-3) for s in k["segs"])
    if not ok:
        miss.append([name, layer, list(a + b), w])
fa, fb = kicad(-12.5, -8.5), kicad(-11.5, -7.5)
filled = [s for s in k["segs"] if min(s["pts"][0], s["pts"][2]) >= min(fa[0], fb[0]) - 0.01 and max(s["pts"][0], s["pts"][2]) <= max(fa[0], fb[0]) + 0.01
          and min(s["pts"][1], s["pts"][3]) >= min(fa[1], fb[1]) - 0.01 and max(s["pts"][1], s["pts"][3]) <= max(fa[1], fb[1]) + 0.01]
L.emit("silk_line_rect", **L.slim(r), wanted=len(want), missing=miss, n_segs=len(k["segs"]),
       filled_rect=[(s["shape"], s["filled"], s["w"]) for s in filled])

# closure 38: a foreign-named trace whose ends land on A and whose middle crosses B's pad is imported (renamed to A);
# pcb check must stop it (KiCad's shorting_items)
c = C()
sa, pa = c.comp("R1", -5, 0, 0, "top")
s1, p1 = c.port(sa, pa, "pin1", 1, -5.5, 0); c.pad(pa, p1, -5.5, 0, width=0.6, height=0.6)
s2, p2 = c.port(sa, pa, "pin2", 2, -4.5, 0); c.pad(pa, p2, -4.5, 0, width=0.6, height=0.6)
sb, pb = c.comp("R2", 5, 0, 0, "top")
s3, p3 = c.port(sb, pb, "pin1", 1, 4.5, 0); c.pad(pb, p3, 4.5, 0, width=0.6, height=0.6)
s4, p4 = c.port(sb, pb, "pin2", 2, 5.5, 0); c.pad(pb, p4, 5.5, 0, width=0.6, height=0.6)
c.strace([s2, s1], [c.net("A")]); c.strace([s3], [c.net("B")]); c.strace([s4], [c.net("C")])
wire = lambda x, y: {"route_type": "wire", "x": x, "y": y, "width": 0.2, "layer": "top"}  # noqa: E731
c.add({"type": "pcb_trace", "pcb_trace_id": "t1", "net_name": "Net-(R1", "route": [wire(-4.5, 0), wire(4.5, 0), wire(4.5, 2), wire(-5.5, 2), wire(-5.5, 0)]})
pj = os.path.join(work, "through")
os.makedirs(pj)
c.dump(os.path.join(pj, "c.json"))
r = L.pcb("import-tscircuit", os.path.join(pj, "c.json"), "--layers", "2", "-o", os.path.join(pj, "board.kicad_pcb"))
open(os.path.join(pj, "pcb.toml"), "w").write('schema = 1\n\n[project]\nname = "t"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = 2\nfab = "jlcpcb-2layer-1.6mm"\n')
ck, un = L.check(pj, os.path.join(work, "through_c")) if r["outcome"] == "done" else ({"outcome": None}, [])
L.emit("rename_through_pad_checked", imported=L.slim(r), check=L.slim(ck), unwaived=un)
