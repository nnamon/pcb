"""Review 9's zone cases for the write gate's fill carry-back, kept in the suite. A board with many kinds of zones
(zone_board.py: two on one net and layer, a two-layer zone, a zone that fills to nothing, a rule area, a footprint
holding a rule area and a copper zone) is edited, with and without zone uuids, three times each. Each result must be
the input plus the edit, byte for byte outside the fills; every zone's fill must equal pcbnew's own refill
(check_splice.py); the three runs must give the same bytes. A track across the footprint's own GND zone must not be
rejected on a stale footprint fill (review 9, 2).

Usage: python3 zone_gate_cases.py pcb-binary workdir
"""
import hashlib
import json
import os
import re
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(work, exist_ok=True)
ADD_N = [{"op": "add_track", "net": "N", "layer": "F.Cu", "width": 0.2, "points": [[20, 25], [50, 25]]}]
ADD_N34 = [{"op": "add_track", "net": "N", "layer": "B.Cu", "width": 0.2, "points": [[52, 28], [54, 31], [67, 31], [69, 28]]}]


def build(name, variant=None, strip_uuids=False):
    p = os.path.join(work, f"{name}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "zone_board.py"), p] + ([variant] if variant else []), check=True, capture_output=True)
    if strip_uuids:
        # zone uuids removed, as a hand-written or generated board may have them: then the save's order is all there is
        t = open(p).read()
        out, i = [], 0
        for m in re.finditer(r"\(zone\b", t):
            if m.start() < i:
                continue
            depth, j = 0, m.start()
            while True:
                c = t[j]
                if c == '"':
                    j = t.index('"', j + 1)
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(t[i:m.start()])
            out.append(re.sub(r"\n[ \t]*\(uuid \"[^\"]*\"\)", "", t[m.start():j + 1]))
            i = j + 1
        out.append(t[i:])
        open(p, "w").write("".join(out))
    return p


def edit(board, ops, tag):
    opsf = os.path.join(work, f"{tag}.ops.json")
    json.dump(ops, open(opsf, "w"))
    out = os.path.join(work, f"{tag}.out.kicad_pcb")
    r = subprocess.run([pcb, "--json", "edit", board, "--ops", opsf, "--work", os.path.join(work, tag + "_w"), "-o", out], capture_output=True, text=True)
    return json.loads(r.stdout), out


results = {}
for name, variant, strip, ops in [("uuids", None, False, ADD_N), ("no_uuids", None, True, ADD_N), ("footprint_zone", "n34", False, ADD_N34)]:
    b = build(name, variant, strip)
    shas, why = set(), None
    for k in range(3):
        d, out = edit(b, ops, f"{name}_{k}")
        if d.get("outcome") != "done":
            why = f"run {k + 1}: {d.get('outcome')} {d.get('error')} {d.get('data', {}).get('regressions')}"
            break
        shas.add(hashlib.sha256(open(out, "rb").read()).hexdigest())
        if k == 0:
            c = subprocess.run([sys.executable, os.path.join(here, "check_splice.py"), b, out], capture_output=True, text=True)
            j = json.loads(c.stdout[c.stdout.index("{"):])
            if not j["prefix_identical"] or j["fill_mismatch"]:
                why = f"not the input plus the edit outside the fills, or a fill not pcbnew's: {json.dumps(j)[:400]}"
                break
    if why is None and len(shas) != 1:
        why = f"three runs gave {len(shas)} different files"
    results[name] = why or "ok"
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
