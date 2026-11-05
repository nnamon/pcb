"""Diff probes beyond review 8's: changes pcb diff should see, and changes it must not report.
usage: diff_misses.py pcb work"""
import json
import os
import re
import subprocess
import sys

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(here, "lib"))
from contract_check import check  # noqa: E402

pcb, work = sys.argv[1], sys.argv[2]
os.makedirs(work, exist_ok=True)
base = os.path.join(work, "base.kicad_pcb")
subprocess.run([sys.executable, os.path.join(here, "lib", "synth_board.py"), "arc", base], check=True, capture_output=True)
src = open(base).read()


def w(name, text):
    p = os.path.join(work, name + ".kicad_pcb")
    open(p, "w").write(text)
    return p


def diff(a, b):
    r = subprocess.run([pcb, "--json", "diff", a, b], capture_output=True, text=True)
    d, pr = check(r.stdout, r.returncode)
    assert not pr, pr
    return d["data"]


def app(extra):
    t = src.rstrip()
    return t[:-1] + extra + ")\n"


def probe(name, a_text, b_text, want_identical):
    d = diff(w(name + "_a", a_text), w(name + "_b", b_text))
    ok = d["identical"] == want_identical
    print(f"{'PASS' if ok else 'FAIL'} {name}: identical={d['identical']} (want {want_identical}) copper={d['copper']} fps={[(f['ref'], f['change']) for f in d['footprints']]} zones+={d['zones_added']} zones-={d['zones_removed']} outline={d['outline_changed']}")


VIA = '\t(via (at 33 33) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net "N"))\n'
probe("via_layers_changed", app(VIA), app(VIA.replace('"F.Cu" "B.Cu"', '"F.Cu" "In1.Cu"')), False)
# arc lock
arc = re.search(r"\t\(arc\n.*?\n\t\)\n", src, re.S).group(0)
probe("arc_lock_changed", src, src.replace(arc, arc.replace("\t\t(layer", "\t\t(locked yes)\n\t\t(layer", 1)), False)
# zone with two outlines: the second changes
Z = '\t(zone (net "GND") (layer "B.Cu") (uuid "12345678-0000-4000-8000-000000000009") (polygon (pts (xy 1 1) (xy 5 1) (xy 5 5))) (polygon (pts (xy 10 10) (xy 15 10) (xy 15 15))))\n'
probe("zone_second_outline_changed", app(Z), app(Z.replace("(xy 15 15)", "(xy 15 19)")), False)
# zone clearance changed
Z2 = '\t(zone (net "GND") (layer "B.Cu") (uuid "12345678-0000-4000-8000-00000000000a") (connect_pads (clearance 0.3)) (polygon (pts (xy 1 1) (xy 5 1) (xy 5 5))))\n'
probe("zone_clearance_changed", app(Z2), app(Z2.replace("(clearance 0.3)", "(clearance 0.6)")), False)
# Edge.Cuts inside a footprint
fpedge = '\t(footprint "cut" (layer "F.Cu") (at 30 20) (property "Reference" "H9" (at 0 0 0) (layer "F.SilkS")) (fp_line (start -2 -2) (end 2 -2) (layer "Edge.Cuts") (stroke (width 0.1) (type solid))))\n'
probe("footprint_edge_cut_moved", app(fpedge), app(fpedge.replace("(end 2 -2)", "(end 3 -2)")), False)
# pad layer order only (KiCad's save reorders them): must be identical
fp1 = re.search(r'\(layers "F.Cu" "F.Mask" "F.Paste"\)', src)
if fp1:
    probe("pad_layer_order_only", src, src.replace('(layers "F.Cu" "F.Mask" "F.Paste")', '(layers "F.Cu" "F.Paste" "F.Mask")', 1), True)
else:
    print("SKIP pad_layer_order_only", re.findall(r"\(layers [^)]*\)", src)[:5])
# pad roundrect ratio changed
probe("pad_shape_rect_to_circle", src, src.replace("smd rect", "smd circle", 1), False)
# number formatting only: identical
probe("number_format_only", app(VIA), app(VIA.replace("(at 33 33)", "(at 33.000 33.0000)")), True)
# footprint value changed
probe("footprint_value_changed", src, src.replace('(property "Value" "R"', '(property "Value" "C"', 1), False)
