"""Sensitivity test for pcb release's read-back (`gerber_helper.py verify`): each mutation damages a copy of a
released Gerber set in one way, and verify must report it; the unmutated set must be clean.

Mutations, placed from the board (never named here): a copper bridge between the closest pads of two nets on F.Cu
(short); a cut across a track of a two-pad net routed only on F.Cu (open); copper at the board edge (cu_edge); a
0.12 mm silkscreen line (silk_line); silkscreen over an exposed pad (silk_on_copper); a hole beside a hole of another
net (hole_hole); a track necked to 0.10 mm (trace); copper 0.10 mm from a pad (gap).

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


def poly(pts, dark=True):
    u = lambda v: str(int(round(v * 1e6)))
    out = [f"%LP{'D' if dark else 'C'}*%", "G36*", f"X{u(pts[0][0])}Y{u(pts[0][1])}D02*"]
    out += [f"X{u(x)}Y{u(y)}D01*" for x, y in pts[1:] + pts[:1]]
    return out + ["G37*", "%LPD*%"]


def append(path, lines):
    t = open(path).read()
    i = t.rstrip().rfind("M02*")
    open(path, "w").write(t[:i] + "\n".join(lines) + "\n" + t[i:])


# pcb release's frame: the outline's centre at the origin, y up
_ex = [mm(p.x) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts for p in (d.GetStart(), d.GetEnd())]
_ey = [mm(p.y) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts for p in (d.GetStart(), d.GetEnd())]
CX, CY = (min(_ex) + max(_ex)) / 2, (min(_ey) + max(_ey)) / 2


def gxy(v):
    return mm(v.x) - CX, CY - mm(v.y)


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
(sx, sy), (tx, ty) = gxy(cut.GetStart()), gxy(cut.GetEnd())
mx, my = (sx + tx) / 2, (sy + ty) / 2
xs = [x - CX for x in _ex]
ys = [CY - y for y in _ey]
ex0, ey_mid = min(xs), (min(ys) + max(ys)) / 2
exposed = next(p for f in b.GetFootprints() for p in f.Pads() if p.IsOnLayer(pcbnew.F_Mask) and p.IsOnLayer(pcbnew.F_Cu) and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and min(p.GetSize().x, p.GetSize().y) >= pcbnew.FromMM(0.5))
px, py = gxy(exposed.GetPosition())
pw = mm(max(exposed.GetSize().x, exposed.GetSize().y))
# the via the hole goes beside: its net must have no copper where the hole lands, or the read-back puts the hole in
# the via's own copper group and judges the pair by the same-net limit (0.254 mm), which a 0.3 mm gap passes. The
# first via in file order changed with each Freerouting run and was sometimes a GND via inside a pour (pcb 0.5.1).
zone_nets = {z.GetNetname() for z in b.Zones() if z.GetNetname()}


def seg_dist(p, a, c):
    (px_, py_), (ax_, ay_), (cx_, cy_) = p, a, c
    dx, dy = cx_ - ax_, cy_ - ay_
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px_ - ax_) * dx + (py_ - ay_) * dy) / L2))
    return math.hypot(px_ - (ax_ + t * dx), py_ - (ay_ + t * dy))


def hole_spot(v):
    """The new hole's centre, KiCad mm: 0.3 mm edge to edge from the via, on its +x side."""
    r = v.GetDrillValue() / 1e6 / 2
    return (mm(v.GetPosition().x) + r + 0.3 + 0.25, mm(v.GetPosition().y))


def spot_clear(v):
    n = v.GetNetname()
    if not n or n in zone_nets:
        return False
    q = hole_spot(v)
    for t in b.GetTracks():
        if t.GetNetname() != n:
            continue
        if t.GetClass() == "PCB_VIA":
            if t.GetPosition() != v.GetPosition() and math.dist(q, (mm(t.GetPosition().x), mm(t.GetPosition().y))) < mm(t.GetWidth(pcbnew.F_Cu)) / 2 + 0.5:
                return False
        elif seg_dist(q, (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))) < mm(t.GetWidth()) / 2 + 0.5:
            return False
    for p in pads_of.get(n, []):
        if math.dist(q, (mm(p.GetPosition().x), mm(p.GetPosition().y))) < mm(max(p.GetSize().x, p.GetSize().y)) / 2 + 0.5:
            return False
    return True


vias = sorted((t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"), key=lambda t: (t.GetNetname(), t.GetPosition().x, t.GetPosition().y))
via = next(t for t in vias if spot_clear(t))
vx, vy = gxy(via.GetPosition())

def neck():
    ux, uy = (tx - sx), (ty - sy)
    L = math.hypot(ux, uy)
    ux, uy = ux / L, uy / L
    nx, ny = -uy, ux
    w = mm(cut.GetWidth())
    out = []
    for side in (1, -1):
        a0, a1 = 0.05, w / 2 + 0.01
        pts = [(mx + side * nx * a0 - ux * 0.2, my + side * ny * a0 - uy * 0.2), (mx + side * nx * a1 - ux * 0.2, my + side * ny * a1 - uy * 0.2),
               (mx + side * nx * a1 + ux * 0.2, my + side * ny * a1 + uy * 0.2), (mx + side * nx * a0 + ux * 0.2, my + side * ny * a0 + uy * 0.2)]
        out += poly(pts, dark=False)
    return out


MUT = {
    "short": ("shorts", lambda d: append(gfile(d, "F_Cu.gbr"), region(min(ax, bx) - 0.1, min(ay, by) - 0.1, max(ax, bx) + 0.1, max(ay, by) + 0.1))),
    "open": ("opens", lambda d: append(gfile(d, "F_Cu.gbr"), region(mx - 0.3, my - 0.3, mx + 0.3, my + 0.3, dark=False))),
    "cu_edge": ("cu_edge", lambda d: append(gfile(d, "B_Cu.gbr"), region(ex0 + 0.05, ey_mid, ex0 + 1.0, ey_mid + 1.0))),
    # 0.12 mm: under the 0.15 mm floor, over the 0.09 mm an older rule held (review 15, 8)
    "silk_line": ("silk_line", lambda d: append(gfile(d, "F_Silkscreen.gbr"), region(ex0 + 1.0, ey_mid + 3.0, ex0 + 3.0, ey_mid + 3.12))),
    # a 0.10 mm strip from a pad: narrow copper joined to wide copper (review 15, 7)
    # a track necked to 0.10 mm: copper cleared from both sides of its middle (review 15, 7; on a board under a
    # pour, a strip added beside a pad would merge with the pour)
    "trace": ("trace", lambda d: append(gfile(d, "F_Cu.gbr"), neck())),
    # a square 0.10 mm from a pad's edge
    "gap": ("gap", lambda d: append(gfile(d, "F_Cu.gbr"), region(px + pw / 2 + 0.1, py - 0.2, px + pw / 2 + 0.5, py + 0.2))),
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
# the project's own dfm waivers (pcb.toml beside the board): what release accepts is the clean baseline
waived = {}
toml = os.path.join(os.path.dirname(os.path.abspath(board)), "pcb.toml")
if os.path.exists(toml):
    import tomllib
    for w in tomllib.load(open(toml, "rb")).get("waiver", []):
        if w.get("check") == "dfm":
            waived[w["item"]] = w.get("max", 1)
counts = {}
for f in v0["dfm"]:
    k = f"{f['rule']} {f['layer']}"
    counts[k] = counts.get(k, 0) + 1
base = {(f["rule"], f["layer"], tuple(f["at"])) for f in v0["dfm"]}
results = {"unmutated clean": not (v0["opens"] or v0["shorts"] or v0["unplaced_pads"]) and all(n <= waived.get(k, 0) for k, n in counts.items())}
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
        hit = [f for f in v["dfm"] if f["rule"] == want and (f["rule"], f["layer"], tuple(f["at"])) not in base]
        ok = bool(hit)
        got = hit[:1]
    results[f"{name} caught"] = ok
    print(f"{'ok  ' if ok else 'FAIL'} {name} caught: {got}")
print(f"{'ok  ' if results['unmutated clean'] else 'FAIL'} unmutated clean")
sys.exit(0 if all(results.values()) else 1)
