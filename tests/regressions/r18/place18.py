"""`pcb place` on the back, against KiCad's own flip: parts placed on the bottom by pcb, compared pad by pad with
the same footprints flipped by pcbnew (FOOTPRINT.Flip, top-bottom) and turned to the same angle. And the CPL rows
the release writes for them from that board.

Usage: python3 place18.py workdir
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import copy_fixture, emit, fresh, pcb, pyq, slim, sub  # noqa: E402

work = sys.argv[1]
fresh(work)
d = copy_fixture(work, "bottom")
r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
synced = os.path.join(work, "synced.kicad_pcb")
shutil.copy(os.path.join(d, "board.kicad_pcb"), synced)
pt = os.path.join(d, "pcb.toml")
sub(pt, 'machine_sides = ["top"]', 'machine_sides = ["top", "bottom"]')
WANT = {"U3": 90, "J1": 180, "SW1": 90, "C2": 45, "Y1": 270}
t = open(pt).read()
for ref, rot in WANT.items():
    i = t.index(f'ref = "{ref}"\n')
    j = t.index("[[place]]", i) if "[[place]]" in t[i:] else len(t)
    blk = t[i:j]
    import re
    nb = re.sub(r"rot_deg = [-\d.]+", f"rot_deg = {rot}", blk).replace('side = "top"', 'side = "bottom"')
    t = t[:i] + nb + t[j:]
open(pt, "w").write(t)
rp = pcb("place", "--project", d, "--ref", ",".join(WANT), "--work", os.path.join(d, "w"))
placed = os.path.join(d, "board.kicad_pcb")
if rp["outcome"] != "done":
    rej = os.path.join(d, "board.rejected.kicad_pcb")
    placed = rej if os.path.exists(rej) else placed

READ = r'''
refs = json.loads(sys.argv[2])
out = {}
for f in b.GetFootprints():
    if f.GetReference() not in refs:
        continue
    pads = sorted([[p.GetNumber(), round(mm(p.GetPosition().x), 4), round(mm(p.GetPosition().y), 4), round(p.GetOrientationDegrees() % 360, 3) % 360,
                    sorted(str(b.GetLayerName(l)) for l in p.GetLayerSet().Seq()), [round(mm(p.GetDrillSizeX()), 4), round(mm(p.GetDrillSizeY()), 4)]] for p in f.Pads()])
    gfx = sorted([[str(b.GetLayerName(g.GetLayer())), round(mm(g.GetStart().x), 3), round(mm(g.GetStart().y), 3), round(mm(g.GetEnd().x), 3), round(mm(g.GetEnd().y), 3)] for g in f.GraphicalItems() if g.GetClass() == "PCB_SHAPE" and g.GetShape() == pcbnew.SHAPE_T_SEGMENT])
    out[f.GetReference()] = {"pos": [round(mm(f.GetPosition().x), 4), round(mm(f.GetPosition().y), 4)], "rot": f.GetOrientationDegrees(), "flipped": f.IsFlipped(), "pads": pads, "gfx": gfx,
                             "ref_mirrored": f.Reference().IsMirrored()}
print(json.dumps(out))
'''
got = pyq(placed, READ, json.dumps(list(WANT)))
# the same footprints flipped and turned by pcbnew
FLIP = r'''
refs = json.loads(sys.argv[2]); pos = json.loads(sys.argv[3])
for f in b.GetFootprints():
    r = f.GetReference()
    if r in refs:
        f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(pos[r][0]), pcbnew.FromMM(pos[r][1])))
        f.SetOrientationDegrees(0)
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        f.SetOrientationDegrees(refs[r])
pcbnew.SaveBoard(sys.argv[1], b)
print("{}")
'''
ref_board = os.path.join(work, "kicad_flipped.kicad_pcb")
shutil.copy(synced, ref_board)
pyq(ref_board, FLIP, json.dumps(WANT), json.dumps({k: v["pos"] for k, v in got.items()}))
want = pyq(ref_board, READ, json.dumps(list(WANT)))
diffs = {}
for ref in WANT:
    g, w = got.get(ref), want.get(ref)
    if not g or not w:
        diffs[ref] = "missing"
        continue
    dd = []
    if g["flipped"] != w["flipped"] or abs(((g["rot"] - w["rot"]) + 180) % 360 - 180) > 1e-3:
        dd.append(f"footprint rot/flip {g['rot']}/{g['flipped']} vs KiCad {w['rot']}/{w['flipped']}")
    for a, c in zip(g["pads"], w["pads"]):
        if a[0] != c[0] or abs(a[1] - c[1]) > 1e-3 or abs(a[2] - c[2]) > 1e-3 or a[4] != c[4] or a[5] != c[5]:
            dd.append(f"pad {a} vs KiCad {c}")
        elif min(abs(a[3] - c[3]) % 180, 180 - abs(a[3] - c[3]) % 180) > 1e-2:
            dd.append(f"pad {a[0]} angle {a[3]} vs KiCad {c[3]}")
    gs = {tuple(x) for x in g["gfx"]}
    ws = {tuple(x) for x in w["gfx"]}
    if gs != ws:
        # a line is the same line either way round
        norm = lambda s: {(x[0],) + tuple(sorted([(x[1], x[2]), (x[3], x[4])])) for x in s}
        if norm(gs) != norm(ws):
            dd.append(f"graphics differ: {len(norm(gs) - norm(ws))} of {len(gs)}")
    if g["ref_mirrored"] != w["ref_mirrored"]:
        dd.append(f"reference text mirrored {g['ref_mirrored']}, KiCad {w['ref_mirrored']}")
    diffs[ref] = dd
emit("bottom_vs_kicad_flip", place=slim(rp), board=os.path.basename(placed), diffs=diffs)
