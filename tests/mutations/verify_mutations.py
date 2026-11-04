"""Sensitivity test for pcb release's read-back (`gerber_helper.py verify`): each mutation damages a copy of a
released Gerber set in one way, and verify must report it; the unmutated set must be clean.

Mutations, placed from the board (never named here): a copper bridge between the closest pads of two nets on F.Cu
(short); a cut across a track of a two-pad net routed only on F.Cu (open); copper at the board edge (cu_edge); a
0.08 mm silkscreen line (silk_line); silkscreen over an exposed pad (silk_on_copper); a hole beside a hole of another
net (hole_hole).

Usage: python3 verify_mutations.py gerber_dir board.kicad_pcb workdir
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys

import pcbnew

gdir, board, work = sys.argv[1:4]
here = os.path.dirname(os.path.abspath(__file__))
helper = os.path.join(here, "..", "..", "src", "gerber_helper.py")
os.makedirs(work, exist_ok=True)
b = pcbnew.LoadBoard(board)
mm = pcbnew.ToMM


def gfile(d, suffix):
    return next(os.path.join(d, f) for f in os.listdir(d) if f.endswith(suffix))


def region(x0, y0, x1, y1, dark=True):
    u = lambda v: str(int(round(v * 1e6)))
    return [f"%LP{'D' if dark else 'C'}*%", "G36*", f"X{u(x0)}Y{u(y0)}D02*", f"X{u(x1)}Y{u(y0)}D01*", f"X{u(x1)}Y{u(y1)}D01*", f"X{u(x0)}Y{u(y1)}D01*", f"X{u(x0)}Y{u(y0)}D01*", "G37*", "%LPD*%"]


def append(path, lines):
    t = open(path).read()
    i = t.rstrip().rfind("M02*")
    open(path, "w").write(t[:i] + "\n".join(lines) + "\n" + t[i:])


def gxy(v):
    return mm(v.x), -mm(v.y)


# places, from the board
fpads = [(f.GetReference(), p) for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() and p.IsOnLayer(pcbnew.F_Cu) and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
best = None
for i, (ra, pa) in enumerate(fpads):
    for rb, pb in fpads[i + 1:]:
        if pa.GetNetname() != pb.GetNetname():
            d = math.dist(gxy(pa.GetPosition()), gxy(pb.GetPosition()))
            if best is None or d < best[0]:
                best = (d, pa, pb)
_, pa, pb = best
(ax, ay), (bx, by) = gxy(pa.GetPosition()), gxy(pb.GetPosition())
pads_of = {}
for f in b.GetFootprints():
    for p in f.Pads():
        pads_of.setdefault(p.GetNetname(), []).append(p)
cut = None
for t in b.GetTracks():
    n = t.GetNetname()
    if t.GetClass() != "PCB_TRACK" or len(pads_of.get(n, [])) != 2 or t.GetLength() < pcbnew.FromMM(1.0):
        continue
    if all(x.GetLayer() == pcbnew.F_Cu and x.GetClass() == "PCB_TRACK" for x in b.GetTracks() if x.GetNetname() == n) and all(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in pads_of[n]):
        cut = t
        break
mx, my = (mm(cut.GetStart().x) + mm(cut.GetEnd().x)) / 2, -(mm(cut.GetStart().y) + mm(cut.GetEnd().y)) / 2
xs = [mm(p.x) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts for p in (d.GetStart(), d.GetEnd())]
ys = [-mm(p.y) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts for p in (d.GetStart(), d.GetEnd())]
ex0, ey_mid = min(xs), (min(ys) + max(ys)) / 2
exposed = next(p for f in b.GetFootprints() for p in f.Pads() if p.IsOnLayer(pcbnew.F_Mask) and p.IsOnLayer(pcbnew.F_Cu) and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and min(p.GetSize().x, p.GetSize().y) >= pcbnew.FromMM(0.5))
px, py = gxy(exposed.GetPosition())
via = next(t for t in b.GetTracks() if t.GetClass() == "PCB_VIA")
vx, vy = gxy(via.GetPosition())

MUT = {
    "short": ("shorts", lambda d: append(gfile(d, "F_Cu.gbr"), region(min(ax, bx) - 0.1, min(ay, by) - 0.1, max(ax, bx) + 0.1, max(ay, by) + 0.1))),
    "open": ("opens", lambda d: append(gfile(d, "F_Cu.gbr"), region(mx - 0.3, my - 0.3, mx + 0.3, my + 0.3, dark=False))),
    "cu_edge": ("cu_edge", lambda d: append(gfile(d, "B_Cu.gbr"), region(ex0 + 0.05, ey_mid, ex0 + 1.0, ey_mid + 1.0))),
    "silk_line": ("silk_line", lambda d: append(gfile(d, "F_Silkscreen.gbr"), region(ex0 + 1.0, ey_mid + 3.0, ex0 + 3.0, ey_mid + 3.08))),
    "silk_on_copper": ("silk_on_copper", lambda d: append(gfile(d, "F_Silkscreen.gbr"), region(px - 0.2, py - 0.2, px + 0.2, py + 0.2))),
    "hole_hole": ("hole_hole", None),
}


def hole_next_to_via(d):
    # an NPTH 0.3 mm edge to edge from a via
    p = gfile(d, "NPTH.drl")
    t = open(p).read()
    r = via.GetDrillValue() / 1e6 / 2
    x = vx + r + 0.3 + 0.25
    tool = "T99C0.500"
    t = t.replace("%\n", f"{tool}\n%\n", 1)
    i = t.rstrip().rfind("M30")
    t = t[:i] + f"T99\nX{x:.3f}Y{vy:.3f}\n" + t[i:]
    open(p, "w").write(t)


MUT["hole_hole"] = ("hole_hole", hole_next_to_via)


def verify(d):
    r = subprocess.run([sys.executable, "-W", "ignore", helper, "verify", d, board], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


v0 = verify(gdir)
results = {"unmutated clean": not (v0["opens"] or v0["shorts"] or v0["unplaced_pads"] or v0["dfm"])}
for name, (want, fn) in MUT.items():
    d = os.path.join(work, name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(gdir, d)
    fn(d)
    v = verify(d)
    if want in ("shorts", "opens"):
        ok = bool(v[want])
        got = v[want][:2]
    else:
        hit = [f for f in v["dfm"] if f["rule"] == want]
        ok = bool(hit)
        got = hit[:1]
    results[f"{name} caught"] = ok
    print(f"{'ok  ' if ok else 'FAIL'} {name} caught: {got}")
print(f"{'ok  ' if results['unmutated clean'] else 'FAIL'} unmutated clean")
sys.exit(0 if all(results.values()) else 1)
