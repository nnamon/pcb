"""pcb compare-gerbers on the paddle-keyer set pcb's flow makes (A) against itself and the ordered set: zip against
folder, a set whose layers are named only by X2 and one with neither X2 nor known names, a slot made longer, and an
explain entry for holes with no rect.

Usage: python3 compare15.py workdir
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
d = L.paddle(work, "base")
board = os.path.join(d, "board.kicad_pcb")
A = L.export(board, os.path.join(work, "A"))


def W(*p):
    return os.path.join(work, *p)


def cmp(name, a, b, explain=None, brd=board):
    r = L.compare(a, b, W("cw_" + name), explain=explain, board=brd if explain else None)
    L.emit(name, **L.slim(r), unexplained=r["unexplained"], missing=r["missing"], drill=(r["data"].get("drill") or {}).get("matched"), layers=sorted(r["data"].get("layers", {})))


def variant(name, fn):
    v = W(name)
    shutil.copytree(A, v)
    for f in sorted(os.listdir(v)):
        fn(v, f)
    return v


# the same set as a zip and as a folder
import zipfile  # noqa: E402
z = W("A.zip")
with zipfile.ZipFile(z, "w") as zz:
    for f in sorted(os.listdir(A)):
        zz.write(os.path.join(A, f), f)
cmp("zip_vs_folder", z, A)


# layers named only by X2: file names that match no pattern
def rename(v, f):
    if f.endswith(".gbr") and "Edge" not in f:
        os.rename(os.path.join(v, f), os.path.join(v, "x2only_" + str(abs(hash(f)) % 1000) + ".gbr"))


cmp("x2_names_only", variant("x2only", rename), A)


# neither X2 nor known names: every layer but the outline unknown; the comparison has nothing left to compare
def strip(v, f):
    p = os.path.join(v, f)
    if f.endswith(".gbr") and "Edge" not in f:
        t = open(p).read()
        t = "\n".join(ln for ln in t.splitlines() if not ln.startswith(("%TF", "%TA", "%TO", "%TD", "G04 #@!")))
        open(p, "w").write(t)
        os.rename(p, os.path.join(v, "layer_" + str(abs(hash(f)) % 1000) + ".gbr"))


cmp("unknown_layers", variant("unknown", strip), A)


# one slot 0.2 mm longer
def slot(v, f):
    p = os.path.join(v, f)
    if f.endswith("PTH.drl") and "NPTH" not in f:
        t = open(p).read()
        m = re.search(r"G85X(-?[\d.]+)Y(-?[\d.]+)", t)
        if m:
            t = t[:m.start()] + f"G85X{m.group(1)}Y{float(m.group(2)) - 0.2:.4f}" + t[m.end():]
        open(p, "w").write(t)


cmp("slot_longer", variant("slot", slot), A)

# an explain entry for holes without rect or whole
e = W("explain_drill.toml")
open(e, "w").write('[[explain]]\nlayer = "drill"\nside = "both"\nthinner_than_mm = 1.0\nwhy = "x"\n')
cmp("drill_explain_norect", variant("slot2", slot), A, explain=e)
