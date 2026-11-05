"""The badge (4 layers) through pcb check, against what DESIGN.md records, and through pcb release with every check
finding waived, so the read-back (connectivity and DFM on 4-layer Gerbers) shows what it reports on a real board.

Usage: python3 badge15.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
FXB = os.path.join(L.TESTS, "fixtures", "badge_r36a")
d = os.path.join(work, "badge")
os.makedirs(d)
r = L.pcb("import-tscircuit", os.path.join(FXB, "circuit.json"), "--layers", "4", "--allow-cross-net", "NFC_COIL", "-o", os.path.join(d, "board.kicad_pcb"))
assert r["outcome"] == "done", r
shutil.copy(os.path.join(FXB, "pcb.toml"), d)
z = L.pcb("zone", "--project", d, "--work", os.path.join(work, "zw"))
c = L.pcb("check", "--project", d, "--work", os.path.join(work, "cw"))
fs = c["data"].get("findings", [])
L.emit("badge_check", zone=L.slim(z), **L.slim(c), fab=c["data"].get("fab"), findings={f["item"]: f["count"] for f in fs})

# waive every finding, pass the gate, release: the read-back on its own
for f in fs:
    L.toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = {f["count"]}\nwhy = "probe: the badge design work after M4"\n')
g = L.pcb("gate", "pass", "layout", "--project", d, "--work", os.path.join(work, "gw"))
rr = L.pcb("release", "--project", d, "-o", os.path.join(work, "out"), "--work", os.path.join(work, "rw")) if g["outcome"] == "done" else g
v = rr["data"].get("verify", {})
dfm = {}
for x in v.get("dfm", []):
    dfm.setdefault(f'{x["rule"]} {x["layer"]}', []).append(x["detail"][:70])
L.emit("badge_release", gate=L.slim(g), **L.slim(rr), layers=v.get("layers"), opens=v.get("opens"), shorts=v.get("shorts"), unplaced=(v.get("unplaced_pads") or [])[:8],
       n_unplaced=len(v.get("unplaced_pads") or []), dfm={k: (len(x), x[:3]) for k, x in dfm.items()})
