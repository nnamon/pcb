"""Review 12 diff probes. usage: PCB_BIN=... python3 diff12.py WORKDIR
miss: A and B differ by one text change that alters copper; want identical false.
resave: B is pcbnew's re-save of A; want identical true."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review10"))
import pcbnew  # noqa: E402
from lib import B, PCB  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)
helper = os.path.join(work, "resave.py")
open(helper, "w").write("import sys, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\npcbnew.SaveBoard(sys.argv[2], b)\n")


def diff(a, b):
    r = subprocess.run([PCB, "--json", "diff", a, b], capture_output=True, text=True)
    d = json.loads(r.stdout)
    data = d.get("data") or {}
    keep = {k: v for k, v in data.items() if v and k not in ("a", "b", "zones_a", "zones_b", "same_text", "identical")}
    return d["outcome"], data.get("identical"), keep


g = B()
g.fp("U1", 20, 20, "GND", tht=True, extra_pads=[(23, 20, "VCC")])
g.trk(5, 45, 30, 45, "S")
g.zone("GND", [pcbnew.B_Cu], (2, 2, 38, 38))
src = open(g.save(os.path.join(work, "base.kicad_pcb"))).read()
END = src.rstrip().rfind(")")


def with_items(*items):
    return src[:END] + "".join("\t" + t + "\n" for t in items) + ")\n"


def fp(extra):
    return ('(footprint "X" (layer "F.Cu") (uuid "aaaaaaaa-1111-4222-8333-444455556666") (at 50 40) '
            '(property "Reference" "J9" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)))) '
            '(property "Value" "X" (at 0 0) (layer "F.Fab") (effects (font (size 1 1)))) '
            f'{extra} (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net "GND")))')


def miss(name, a_item, b_item):
    a, b = os.path.join(work, name + "_a.kicad_pcb"), os.path.join(work, name + "_b.kicad_pcb")
    open(a, "w").write(with_items(a_item))
    open(b, "w").write(with_items(b_item))
    o, ident, keep = diff(a, b)
    print(json.dumps({"case": name, "kind": "miss?", "outcome": o, "identical": ident, "reported": keep}))


def resave(name, item):
    a, b = os.path.join(work, "rs_" + name + "_a.kicad_pcb"), os.path.join(work, "rs_" + name + "_b.kicad_pcb")
    open(a, "w").write(with_items(item))
    r = subprocess.run(["python3", helper, a, b], capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({"case": name, "resave_failed": r.stderr[-300:]}))
        return
    o, ident, keep = diff(a, b)
    print(json.dumps({"case": name, "kind": "resave", "outcome": o, "identical": ident, "reported": keep}))


TXT = '(gr_text "CU" (at 10 30 0) (layer "F.Cu") (uuid "bbbbbbbb-1111-4222-8333-444455556666") (effects (font (size 1 1) (thickness 0.15))))'
miss("gr_text_font_size", TXT, TXT.replace("(size 1 1)", "(size 3 3)"))
miss("gr_text_thickness", TXT, TXT.replace("(thickness 0.15)", "(thickness 0.5)"))
miss("gr_text_knockout", TXT, TXT.replace('(layer "F.Cu")', '(layer "F.Cu" knockout)'))
miss("gr_text_mirror_justify", TXT, TXT.replace("(thickness 0.15)))", "(thickness 0.15)) (justify left bottom mirror))"))
miss("gr_text_bold", TXT, TXT.replace("(thickness 0.15))", "(thickness 0.15) (bold yes))"))
POLY = '(gr_poly (pts (xy 5 30) (arc (start 8 30) (mid 9 31) (end 8 32)) (xy 5 32)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (net "GND") (uuid "cccccccc-1111-4222-8333-444455556666"))'
miss("gr_poly_arc_mid_moved", POLY, POLY.replace("(mid 9 31)", "(mid 12 31)"))
miss("gr_poly_fill_hatch", POLY, POLY.replace("(fill yes)", "(fill hatch)"))
FPL = '(fp_line (start 0 2) (end 3 2) (stroke (width 0.2) (type solid)) (layer "F.Cu") (uuid "dddddddd-1111-4222-8333-444455556666"))'
miss("fp_line_cu_width", fp(FPL), fp(FPL.replace("(width 0.2)", "(width 1.5)")))
FPP = '(fp_poly (pts (xy 0 2) (xy 2 2) (xy 2 4)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (uuid "eeeeeeee-1111-4222-8333-444455556666"))'
miss("fp_poly_cu_fill", fp(FPP), fp(FPP.replace("(fill yes)", "(fill no)")))
FPA = '(fp_poly (pts (xy 0 2) (arc (start 2 2) (mid 3 3) (end 2 4)) (xy 0 4)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (uuid "eeeeeeee-1111-4222-8333-444455556667"))'
miss("fp_poly_cu_arc_mid", fp(FPA), fp(FPA.replace("(mid 3 3)", "(mid 6 3)")))
FPT = '(fp_text user "CU" (at 0 2 0) (layer "F.Cu") (uuid "ffffffff-1111-4222-8333-444455556666") (effects (font (size 1 1) (thickness 0.15))))'
miss("fp_text_cu_moved", fp(FPT), fp(FPT.replace("(at 0 2 0)", "(at 4 2 0)")))
miss("fp_text_cu_text", fp(FPT), fp(FPT.replace('"CU"', '"COPPER TEXT"')))
miss("fp_text_cu_size", fp(FPT), fp(FPT.replace("(size 1 1)", "(size 3 3)")))
PRP = '(property "Cu" "MARK" (at 0 2 0) (layer "F.Cu") (uuid "ffffffff-1111-4222-8333-444455556667") (effects (font (size 1 1) (thickness 0.15))))'
miss("fp_property_cu_moved", fp(PRP), fp(PRP.replace("(at 0 2 0)", "(at 4 2 0)")))
FPR = '(fp_rect (start 0 2) (end 2 4) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Cu") (uuid "ffffffff-1111-4222-8333-444455556668"))'
miss("fp_rect_cu_fill", fp(FPR), fp(FPR.replace("(fill no)", "(fill yes)")))
miss("fp_attr_zone_connect", fp("(zone_connect 1)"), fp("(zone_connect 0)"))
# controls: moves that the key does read
miss("gr_text_moved (control)", TXT, TXT.replace("(at 10 30 0)", "(at 12 30 0)"))
miss("fp_line_cu_moved (control)", fp(FPL), fp(FPL.replace("(end 3 2)", "(end 4 2)")))

resave("gr_poly_no_stroke", '(gr_poly (pts (xy 5 30) (xy 8 30) (xy 8 33)) (fill yes) (layer "F.Cu") (net "GND"))')
resave("gr_rect_fill_none", '(gr_rect (start 5 30) (end 8 33) (stroke (width 0.2) (type solid)) (fill none) (layer "F.Cu"))')
resave("gr_arc_on_cu", '(gr_arc (start 5 30) (mid 6 31) (end 7 30) (stroke (width 0.2) (type solid)) (layer "F.Cu"))')
resave("gr_text_no_angle", '(gr_text "X" (at 10 30) (layer "F.Cu") (effects (font (size 1 1) (thickness 0.15))))')
resave("gr_poly_with_arc", '(gr_poly (pts (xy 5 30) (arc (start 8 30) (mid 9 31) (end 8 32)) (xy 5 32)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (net "GND"))')
resave("target_on_cu", '(target plus (at 30 30) (size 5) (width 0.1) (layer "F.Cu"))')
resave("dimension_on_cu", '(dimension (type aligned) (layer "F.Cu") (pts (xy 5 30) (xy 25 30)) (height 2) '
       '(gr_text "20 mm" (at 15 28 0) (layer "F.Cu") (effects (font (size 1 1) (thickness 0.15)))) (format (units 2) (units_format 1) (precision 2)) '
       '(style (thickness 0.15) (arrow_length 1.27) (text_position_mode 0) (extension_height 0.58642) (extension_offset 0.5)))')
resave("fp_line_cu_width_only", fp('(fp_line (start 0 2) (end 3 2) (width 0.2) (layer "F.Cu"))'))
resave("fp_zone_connect_attr", fp("(zone_connect 0) (clearance 0.20)"))
resave("gr_text_knockout", '(gr_text "X" (at 10 30) (layer "F.Cu" knockout) (effects (font (size 1 1) (thickness 0.15))))')
ZH = ('(zone (net "GND") (layer "F.Cu") (uuid "12121212-1111-4222-8333-444455556666") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) '
      '(fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))) (polygon (pts (xy 50 8) (xy 55 8) (xy 55 12) (xy 50 12))))')
resave("zone_with_hole", ZH)
miss("zone_hole_moved", ZH, ZH.replace("(xy 50 8) (xy 55 8) (xy 55 12) (xy 50 12)", "(xy 60 8) (xy 65 8) (xy 65 12) (xy 60 12)"))
miss("zone_hole_removed", ZH, ZH.replace(" (polygon (pts (xy 50 8) (xy 55 8) (xy 55 12) (xy 50 12)))", ""))
# review 11 N4 variants
resave("n4_zone_prio0_name_empty_2layer", '(zone (net "GND") (name "") (layers "F.Cu" "B.Cu") (priority 0) (hatch full 0.508) (connect_pads (clearance 0.25)) (min_thickness 0.2) (filled_areas_thickness no) (fill (thermal_gap 0.4) (thermal_bridge_width 0.4)) (polygon (pts (xy 41 3) (xy 69 3) (xy 69 19) (xy 41 19))))')
resave("n4_rule_area_net_empty", '(zone (net "") (layer "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (keepout (tracks allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed)) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 41 22) (xy 69 22) (xy 69 28) (xy 41 28))))')
resave("n4_hatch_zone", '(zone (net "GND") (layer "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (mode hatch) (thermal_gap 0.5) (thermal_bridge_width 0.5) (hatch_thickness 0.8) (hatch_gap 1.2) (hatch_orientation 45)) (polygon (pts (xy 41 22) (xy 69 22) (xy 69 28) (xy 41 28))))')
resave("n4_gr_line_width_b", '(gr_line (start 41.25 30) (end 49.125 31.5) (width 0.25) (layer "F.Cu") (net "GND"))')
resave("n4_pad_numbers_text", fp("").replace('(net "GND"))', '(net "GND") (clearance 0.250) (thermal_bridge_angle 90.0))'))
# review 11 N5 variant: footprint Value property moved from F.Fab to B.Cu
miss("n5_value_to_B_Cu", fp(""), fp("").replace('(property "Value" "X" (at 0 0) (layer "F.Fab")', '(property "Value" "X" (at 0 0) (layer "B.Cu")'))
miss("n5_pad_clearance", fp(""), fp("").replace('(net "GND"))', '(net "GND") (clearance 0.5))'))
