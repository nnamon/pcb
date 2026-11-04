"""Check of a release folder's BOM, CPL and checksums against the files that were ordered (golden), by value.

Fails unless:
  A. the CPL has the same designators as the golden one, each at the same place (within 1 um), side and rotation
     (mod 360);
  B. the BOM gives each designator the same LCSC part as the golden one, and no designator twice;
  C. CHECKSUMS.txt lists every other file in the folder with its SHA-256, and nothing else;
  D. the folder holds exactly one Gerber zip, one BOM and one CPL, named <name>_v<version>_{gerbers.zip,BOM.csv,CPL.csv}.
The Gerbers themselves are compared by `pcb compare-gerbers`.

Usage: python3 verify_release.py release_dir golden_bom.csv golden_cpl.csv name version
"""
import csv
import hashlib
import json
import os
import sys

rel, gbom, gcpl, name, version = sys.argv[1:6]
fails = []


def cpl(path):
    out = {}
    for r in csv.DictReader(open(path, newline="", encoding="utf-8-sig")):
        d = r["Designator"].strip()
        if d in out:
            fails.append(f"A: {os.path.basename(path)} lists {d} twice")
        mm = lambda v: float(v.strip().removesuffix("mm"))
        out[d] = (mm(r["Mid X"]), mm(r["Mid Y"]), r["Layer"].strip().lower(), float(r["Rotation"]) % 360)
    return out


def bom(path):
    out = {}
    for r in csv.DictReader(open(path, newline="", encoding="utf-8-sig")):
        for d in r["Designator"].split(","):
            d = d.strip()
            if d in out:
                fails.append(f"B: {os.path.basename(path)} lists {d} twice")
            out[d] = r["LCSC Part #"].strip()
    return out


stem = f"{name}_v{version}"
want = {f"{stem}_gerbers.zip", f"{stem}_BOM.csv", f"{stem}_CPL.csv", "CHECKSUMS.txt"}
have = set(os.listdir(rel))
if have != want:
    fails.append(f"D: the folder holds {sorted(have)}, expected {sorted(want)}")
else:
    a, g = cpl(os.path.join(rel, f"{stem}_CPL.csv")), cpl(gcpl)
    if set(a) != set(g):
        fails.append(f"A: designators differ: only in the release {sorted(set(a) - set(g))}, only in the order {sorted(set(g) - set(a))}")
    for d in sorted(set(a) & set(g)):
        (x, y, s, r), (gx, gy, gs, gr) = a[d], g[d]
        if abs(x - gx) > 1e-3 or abs(y - gy) > 1e-3 or s != gs or min(abs(r - gr), 360 - abs(r - gr)) > 1e-3:
            fails.append(f"A: {d} at ({x}, {y}) {s} {r} in the release, ({gx}, {gy}) {gs} {gr} in the order")
    ab, gb = bom(os.path.join(rel, f"{stem}_BOM.csv")), bom(gbom)
    for d in sorted(set(ab) | set(gb)):
        if ab.get(d) != gb.get(d):
            fails.append(f"B: {d} is {ab.get(d)} in the release BOM, {gb.get(d)} in the order")
    listed = {}
    for line in open(os.path.join(rel, "CHECKSUMS.txt")):
        h, _, f = line.strip().partition("  ")
        listed[f] = h
    for f in sorted(want - {"CHECKSUMS.txt"}):
        h = hashlib.sha256(open(os.path.join(rel, f), "rb").read()).hexdigest()
        if listed.get(f) != h:
            fails.append(f"C: CHECKSUMS.txt gives {f} as {listed.get(f)}, the file is {h}")
    if set(listed) != want - {"CHECKSUMS.txt"}:
        fails.append(f"C: CHECKSUMS.txt lists {sorted(listed)}")
print(json.dumps({"ok": not fails, "fails": fails}, indent=1))
sys.exit(0 if not fails else 1)
