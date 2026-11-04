"""Review 11 diff probes. usage: PCB_BIN=... python3 diff11.py WORKDIR
Misses: a change that alters copper but diff calls identical. False positives: a pcbnew re-save that diff calls
changed."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review10"))
import pcbnew  # noqa: E402
from lib import B, PCB  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)


def diff(a, b):
    r = subprocess.run([PCB, "--json", "diff", a, b], capture_output=True, text=True)
    d = json.loads(r.stdout)
    data = d.get("data") or {}
    keep = {k: v for k, v in data.items() if v and k not in ("a", "b", "zones_a", "zones_b", "same_text", "identical")}
    return d["outcome"], data.get("identical"), keep


def base():
    g = B()
    f = g.fp("U1", 20, 20, "GND", tht=True, extra_pads=[(23, 20, "VCC")])
    g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
    g.trk(5, 45, 30, 45, "S")
    g.zone("GND", [pcbnew.B_Cu], (2, 2, 38, 38))
    return g, f


def save_pair(name, mutate):
    g, f = base()
    a = g.save(os.path.join(work, name + "_a.kicad_pcb"))
    g, f = base()
    mutate(g, f)
    b = g.save(os.path.join(work, name + "_b.kicad_pcb"))
    return a, b


def miss(name, mutate):
    a, b = save_pair(name, mutate)
    o, ident, keep = diff(a, b)
    print(json.dumps({"case": name, "kind": "miss?", "outcome": o, "identical": ident, "reported": keep}))


def fz_conn(g, f):
    f.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)


def fz_clear(g, f):
    f.SetLocalClearance(mm(1.0))


mm = pcbnew.FromMM
miss("footprint_zone_connection_none", fz_conn)
miss("footprint_local_clearance", fz_clear)


def dim_on_cu(g, f):
    d = pcbnew.PCB_DIM_ALIGNED(g.b)
    d.SetLayer(pcbnew.F_Cu)
    d.SetStart(pcbnew.VECTOR2I(mm(5), mm(30)))
    d.SetEnd(pcbnew.VECTOR2I(mm(30), mm(30)))
    g.b.Add(d)


miss("dimension_on_F_Cu", dim_on_cu)


def target_on_cu(g, f):
    t = pcbnew.PCB_TARGET(g.b)
    t.SetLayer(pcbnew.F_Cu)
    t.SetPosition(pcbnew.VECTOR2I(mm(10), mm(30)))
    t.SetSize(mm(5))
    t.SetWidth(mm(0.2))
    g.b.Add(t)


miss("target_on_F_Cu", target_on_cu)


def ref_on_cu(g, f):
    f.Reference().SetLayer(pcbnew.F_Cu)


miss("reference_text_on_F_Cu", ref_on_cu)


def rect_on_cu(g, f):
    s = pcbnew.PCB_SHAPE(g.b)
    s.SetShape(pcbnew.SHAPE_T_RECT)
    s.SetStart(pcbnew.VECTOR2I(mm(5), mm(30)))
    s.SetEnd(pcbnew.VECTOR2I(mm(8), mm(33)))
    s.SetLayer(pcbnew.F_Cu)
    s.SetFilled(True)
    g.b.Add(s)


miss("gr_rect_on_F_Cu (control)", rect_on_cu)


def pad_thermal_angle(g, f):
    for p in f.Pads():
        if p.GetNumber() == "1":
            p.SetThermalSpokeAngleDegrees(90)


miss("pad_thermal_spoke_angle_90", pad_thermal_angle)


def zone_teardrop(g, f):
    pass


# False positives: pcbnew re-save of hand-written text
HAND = {
    "gr_text_minimal_on_cu": '(gr_text "X" (at 10 30) (layer "F.Cu") (effects (font (size 1 1))))',
    "gr_poly_old_fill_solid": '(gr_poly (pts (xy 5 30) (xy 8 30) (xy 8 33)) (stroke (width 0.1) (type solid)) (fill solid) (layer "F.Cu") (net "GND"))',
    "gr_line_on_cu_width_only": '(gr_line (start 5 30) (end 9 30) (width 0.2) (layer "B.Cu"))',
    "gr_circle_on_cu_child_order": '(gr_circle (center 12 30) (end 13 30) (layer "F.Cu") (stroke (width 0.2) (type solid)) (fill no))',
    "zone_priority0_name_empty": '(zone (net "GND") (name "") (layer "F.Cu") (priority 0) (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))))',
    "zone_connect_pads_yes": '(zone (net "GND") (layer "F.Cu") (hatch edge 0.5) (connect_pads yes (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))))',
    "zone_filled_areas_thickness_no": '(zone (net "GND") (layer "F.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (filled_areas_thickness no) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))))',
    "zone_hatch_fill_mode": '(zone (net "GND") (layer "F.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (mode hatch) (thermal_gap 0.5) (thermal_bridge_width 0.5) (hatch_thickness 1) (hatch_gap 1.5) (hatch_orientation 0)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))))',
    "zone_no_hatch_no_fill": '(zone (net "GND") (layer "F.Cu") (connect_pads (clearance 0.3)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))))',
    "zone_clockwise_start_other_corner": '(zone (net "GND") (layer "F.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 70 20) (xy 40 20) (xy 40 2) (xy 70 2))))',
    "zone_keepout_full": '(zone (net "") (layers "F.Cu" "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (keepout (tracks not_allowed) (vias not_allowed) (pads not_allowed) (copperpour not_allowed) (footprints allowed)) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 40 22) (xy 70 22) (xy 70 30) (xy 40 30))))',
    "pad_thermal_hand": None,
}


def fp_hand(extra):
    return ('(footprint "X" (layer "F.Cu") (at 50 40) (property "Reference" "J9" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)))) '
            '(property "Value" "X" (at 0 0) (layer "F.Fab") (effects (font (size 1 1)))) '
            f'(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net "GND") {extra}))')


HAND["pad_thermal_hand"] = fp_hand("(zone_connect 2) (thermal_bridge_width 0.30) (thermal_gap 0.5)")
HAND["fp_zone_hand"] = ('(footprint "X" (layer "F.Cu") (at 50 40) (property "Reference" "J8" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)))) '
                        '(property "Value" "X" (at 0 0) (layer "F.Fab") (effects (font (size 1 1)))) '
                        '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net "GND")) '
                        '(zone (net "GND") (layer "F.Cu") (connect_pads (clearance 0.3)) (polygon (pts (xy 47 37) (xy 53 37) (xy 53 43) (xy 47 43)))))')
HAND["fp_text_on_cu"] = fp_hand("").replace('(pad "1"', '(fp_text user "CU" (at 0 2) (layer "F.Cu") (effects (font (size 1 1)))) (pad "1"')
HAND["fp_poly_on_cu"] = fp_hand("").replace('(pad "1"', '(fp_poly (pts (xy 0 2) (xy 1 2) (xy 1 3)) (width 0.1) (fill solid) (layer "F.Cu")) (pad "1"')

g, f = base()
basep = g.save(os.path.join(work, "hand_base.kicad_pcb"))
src = open(basep).read()
helper = os.path.join(work, "resave.py")
open(helper, "w").write("import sys, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\npcbnew.SaveBoard(sys.argv[2], b)\n")
for name, text in HAND.items():
    a = os.path.join(work, f"fp_{name}_a.kicad_pcb")
    b = os.path.join(work, f"fp_{name}_b.kicad_pcb")
    i = src.rstrip().rfind(")")
    open(a, "w").write(src[:i] + "\t" + text + "\n)\n")
    r = subprocess.run(["python3", helper, a, b], capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({"case": name, "resave_failed": r.stderr[-300:]}))
        continue
    o, ident, keep = diff(a, b)
    print(json.dumps({"case": name, "kind": "resave", "outcome": o, "identical": ident, "reported": keep}))
