"""Check of a board pcb sync and pcb place made, against the netlist and JLCPCB's own footprints, read independently.

Fails unless:
  A. the board has one footprint per netlist part, and no other footprint with numbered pads;
  B. every pad a netlist net of two or more pins names carries that net, and every other numbered pad has no net;
  C. a part with an LCSC code carries it (property LCSC);
  D. each part with an LCSC code has JLCPCB's footprint pads where JLCPCB's footprint, turned and moved as the
     footprint is, puts them: every EasyEDA pad (cached in parts/<LCSC>.easyeda.json) lands on a board pad of the same
     number within 1 um, the pad counts match, and on the back the footprint is mirrored;
  E. with a places file (pcb.toml's [[place]]), each part's origin and rotation are those places, in the outline's
     centred frame.

Usage: python3 verify_sync.py board.kicad_pcb netlist.net parts_dir [pcb.toml]
"""
import json
import math
import re
import sys
import tomllib

import pcbnew

board, netf, parts = sys.argv[1:4]
toml = sys.argv[4] if len(sys.argv) > 4 else None
fails = []
U = 0.254


def sx(text):
    """A small S-expression reader: nested lists of atoms."""
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack = [[]]
    for t in toks:
        if t == "(":
            stack.append([])
        elif t == ")":
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return stack[0][0]


def kids(n, head):
    return [c for c in n[1:] if isinstance(c, list) and c and c[0] == head]


def val(n, head):
    k = kids(n, head)
    return k[0][1] if k and len(k[0]) > 1 else ""


nl = sx(open(netf).read())
comps = {}
for c in kids(kids(nl, "components")[0], "comp"):
    fields = {}
    for fs in kids(c, "fields"):
        for f in kids(fs, "field"):
            fields[val(f, "name")] = f[2] if len(f) > 2 and isinstance(f[2], str) else ""
    comps[val(c, "ref")] = fields
nets = {}
for n in kids(kids(nl, "nets")[0], "net"):
    nodes = [(val(x, "ref"), val(x, "pin")) for x in kids(n, "node")]
    if len(nodes) >= 2:
        for r, p in nodes:
            nets[(r, p)] = val(n, "name")

b = pcbnew.LoadBoard(board)
mm = pcbnew.ToMM
fps = {f.GetReference(): f for f in b.GetFootprints()}
# A
for r in comps:
    if r not in fps:
        fails.append(f"A: {r} is not on the board")
for r, f in fps.items():
    if r not in comps and any(p.GetNumber() for p in f.Pads()):
        fails.append(f"A: {r} is on the board but not in the netlist")
# B, C
for r, f in fps.items():
    if r not in comps:
        continue
    for p in f.Pads():
        if not p.GetNumber():
            continue
        want = nets.get((r, p.GetNumber()), "")
        if p.GetNetname() != want:
            fails.append(f"B: {r}.{p.GetNumber()} is {p.GetNetname()!r}, the netlist says {want!r}")
    code = comps[r].get("LCSC", "")
    if code and f.GetFieldText("LCSC") != code:
        fails.append(f"C: {r} carries LCSC {f.GetFieldText('LCSC')!r}, the netlist says {code!r}")
# D
for r, f in fps.items():
    code = comps.get(r, {}).get("LCSC", "")
    if not code:
        continue
    j = json.load(open(f"{parts}/{code}.easyeda.json"))["result"]["packageDetail"]["dataStr"]
    ox, oy = float(j["head"]["x"]), float(j["head"]["y"])
    ep = [(s.split("~")[8], (float(s.split("~")[2]) - ox) * U, (float(s.split("~")[3]) - oy) * U) for s in j["shape"] if s.startswith("PAD~")]
    pos = f.GetPosition()
    a = math.radians(f.GetOrientationDegrees())
    flip = f.IsFlipped()
    bp = [(p.GetNumber(), mm(p.GetPosition().x), mm(p.GetPosition().y)) for p in f.Pads() if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH and p.IsOnCopperLayer()]
    if len(bp) != len(ep):
        fails.append(f"D: {r} has {len(bp)} pads, JLCPCB's {code} footprint {len(ep)}")
    for num, lx, ly in ep:
        if flip:
            ly = -ly
        # KiCad turns anticlockwise on screen (y down)
        x = mm(pos.x) + lx * math.cos(a) + ly * math.sin(a)
        y = mm(pos.y) - lx * math.sin(a) + ly * math.cos(a)
        if not any(n == num and abs(x - bx) < 1e-3 and abs(y - by) < 1e-3 for n, bx, by in bp):
            fails.append(f"D: {r} ({code}) pad {num} should be at ({x:.4f}, {y:.4f})")
# E
if toml:
    t = tomllib.load(open(toml, "rb"))
    bb = b.GetBoardEdgesBoundingBox()
    cx, cy = mm(bb.GetCenter().x), mm(bb.GetCenter().y)
    for pl in t.get("place", []):
        f = fps.get(pl["ref"])
        if f is None:
            fails.append(f"E: [[place]] {pl['ref']} is not on the board")
            continue
        x, y = mm(f.GetPosition().x) - cx, cy - mm(f.GetPosition().y)
        if abs(x - pl["at"][0]) > 1e-3 or abs(y - pl["at"][1]) > 1e-3:
            fails.append(f"E: {pl['ref']} is at ({x:.4f}, {y:.4f}), [[place]] says {pl['at']}")
        if abs(((f.GetOrientationDegrees() - pl.get("rot_deg", 0)) + 180) % 360 - 180) > 1e-3:
            fails.append(f"E: {pl['ref']} is turned {f.GetOrientationDegrees()}, [[place]] says {pl.get('rot_deg', 0)}")
        if f.IsFlipped() != (pl.get("side", "top") == "bottom"):
            fails.append(f"E: {pl['ref']} is on the wrong side")

print(json.dumps({"parts": len(comps), "pads_checked": sum(1 for _ in nets), "fails": fails[:40], "n_fails": len(fails)}, indent=1))
sys.exit(1 if fails else 0)
