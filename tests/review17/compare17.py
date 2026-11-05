"""compare-gerbers after review 16's closures 31 (slot direction) and 34 (unread files): J1's plated slots turned,
reversed and written in KiCad's other oval format (route), and sets holding files compare-gerbers does not read.
Set B is always pcb's own release of the paddle keyer; A is a copy with one change.

Usage: python3 compare17.py workdir
"""
import math
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r17lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


d = L.paddle(work, "base")
g, r = L.gate_release(d, work, "base")
B = L.unzip(os.path.join(r["written"], L.ZIP), W("B"))
PLOT = W("base_r", "plot.kicad_pcb")
PTH = os.path.basename(L.find(B, r"-PTH\.drl$"))


def variant(name, fn):
    a = W("A_" + name)
    shutil.copytree(B, a)
    fn(a)
    return a


def compare(a, b, name):
    x = L.pcb("compare-gerbers", a, b, "--work", W("cmp_" + name))
    dr = x["data"].get("drill", {})
    return dict(outcome=x["outcome"], code=x["code"], msg=(x["msg"] or str(x["data"].get("error") or ""))[:300], matched=dr.get("matched"),
                holes=[dr.get("a"), dr.get("b")], drill_differ=len(dr.get("differ") or []),
                differing={k: len(v.get("unexplained", [])) for k, v in x["data"].get("layers", {}).items() if v.get("unexplained")})


SLOT = "X-4.325Y28.635G85X-4.325Y28.235"  # J1's first slot: centre (-4.325, 28.435), 0.4 mm between end centres
assert SLOT in open(os.path.join(B, PTH)).read()


def turn(deg):
    a = math.radians(deg)
    dx, dy = 0.2 * math.sin(a), 0.2 * math.cos(a)
    return f"X{-4.325 - dx:.3f}Y{28.435 + dy:.3f}G85X{-4.325 + dx:.3f}Y{28.435 - dy:.3f}"


def sub(old, new):
    def fn(a):
        p = os.path.join(a, PTH)
        t = open(p).read()
        assert old in t
        open(p, "w").write(t.replace(old, new, 1))
    return fn


# closure 31: direction
for name, new in (("turned_90", turn(90)), ("turned_10", turn(10)), ("turned_3", turn(3)), ("reversed", "X-4.325Y28.235G85X-4.325Y28.635")):
    L.emit("slot_" + name, line=new, **compare(variant(name, sub(SLOT, new)), B, name))

# the same board's drill files in KiCad's route oval format (G00 / M15 / G01 / M16 / G05), from release's own plot
# copy, so the frame is the release's
R = W("route_export")
os.makedirs(R)
subprocess.run(["kicad-cli", "pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "--excellon-oval-format", "route", "--drill-origin", "plot", "-o", R + "/", PLOT], check=True, capture_output=True)
route_pth = open(L.find(R, r"-PTH\.drl$")).read()
n_routed = len(re.findall(r"^M15$", route_pth, re.M))


def to_route(text_fn=None):
    def fn(a):
        t = route_pth if text_fn is None else text_fn(route_pth)
        open(os.path.join(a, PTH), "w").write(t)
    return fn


B_route = variant("route", to_route())
# one routed slot turned 90 degrees; and one routed slot deleted
turned = variant("route_turned", to_route(lambda t: t.replace("G00X-4.325Y28.635\nM15\nG01X-4.325Y28.235", "G00X-4.525Y28.435\nM15\nG01X-4.125Y28.435", 1)))
gone = variant("route_gone", to_route(lambda t: t.replace("G00X-4.325Y28.635\nM15\nG01X-4.325Y28.235\nM16\nG05\n", "", 1)))
L.emit("route_vs_alternate", routed_slots_in_file=n_routed, **compare(B_route, B, "route_vs_alt"))
L.emit("route_slot_turned", **compare(turned, B_route, "route_turned"))
L.emit("route_slot_deleted", **compare(gone, B_route, "route_gone"))


# closure 34: files the comparison does not read
def add_file(name, src_pat, strip_x2=False, extra=None):
    def fn(a):
        t = open(L.find(a, src_pat)).read()
        if strip_x2:
            t = "\n".join(ln for ln in t.splitlines() if not ln.startswith(("%TF", "%TA", "%TO", "%TD", "G04 #@!")))
        if extra:
            t = extra(t)
        open(os.path.join(a, name), "w").write(t)
    return fn


cases = {
    "second_fcu": add_file("plot-F_Cu_copy.gbr", r"B_Cu\.gbr$", extra=lambda t: t.replace("Copper,L2,Bot", "Copper,L1,Top")),
    "comment_layer": add_file("plot-Notes.gbr", r"F_Silkscreen\.gbr$", extra=lambda t: t.replace("Legend,Top", "Other,Comment")),
    "inner_g1_no_x2": add_file("board.g1", r"B_Cu\.gbr$", strip_x2=True),
    "unnamed_gbr_no_x2": add_file("notes.gbr", r"B_Cu\.gbr$", strip_x2=True),
    "drill_as_txt": add_file("plot-PTH-extra.txt", r"-PTH\.drl$", extra=lambda t: t.replace("X-4.325Y28.635G85X-4.325Y28.235", "X0Y0\nX-4.325Y28.635G85X-4.325Y28.235")),
    "third_drl": add_file("plot-PTH-extra.drl", r"NPTH\.drl$", extra=lambda t: re.sub(r"(T1\n)", r"\1X0Y0\n", t, count=1)),
}
for name, fn in cases.items():
    L.emit("unread_" + name, **compare(variant(name, fn), B, name))
