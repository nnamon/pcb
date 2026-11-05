"""pcb compare-gerbers: explain entries that must be refused, and files in a set that the comparison does not read
(a second file claiming the top copper, a layer with an unlisted X2 function).

Usage: python3 compare16.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r16lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


d = L.paddle(work, "ctl")
g = L.gate(d, W("g"))
r = L.release(d, W("out"), W("r"))
A = L.unzip(os.path.join(r["written"], f"{L.STEM}_gerbers.zip"), W("A"))

# 21: explain entries with an unknown key, no why, a bad side, a drill entry with no place, a reversed rect,
# whole = false and nothing else
BAD = {
    "unknown_key": '[[explain]]\nlayer = "F.Cu"\nside = "a"\nrect = [0, 0, 1, 1]\nwhy = "x"\nlayr = "B.Cu"\n',
    "no_why": '[[explain]]\nlayer = "F.Cu"\nside = "a"\nrect = [0, 0, 1, 1]\n',
    "bad_side": '[[explain]]\nlayer = "F.Cu"\nside = "c"\nrect = [0, 0, 1, 1]\nwhy = "x"\n',
    "drill_no_place": '[[explain]]\nlayer = "drill"\nside = "both"\nthinner_than_mm = 1.0\nwhy = "x"\n',
    "rect_reversed": '[[explain]]\nlayer = "F.Cu"\nside = "a"\nrect = [1, 1, 0, 0]\nwhy = "x"\n',
    "whole_false": '[[explain]]\nlayer = "F.Cu"\nside = "a"\nwhole = false\nwhy = "x"\n',
}
res = {}
for k, text in BAD.items():
    e = W(k + ".toml")
    open(e, "w").write(text)
    c = L.pcb("compare-gerbers", A, A, "--explain", e, "--work", W("cw_" + k))
    res[k] = [c["outcome"], c["code"]]
L.emit("explain_refused", **res)

# a second file claiming F.Cu (a copy of B.Cu's copper with F.Cu's X2 function), beside the real one
v = W("dup")
shutil.copytree(A, v)
fcu, bcu = L.find(v, r"F_Cu"), L.find(v, r"B_Cu")
t = open(bcu).read().replace("Copper,L2,Bot", "Copper,L1,Top")
open(os.path.join(v, "zz-second-top.gbr"), "w").write(t)
c = L.pcb("compare-gerbers", v, A, "--work", W("cw_dup"))
L.emit("second_top_copper", **L.slim(c), files=len(os.listdir(v)))

# a layer with an X2 function the comparison does not list (a copy of F.Cu as "Other,Comment")
v = W("other")
shutil.copytree(A, v)
t = open(fcu).read()
import re  # noqa: E402
t = re.sub(r"%TF\.FileFunction,[^*]*\*%", "%TF.FileFunction,Other,Comment*%", t)
open(os.path.join(v, "plot-User_1.gbr"), "w").write(t)
c = L.pcb("compare-gerbers", v, A, "--work", W("cw_other"))
L.emit("unlisted_layer", **L.slim(c))
