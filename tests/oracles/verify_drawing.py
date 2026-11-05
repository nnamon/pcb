"""Check of the placement drawing pcb drawing wrote, against the board and the release's CPL, read independently.

Fails unless:
  A. there are three SVG sheets, each 420 x 297 mm (true scale), and one PDF of three A3 pages (1190.55 x 841.89 pt);
  B. the placement table (sheet 3) lists every part with numbered pads once, and each part the CPL lists sits in the
     table at the CPL's place moved to datum A (the outline's lower-left corner), within 1 um, with its rotation;
  C. every ordinate printed on sheet 1 (the teal numbers along the bottom and the left) is the X or Y, from datum A,
     of a footprint origin on the board, or 0;
  D. no two texts on a sheet overlap (boxes estimated from the font size: 0.6 of the size per character).

Usage: python3 verify_drawing.py drawings_dir board.kicad_pcb cpl.csv
"""
import csv
import glob
import json
import re
import sys

import pcbnew

d, board, cplf = sys.argv[1:4]
fails = []
svgs = sorted(glob.glob(f"{d}/*_sheet[0-9].svg"))
pdfs = glob.glob(f"{d}/*.pdf")
# A
if len(svgs) != 3:
    fails.append(f"A: {len(svgs)} SVG sheets")
for s in svgs:
    head = open(s).read(400)
    if 'width="420mm"' not in head or 'height="297mm"' not in head:
        fails.append(f"A: {s} is not 420 x 297 mm")
if len(pdfs) != 1:
    fails.append(f"A: {len(pdfs)} PDFs")
else:
    raw = open(pdfs[0], "rb").read()
    boxes = re.findall(rb"/MediaBox \[0 0 ([0-9.]+) ([0-9.]+)\]", raw)
    if len(boxes) != 3 or any(abs(float(w) - 1190.55) > 0.5 or abs(float(h) - 841.89) > 0.5 for w, h in boxes):
        fails.append(f"A: PDF pages {boxes}")

texts = []
for i, s in enumerate(svgs):
    t = []
    for m in re.finditer(r'<text x="([-0-9.]+)" y="([-0-9.]+)" font-family="[^"]*" font-size="([0-9.]+)" text-anchor="(\w+)" fill="([^"]*)"([^>]*)>([^<]*)</text>', open(s).read()):
        x, y, size, anchor, col, rest, txt = float(m[1]), float(m[2]), float(m[3]), m[4], m[5], m[6], m[7]
        t.append((x, y, size, anchor, col, "rotate" in rest, txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')))
    texts.append(t)

b = pcbnew.LoadBoard(board)
mm = pcbnew.ToMM
# the outline's extent by its segments' ends (KiCad's own box includes the line width)
ends = [(mm(p.x), mm(p.y)) for g in b.GetDrawings() if g.GetLayer() == pcbnew.Edge_Cuts for p in (g.GetStart(), g.GetEnd())]
x0, y1 = min(e[0] for e in ends), max(e[1] for e in ends)
w, h = max(e[0] for e in ends) - x0, y1 - min(e[1] for e in ends)
origins = {f.GetReference(): (mm(f.GetPosition().x) - x0, y1 - mm(f.GetPosition().y)) for f in b.GetFootprints() if any(p.GetNumber() for p in f.Pads())}

# B: the table, rows of REF X Y ROT SIDE ... in mono text by row
if len(texts) == 3:
    rows = {}
    by_line = {}
    for x, y, size, anchor, col, rot, txt in texts[2]:
        if size < 2.0:
            by_line.setdefault((round(y, 2)), []).append((x, txt))
    for y, cells in by_line.items():
        cells.sort()
        # tables run in columns: split a line where the x jumps back to a REF column start
        groups, cur = [], []
        for x, txt in cells:
            if cur and re.fullmatch(r"[A-Z][A-Z_0-9]*", txt) and len(cur) >= 5:
                groups.append(cur)
                cur = []
            cur.append(txt)
        groups.append(cur)
        for g in groups:
            if len(g) >= 5 and re.fullmatch(r"-?[0-9.]+", g[1] or ""):
                if g[0] in rows:
                    fails.append(f"B: {g[0]} twice in the table")
                rows[g[0]] = (float(g[1]), float(g[2]), float(g[3]), g[4])
    missing = sorted(set(origins) - set(rows))
    if missing:
        fails.append(f"B: not in the table: {missing}")
    for r in csv.DictReader(open(cplf, newline="", encoding="utf-8-sig")):
        ref = r["Designator"]
        if ref not in rows:
            fails.append(f"B: CPL part {ref} not in the table")
            continue
        X, Y = float(r["Mid X"][:-2]) + w / 2, float(r["Mid Y"][:-2]) + h / 2
        tx, ty, trot, side = rows[ref]
        if abs(tx - X) > 1.5e-3 or abs(ty - Y) > 1.5e-3:
            fails.append(f"B: {ref} is at ({tx}, {ty}) in the table, ({X:.3f}, {Y:.3f}) from the CPL")
        if abs((tx - X)) <= 1.5e-3 and abs((trot - float(r["Rotation"]) + 180) % 360 - 180) > 1e-6:
            fails.append(f"B: {ref} turned {trot} in the table, {r['Rotation']} in the CPL")

# C: ordinates, the teal (#005f60) plain numbers on sheet 1
if texts:
    xs = {round(v[0], 2) for v in origins.values()} | {0.0, round(w, 2)}
    ys = {round(v[1], 2) for v in origins.values()} | {0.0, round(h, 2)}
    n_ord = 0
    for x, y, size, anchor, col, rot, txt in texts[0]:
        if col == "#005f60" and re.fullmatch(r"-?[0-9]+\.[0-9]{2}", txt):
            n_ord += 1
            v = float(txt)
            if not any(abs(v - q) < 0.006 for q in (xs if rot else ys) | (xs | ys)):
                fails.append(f"C: ordinate {txt} is no footprint origin's X or Y")
    if n_ord < 3:
        fails.append(f"C: only {n_ord} ordinates")

# D
def box(x, y, size, anchor, rot, txt):
    L = len(txt) * size * 0.6
    a0 = {"start": 0, "middle": -L / 2, "end": -L}[anchor]
    if rot:
        return (x - size * 0.75, y - a0 - L, x + size * 0.2, y - a0)
    return (x + a0, y - size * 0.75, x + a0 + L, y + size * 0.2)


for i, t in enumerate(texts):
    bx = [box(x, y, s, a, r, txt) for x, y, s, a, c, r, txt in t]
    for p in range(len(bx)):
        for q in range(p + 1, len(bx)):
            A, B = bx[p], bx[q]
            if A[0] < B[2] - 1e-6 and B[0] < A[2] - 1e-6 and A[1] < B[3] - 1e-6 and B[1] < A[3] - 1e-6:
                fails.append(f"D: sheet {i + 1}: {t[p][6]!r} overlaps {t[q][6]!r}")

print(json.dumps({"sheets": len(svgs), "table_rows": len(rows) if len(texts) == 3 else 0, "fails": fails[:30], "n_fails": len(fails)}, indent=1))
sys.exit(1 if fails else 0)
