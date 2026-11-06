"""Cases for pcb edit's footprint and outline operations (set_pad, silk_widen, silk_clear, silk_remove, add_slot,
add_hole) on a small board built here with pcbnew. Every result is read back with pcbnew, never pcb's own parser; the
input must never change, and every output passes the output contract.

Board (mm, KiCad frame): outline (0,0)-(60,40). U1 at (20,20), no turn: pad 1 SMD 1 x 1 at (20,20), pad 2 plated
1.6 mm round with a 0.8 mm drill at (25,20), both on net A; silkscreen 0.1 mm: a line (17,20)-(28,20) across both pads,
a line (17,17)-(28,17) clear of them, a 0.1 mm radius circle at (18,18). U2 at (40,20) turned 90 degrees: pad 1 SMD
1 x 0.6 at local (2,0), so at (40,18). U3 at (3,30): a silkscreen line (-1,30)-(8,30) running off the board's left edge.

Usage: python3 footprint_cases.py pcb-binary workdir
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = sys.argv[1:3]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
fails = []

BUILD = r'''
import sys, pcbnew
out = sys.argv[1]
b = pcbnew.BOARD()
MM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
for (x0, y0, x1, y1) in [(0, 0, 60, 0), (60, 0, 60, 40), (60, 40, 0, 40), (0, 40, 0, 0)]:
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetStart(V(x0, y0)); s.SetEnd(V(x1, y1))
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.05)); b.Add(s)
net = pcbnew.NETINFO_ITEM(b, "A"); b.Add(net)
def fp(ref, x, y, rot):
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.Reference().SetVisible(False); f.Value().SetVisible(False)
    b.Add(f); f.SetPosition(V(x, y)); f.SetOrientationDegrees(rot); return f
def pad(f, num, lx, ly, w, h, kind, shape, drill=0):
    p = pcbnew.PAD(f); p.SetNumber(num); p.SetAttribute(kind); p.SetShape(shape); p.SetSize(V(w, h))
    if drill: p.SetDrillSize(V(drill, drill))
    p.SetLayerSet(p.PTHMask() if kind == pcbnew.PAD_ATTRIB_PTH else p.SMDMask())
    f.Add(p); p.SetFPRelativePosition(V(lx, ly)); p.SetNet(net); return p
def line(f, x0, y0, x1, y1, w=0.1):
    s = pcbnew.PCB_SHAPE(f); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.F_SilkS); s.SetWidth(MM(w))
    f.Add(s); s.SetStart(V(x0, y0)); s.SetEnd(V(x1, y1))
u1 = fp("U1", 20, 20, 0)
pad(u1, "1", 0, 0, 1, 1, pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_SHAPE_RECT)
pad(u1, "2", 5, 0, 1.6, 1.6, pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_SHAPE_CIRCLE, 0.8)
line(u1, 17, 20, 28, 20)
line(u1, 17, 17, 28, 17)
c = pcbnew.PCB_SHAPE(u1); c.SetShape(pcbnew.SHAPE_T_CIRCLE); c.SetLayer(pcbnew.F_SilkS); c.SetWidth(MM(0.1)); c.SetFilled(False)
u1.Add(c); c.SetCenter(V(18, 18)); c.SetEnd(V(18.1, 18))
u2 = fp("U2", 40, 20, 90)
pad(u2, "1", 2, 0, 1, 0.6, pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_SHAPE_RECT)
u3 = fp("U3", 3, 30, 0)
line(u3, -1, 30, 8, 30)
b.Save(out)
'''
READ = r'''
import sys, json, pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
out = {"fp": {}, "edge": []}
for f in b.GetFootprints():
    d = {"pads": [], "silk": []}
    for p in f.Pads():
        d["pads"].append({"num": p.GetNumber(), "x": mm(p.GetPosition().x), "y": mm(p.GetPosition().y), "w": mm(p.GetSize().x),
                          "h": mm(p.GetSize().y), "drill": mm(p.GetDrillSize().x), "kind": int(p.GetAttribute())})
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_SilkS and isinstance(g, pcbnew.PCB_SHAPE):
            d["silk"].append({"shape": g.GetShapeStr(), "w": mm(g.GetWidth()), "filled": g.IsSolidFill(),
                              "s": [mm(g.GetStart().x), mm(g.GetStart().y)], "e": [mm(g.GetEnd().x), mm(g.GetEnd().y)]})
    out["fp"][f.GetReference()] = d
for g in b.GetDrawings():
    if g.GetLayer() == pcbnew.Edge_Cuts:
        out["edge"].append(g.GetShapeStr())
print(json.dumps(out))
'''
open(os.path.join(work, "build.py"), "w").write(BUILD)
open(os.path.join(work, "read.py"), "w").write(READ)
base = os.path.join(work, "base.kicad_pcb")
subprocess.run([sys.executable, os.path.join(work, "build.py"), base], check=True, capture_output=True)


def read(p):
    r = subprocess.run([sys.executable, os.path.join(work, "read.py"), p], capture_output=True, text=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run(name, ops, board=base):
    opsf = os.path.join(work, f"{name}.json")
    json.dump(ops, open(opsf, "w"))
    out = os.path.join(work, f"{name}.kicad_pcb")
    before = sha(board)
    o = subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "-o", out, "--work", os.path.join(work, f"{name}_w")], capture_output=True, text=True)
    v, problems = check(o.stdout, o.returncode)
    if problems:
        fails.append(f"{name}: output contract: {problems}")
    if sha(board) != before:
        fails.append(f"{name}: the input board changed")
    return v or {}, out


def want(name, ok, why):
    print(("PASS " if ok else "FAIL ") + f"{name}: {why}")
    if not ok:
        fails.append(f"{name}: {why}")


def outcome(v):
    return v.get("outcome"), (v.get("error") or {}).get("code")


def pad_of(r, ref, num):
    return next(p for p in r["fp"][ref]["pads"] if p["num"] == num)


# set_pad on a turned footprint: moved and resized, read back where asked
v, out = run("set_pad_turned", [dict(op="set_pad", ref="U2", pad="1", at=[40, 18], to=[40.5, 17.8], size=[1.2, 0.7])])
p = pad_of(read(out), "U2", "1") if outcome(v)[0] == "done" else {}
want("set_pad_turned", outcome(v)[0] == "done" and abs(p.get("x", 0) - 40.5) < 1e-3 and abs(p.get("y", 0) - 17.8) < 1e-3 and abs(p["w"] - 1.2) < 1e-3 and abs(p["h"] - 0.7) < 1e-3,
     f"U2.1 at ({p.get('x')}, {p.get('y')}), {p.get('w')} x {p.get('h')} ({outcome(v)})")
# set_pad drill on a plated pad
v, out = run("set_pad_drill", [dict(op="set_pad", ref="U1", pad="2", at=[25, 20], drill=0.9)])
p = pad_of(read(out), "U1", "2") if outcome(v)[0] == "done" else {}
want("set_pad_drill", outcome(v)[0] == "done" and abs(p.get("drill", 0) - 0.9) < 1e-3 and abs(p["w"] - 1.6) < 1e-3, f"U1.2 drill {p.get('drill')} ({outcome(v)})")
# refusals
for name, ops, code in [
    ("set_pad_wrong_at_refused", [dict(op="set_pad", ref="U1", pad="1", at=[21, 20], size=[1, 1])], "edit-no-target"),
    ("set_pad_nothing_refused", [dict(op="set_pad", ref="U1", pad="1", at=[20, 20])], "edit-op"),
    ("set_pad_drill_on_smd_refused", [dict(op="set_pad", ref="U1", pad="1", at=[20, 20], drill=0.5)], "edit-op"),
    ("set_pad_no_footprint_refused", [dict(op="set_pad", ref="U9", pad="1", at=[20, 20], size=[1, 1])], "edit-no-target"),
    ("add_hole_existing_ref_refused", [dict(op="add_hole", ref="U1", at=[50, 10], drill=3)], "edit-op"),
    ("add_slot_off_board_refused", [dict(op="add_slot", **{"from": [58, 10]}, to=[62, 10], width=1)], "edit-op"),
    ("silk_widen_unknown_ref_refused", [dict(op="silk_widen", min=0.15, refs=["U9"])], "edit-no-target"),
]:
    v, _ = run(name, ops)
    want(name, outcome(v) == ("refused", code), f"{outcome(v)}, want refused {code}")

# silk_clear: the line across both pads is cut back 0.15 mm plus half its width from their copper (U1.2 round, 0.8 mm
# radius), the clear line and the circle stay, and U3's line ends 0.15 mm plus half its width inside the edge
v, cleared = run("silk_clear", [dict(op="silk_clear", pads=0.15, edge=0.15)])
r = read(cleared) if outcome(v)[0] == "done" else {"fp": {"U1": {"silk": []}, "U3": {"silk": []}}}
segs = [s for s in r["fp"]["U1"]["silk"] if s["shape"] == "Line" and abs(s["s"][1] - 20) < 1e-6]
gap = 0.15 + 0.05


def seg_hits_rect(s, cx, cy, hx, hy):
    xs = sorted([s["s"][0], s["e"][0]])
    return xs[1] > cx - hx and xs[0] < cx + hx and abs(s["s"][1] - cy) < hy


bad = [s for s in segs if seg_hits_rect(s, 20, 20, 0.5 + gap - 1e-6, 0.5 + gap) or seg_hits_rect(s, 25, 20, 0.8 + gap - 1e-6, 0.8 + gap)]
clear_line = [s for s in r["fp"]["U1"]["silk"] if s["shape"] == "Line" and abs(s["s"][1] - 17) < 1e-6]
u3 = [s for s in r["fp"]["U3"]["silk"] if s["shape"] == "Line"]
want("silk_clear", outcome(v)[0] == "done" and segs and not bad and len(clear_line) == 1 and u3 and min(min(s["s"][0], s["e"][0]) for s in u3) >= 0.15 + 0.05 - 1e-6,
     f"pieces on y 20 {[(s['s'][0], s['e'][0]) for s in segs]}, clear line kept {len(clear_line)}, U3 from x {min((min(s['s'][0], s['e'][0]) for s in u3), default=None)} ({outcome(v)})")
want("silk_clear_pieces_kept", sorted(round(min(s["s"][0], s["e"][0]), 3) for s in segs) == [17.0, 20.7, 26.0] if segs else False,
     f"the line keeps (17, 19.3), (20.7, 24.0) and (26.0, 28): {[(round(s['s'][0], 3), round(s['e'][0], 3)) for s in segs]}")

# silk_widen on the cleared board: every silkscreen shape at 0.15 mm, the small circle filled
v, out = run("silk_widen", [dict(op="silk_widen", min=0.15)], board=cleared)
r = read(out) if outcome(v)[0] == "done" else {"fp": {}}
silk = [s for f in r["fp"].values() for s in f["silk"]]
circ = [s for s in silk if s["shape"] == "Circle"]
want("silk_widen", outcome(v)[0] == "done" and silk and all(s["w"] >= 0.15 - 1e-6 for s in silk) and circ and all(c["filled"] for c in circ),
     f"widths {sorted({s['w'] for s in silk})}, circle filled {[c['filled'] for c in circ]} ({outcome(v)})")

# silk_remove limited to U1: U1 has no silkscreen shapes, U3 keeps its line
v, out = run("silk_remove", [dict(op="silk_remove", refs=["U1"])])
r = read(out) if outcome(v)[0] == "done" else {"fp": {"U1": {"silk": [1]}, "U3": {"silk": []}}}
want("silk_remove", outcome(v)[0] == "done" and not r["fp"]["U1"]["silk"] and len(r["fp"]["U3"]["silk"]) == 1,
     f"U1 {len(r['fp']['U1']['silk'])} shapes, U3 {len(r['fp']['U3']['silk'])} ({outcome(v)})")

# add_slot and add_hole: two lines and two arcs on the outline; a non-plated hole footprint (pcbnew.PAD_ATTRIB_NPTH, 3) of the drill asked
v, out = run("add_slot_and_hole", [dict(op="add_slot", **{"from": [45, 10]}, to=[52, 10], width=1.2), dict(op="add_hole", ref="H1", at=[50, 32], drill=3.0)])
r = read(out) if outcome(v)[0] == "done" else {"edge": [], "fp": {}}
h = r["fp"].get("H1", {"pads": [{}]})["pads"][0]
want("add_slot_and_hole", outcome(v)[0] == "done" and sorted(r["edge"]).count("Arc") == 2 and sorted(r["edge"]).count("Line") == 6
     and abs(h.get("drill", 0) - 3.0) < 1e-6 and h.get("kind") == 3 and abs(h.get("x", 0) - 50) < 1e-6,
     f"edge {sorted(r['edge'])}, H1 {h} ({outcome(v)})")

print(json.dumps({"ok": not fails, "failed": fails}, indent=1))
sys.exit(1 if fails else 0)
