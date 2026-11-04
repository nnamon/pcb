"""Review 10 diff probes: changes that alter copper or the outline which pcb diff should see, and text forms pcbnew's
re-save changes which it must not report.
usage: python3 diff_probes.py WORKDIR"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew  # noqa: E402
from lib import PCB, B, blocks  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)

g = B()
g.fp("G1", 10, 10, "GND", tht=True)
g.fp("S1", 5, 45, "S")
g.fp("S2", 30, 45, "S")
g.trk(5, 45, 30, 45, "S")
g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
f = g.fp("FZ1", 60, 28, "GND", tht=True)
g.zone("GND", [pcbnew.B_Cu], (56, 24, 66, 32), parent=f)
base = g.save(os.path.join(work, "base.kicad_pcb"))
src = open(base).read()


def w(name, text):
    p = os.path.join(work, name + ".kicad_pcb")
    open(p, "w").write(text)
    return p


def resave(p):
    q = p.replace(".kicad_pcb", ".resaved.kicad_pcb")
    subprocess.run([sys.executable, "-c", f"import pcbnew; b=pcbnew.LoadBoard({p!r}); pcbnew.SaveBoard({q!r}, b)"], check=True, capture_output=True)
    return q


def diff(a, b):
    r = subprocess.run([PCB, "--json", "diff", a, b], capture_output=True, text=True)
    d = json.loads(r.stdout)
    return d


def app(t, extra):
    t = t.rstrip()
    return t[:-1] + extra + "\n)\n"


def first_zone(t):
    s, e = blocks(t, "zone")
    return s, e


results = []


def probe(name, a_text, b_text, want_identical):
    d = diff(w(name + "_a", a_text), w(name + "_b", b_text))
    dd = d["data"]
    summary = {k: dd[k] for k in ("footprints", "copper", "zones_added", "zones_removed", "outline_changed") if dd.get(k)}
    ok = dd["identical"] == want_identical
    results.append((name, "PASS" if ok else "FAIL", want_identical, dd["identical"], summary))


def probe_resave(name, text):
    a = w(name + "_a", text)
    b = resave(a)
    d = diff(a, b)["data"]
    summary = {k: d[k] for k in ("footprints", "copper", "zones_added", "zones_removed", "outline_changed") if d.get(k)}
    results.append((name, "PASS" if d["identical"] else "FAIL", True, d["identical"], summary))


zs, ze = blocks(src, "zone")[-1]  # the top-level GND zone (footprint zones come first in the file)
ztext = src[zs:ze]
assert '(net "GND")' in ztext and "F.Cu" in ztext, ztext[:200]

# misses: copper changes
probe("zone_thermal_gap", src, src[:zs] + ztext.replace("(thermal_gap 0.5)", "(thermal_gap 1.5)") + src[ze:], False)
probe("zone_thermal_bridge", src, src[:zs] + ztext.replace("(thermal_bridge_width 0.5)", "(thermal_bridge_width 1.5)") + src[ze:], False)
probe("zone_connect_pads_none", src, src[:zs] + ztext.replace("(connect_pads\n", "(connect_pads no\n") + src[ze:], False)
probe("zone_island_mode", src, src[:zs] + ztext.replace("(island_removal_mode 0)", "(island_removal_mode 1)") + src[ze:], False)
probe("zone_hatched", src, src[:zs] + re.sub(r"\(fill\b", "(fill (mode hatch)", ztext, 1) + src[ze:], False)
COPPER_POLY = '\t(gr_poly\n\t\t(pts (xy 40 30) (xy 45 30) (xy 45 35) (xy 40 35))\n\t\t(stroke (width 0) (type solid))\n\t\t(fill yes)\n\t\t(layer "F.Cu")\n\t\t(net "GND")\n\t)'
probe("copper_gr_poly_added", src, app(src, COPPER_POLY), False)
probe("copper_gr_text_added", src, app(src, '\t(gr_text "X" (at 40 40 0) (layer "F.Cu") (effects (font (size 2 2) (thickness 0.3))))'), False)
# footprint zone outline changed relative to the footprint
fzs, fze = blocks(src, "zone")[0]
fz = src[fzs:fze]
assert "B.Cu" in fz
probe("fp_zone_outline", src, src[:fzs] + fz.replace("(xy 66 32)", "(xy 70 32)") + src[fze:], False)
# pad zone connection override, roundrect ratio
pads = blocks(src, "pad")
ps, pe = pads[0]
probe("pad_zone_connect", src, src[:ps] + src[ps:pe - 1] + " (zone_connect 0))" + src[pe:], False)
# Edge.Cuts circle radius (the outline is segments in this board; add a circle cut-out then change it)
withc = app(src, '\t(gr_circle (center 40 25) (end 42 25) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))')
probe("edge_circle_radius", withc, withc.replace("(end 42 25)", "(end 43 25)"), False)

# false positives: forms pcbnew rewrites
probe_resave("resave_base", src)
probe_resave("resave_via_layers_reversed", app(src, '\t(via (at 20 30) (size 0.6) (drill 0.3) (layers "B.Cu" "F.Cu") (net "GND"))'))
minimal_zone = '\t(zone (net "GND") (layer "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0.30)) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 2 22) (xy 20 22) (xy 20 33) (xy 2 33))))'
probe_resave("resave_minimal_zone", app(src, minimal_zone))
keepout_partial = '\t(zone (layers "F.Cu") (hatch edge 0.5) (keepout (tracks not_allowed)) (polygon (pts (xy 25 5) (xy 30 5) (xy 30 15) (xy 25 15))))'
probe_resave("resave_partial_keepout", app(src, keepout_partial))
probe_resave("resave_zone_layers_FB", app(src, '\t(zone (net "GND") (layers "F&B.Cu") (uuid "aaaaaaaa-0000-0000-0000-000000000001") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 2 22) (xy 20 22) (xy 20 33) (xy 2 33))))'))
probe_resave("resave_track_width_long", app(src, '\t(segment (start 5 40) (end 30 40) (width 0.20000001) (layer "F.Cu") (net "S"))'))

for r in results:
    print(json.dumps(r))
