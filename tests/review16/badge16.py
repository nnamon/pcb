"""The badge (4 layers) through pcb's flow: pcb check against the fixture's list (names and counts), then every
finding waived, gate, release, so the read-back on a real 4-layer board shows what it reports and how long it takes.
Slot-to-hole gaps are measured here from the released Excellon files as stadiums.

Usage: python3 badge16.py workdir
"""
import math
import os
import re
import shutil
import sys
import time
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r16lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
d = os.path.join(work, "badge")
os.makedirs(d)
r = L.pcb("import-tscircuit", os.path.join(L.FXB, "circuit.json"), "--layers", "4", "--allow-cross-net", "NFC_COIL", "-o", os.path.join(d, "board.kicad_pcb"))
assert r["outcome"] == "done", r
shutil.copy(os.path.join(L.FXB, "pcb.toml"), d)
z = L.pcb("zone", "--project", d, "--work", os.path.join(work, "zw"))
c = L.pcb("check", "--project", d, "--work", os.path.join(work, "cw"))
fx = tomllib.load(open(os.path.join(L.FXB, "fixture.toml"), "rb"))
listed = set(fx.get("check", {}).get("findings", []))
got = {f'{f["check"]} {f["item"]}': f["count"] for f in c["data"].get("findings", [])}
L.emit("badge_check", zone=L.slim(z), **L.slim(c), only_found=sorted(set(got) - listed), only_listed=sorted(listed - set(got)),
       counts={k: v for k, v in got.items() if k.startswith(("drc unconnected", "drc clearance", "drc hole_clearance", "drc courtyards", "drc silk", "silk", "ring"))})

for f in c["data"].get("findings", []):
    L.toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {f["count"]}\nwhy = "review 16 probe"\n')
g = L.gate(d, os.path.join(work, "gw"))
t0 = time.time()
rr = L.release(d, os.path.join(work, "out"), os.path.join(work, "rw")) if g["outcome"] == "done" else g
secs = round(time.time() - t0, 1)
v = rr["data"].get("verify") or {}
dfm = {}
for x in v.get("dfm", []):
    dfm.setdefault(f'{x["rule"]} {x["layer"]}', []).append(x["detail"][:70])

# slot-to-hole gaps from the released drill files, as stadiums
holes = []
if rr.get("written"):
    zd = L.unzip(os.path.join(rr["written"], "badge_r36a_v" + re.search(r'version = "([^"]+)"', open(os.path.join(d, "pcb.toml")).read()).group(1) + "_gerbers.zip"), os.path.join(work, "z"))
    from shapely.geometry import LineString, Point
    for p in sorted(os.listdir(zd)):
        if not p.endswith(".drl"):
            continue
        tools, cur = {}, None
        for ln in open(os.path.join(zd, p)).read().splitlines():
            m = re.match(r"T(\d+)C([\d.]+)", ln)
            if m:
                tools[m.group(1)] = float(m.group(2))
                continue
            m = re.match(r"T(\d+)$", ln)
            if m:
                cur = m.group(1)
                continue
            m = re.match(r"X([-\d.]+)Y([-\d.]+)(?:G85X([-\d.]+)Y([-\d.]+))?$", ln)
            if m and cur:
                a = (float(m.group(1)), float(m.group(2)))
                if m.group(3):
                    e = (float(m.group(3)), float(m.group(4)))
                    holes.append((LineString([a, e]).buffer(tools[cur] / 2, 32), True, p))
                else:
                    holes.append((Point(a).buffer(tools[cur] / 2, 32), False, p))
slot_gaps = []
for i, (hs, isslot, f) in enumerate(holes):
    if not isslot:
        continue
    for j, (h2, s2, f2) in enumerate(holes):
        if j != i and hs.distance(h2) < 1.0 and (not s2 or j > i):
            slot_gaps.append(round(hs.distance(h2), 3))
L.emit("badge_release", gate=L.slim(g), **L.slim(rr), seconds=secs, opens=v.get("opens"), shorts=v.get("shorts"), n_unplaced=len(v.get("unplaced_pads") or []),
       dfm={k: (len(x), x[:2]) for k, x in dfm.items()}, slots=sum(1 for h in holes if h[1]), slot_gaps_under_1mm=sorted(slot_gaps))
