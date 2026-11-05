"""Cases for `pcb diff`, on the boards tests/cases/edit_cases.py writes (so each change is known from its
operations), plus a board read from a git revision.

Usage: python3 diff_cases.py pcb-binary edit-cases-workdir workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, ew, work = sys.argv[1:4]
os.makedirs(work, exist_ok=True)


def run(*args, cwd=None):
    r = subprocess.run([os.path.abspath(pcb), "--json", "diff", *args], capture_output=True, text=True, cwd=cwd)
    d, problems = check(r.stdout, r.returncode)
    return d, problems


E = lambda case, out=False: os.path.join(ew, f"{case}{'.out' if out else ''}.kicad_pcb")
results = {}
# name: (a, b, test on data)
CASES = {
    "identical": (E("join_n"), E("join_n"), lambda d: d["identical"] and not d["copper"] and not d["footprints"]),
    "added_track": (E("join_n"), E("join_n", True), lambda d: d["copper"] == {"N": {"tracks_added": 1, "tracks_removed": 0, "length_added_mm": 20.0, "length_removed_mm": 0.0, "vias_added": 0, "vias_removed": 0, "locks_changed": 0}} and not d["footprints"]),
    "tracks_and_vias": (E("join_n_through_vias"), E("join_n_through_vias", True), lambda d: (d["copper"]["N"]["tracks_added"], d["copper"]["N"]["vias_added"]) == (3, 2)),
    "width_change": (E("set_width"), E("set_width", True), lambda d: (d["copper"]["W"]["tracks_added"], d["copper"]["W"]["tracks_removed"]) == (1, 1)),
    "footprint_moved": (E("move_footprint"), E("move_footprint", True), lambda d: [(f["ref"], f["change"]) for f in d["footprints"]] == [("N2", "moved")] and not d["copper"]),
    "reversed": (E("join_n", True), E("join_n"), lambda d: d["copper"]["N"]["tracks_removed"] == 1),
}
for name, (a, b, test) in CASES.items():
    d, problems = run(a, b)
    results[name] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "done" and test(d["data"]) else f"unexpected: {json.dumps(d.get('data'))[:400]}")

# a git revision: commit the input, then compare HEAD:board with the edited file
g = os.path.join(work, "repo")
shutil.rmtree(g, ignore_errors=True)
os.makedirs(g)
shutil.copy(E("join_n"), os.path.join(g, "b.kicad_pcb"))
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
for c in (["init", "-q"], ["add", "b.kicad_pcb"], ["commit", "-q", "-m", "x"]):
    subprocess.run(["git", *c], cwd=g, check=True, capture_output=True, env=env)
shutil.copy(E("join_n", True), os.path.join(g, "b.kicad_pcb"))
d, problems = run("HEAD:b.kicad_pcb", "b.kicad_pcb", cwd=g)
results["git_revision"] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "done" and d["data"]["copper"].get("N", {}).get("tracks_added") == 1 else f"unexpected: {json.dumps(d.get('data'))[:300]}")
d, problems = run("HEAD:no-such.kicad_pcb", "b.kicad_pcb", cwd=g)
results["missing_revision_refused"] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "refused" and d["error"]["code"] == "usage" else f"outcome {d['outcome']}")
png = os.path.join(work, "diff.png")
d, problems = run(E("join_n"), E("join_n", True), "--png", png)
results["png"] = "; ".join(problems) if problems else ("ok" if os.path.getsize(png) > 1000 and d.get("written") == png else "no PNG")

# ---- Reviews 8 to 12 (M1), moved from tests/regressions@e17bfac/r08 to r12; see docs/reviews/audit/AUDIT_m1.md ----
# Pairs of boards with one known change each (a "miss" if diff called them identical), and pcbnew re-saves of
# hand-written text, which must compare identical. Boards: tests/lib/synth_board.py and tests/lib/gate_board.py.
LIB = os.path.join(here, "..", "lib")
mw = os.path.join(work, "m1")
os.makedirs(mw, exist_ok=True)


def build(kind, variant):
    p = os.path.join(mw, f"base_{kind}_{variant}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(LIB, "synth_board.py" if kind == "synth" else "gate_board.py"), variant, p], check=True, capture_output=True)
    return p


def wr(name, text):
    p = os.path.join(mw, name + ".kicad_pcb")
    open(p, "w").write(text)
    return p


def resaved(name, text):
    a = wr(name + "_a", text)
    b = os.path.join(mw, name + "_b.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(LIB, "gate_board.py"), "resave", a, b], check=True, capture_output=True)
    return a, b


def pcbnew_edit(name, src, code):
    p = os.path.join(mw, name + ".kicad_pcb")
    subprocess.run([sys.executable, "-c", f"import pcbnew\nb = pcbnew.LoadBoard({src!r})\nmm = pcbnew.FromMM\nfp = {{f.GetReference(): f for f in b.GetFootprints()}}\n{code}\npcbnew.SaveBoard({p!r}, b)\n"], check=True, capture_output=True)
    return p


def diff11(change):
    p = os.path.join(mw, f"d11_{change}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(LIB, "gate_board.py"), "diff11", change, p], check=True, capture_output=True)
    return p


app8 = lambda t, extra: t.rstrip()[:-1] + extra + ")\n"  # reviews 8 and 9
app10 = lambda t, extra: t.rstrip()[:-1] + extra + "\n)\n"  # reviews 10 to 12


def zblock(t, idx):
    sys.path.insert(0, LIB)
    from gate_board import blocks
    return blocks(t, "zone")[idx]


base8, arc8, gz8 = build("synth", "base"), build("synth", "arc"), build("synth", "gzone")
A8, ARC9 = open(base8).read(), open(arc8).read()
fps = lambda d: [(f["ref"], f["change"]) for f in d["footprints"]]
IDENT = lambda d: d["identical"]
CHANGED = lambda d: not d["identical"]
M1 = {}  # name: (a, b, test on data)
# review 8, 7 and 18: footprints, pads, copper, outline, zones and locks
M1["r08_turned"] = (base8, pcbnew_edit("turn90", base8, "fp['N2'].SetOrientationDegrees(90)"), lambda d: fps(d) == [("N2", "turned")])  # source: review 8, turned
M1["r08_flipped"] = (base8, pcbnew_edit("flip", base8, "fp['N2'].Flip(fp['N2'].GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)"), lambda d: any(r == "N2" and "flipped" in c for r, c in fps(d)))  # source: review 8, flipped
M1["r08_rotation_270_equals_minus_90"] = (wr("r270", A8.replace("(at 40 15)", "(at 40 15 270)", 1)), wr("rm90", A8.replace("(at 40 15)", "(at 40 15 -90)", 1)), IDENT)  # source: review 8, rotation_270_equals_minus_90
M1["r08_footprint_removed"] = (base8, pcbnew_edit("removed", base8, "b.Remove(fp['S3'])"), lambda d: fps(d) == [("S3", "removed")])  # source: review 8, footprint_removed
M1["r08_pad_size_changed"] = (base8, pcbnew_edit("padsize", base8, "p = list(fp['N2'].Pads())[0]; p.SetSize(pcbnew.VECTOR2I(mm(2), mm(2)))"), CHANGED)  # source: review 8, pad_size_changed
M1["r08_pad_moved_in_footprint"] = (base8, pcbnew_edit("padmove", base8, "p = list(fp['N2'].Pads())[0]; p.SetFPRelativePosition(pcbnew.VECTOR2I(mm(1), 0))"), CHANGED)  # source: review 8, pad_moved_in_footprint
_dup = app8(A8, '\t(footprint "x" (layer "F.Cu") (at 5 35) (property "Reference" "N2") (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "N")))\n')
M1["r08_duplicate_reference_move_seen"] = (wr("dupref", _dup), wr("dupref_moved", _dup.replace("(at 40 15)", "(at 41 15)", 1)), CHANGED)  # source: review 8, duplicate_reference_move_seen
M1["r08_duplicate_track_added"] = (base8, wr("dupseg", app8(A8, '\t(segment (start 3 30) (end 45 30) (width 0.2) (layer "F.Cu") (net "S"))\n')),
                                   lambda d: d["copper"].get("S", {}).get("tracks_added") == 1 and abs(d["copper"]["S"]["length_added_mm"] - 42) < 1e-6)  # source: review 8, duplicate_track_added
M1["r08_via_size_change"] = (base8, wr("viasize", A8.replace("(size 0.8)\n\t\t(drill 0.4)", "(size 0.9)\n\t\t(drill 0.4)", 1)), lambda d: d["copper"].get("L", {}).get("vias_added") == 1 and d["copper"]["L"]["vias_removed"] == 1)  # source: review 8, via_size_change
M1["r08_outline_change_not_identical"] = (base8, wr("outline", A8.replace("(end 60 0)", "(end 70 0)", 1).replace("(start 60 0)", "(start 70 0)", 1)), CHANGED)  # source: review 8, outline_change_not_identical
M1["r08_arc_change_not_identical"] = (arc8, pcbnew_edit("arcmoved", arc8, "a = [t for t in b.GetTracks() if t.GetClass() == 'PCB_ARC'][0]; a.SetMid(pcbnew.VECTOR2I(mm(30), mm(12)))"), CHANGED)  # source: review 8, arc_change_not_identical
M1["r08_zone_moved_not_identical"] = (gz8, pcbnew_edit("gz2", gz8, "z = b.Zones()[0]; z.Move(pcbnew.VECTOR2I(mm(1), 0))"), CHANGED)  # source: review 8, zone_moved_not_identical
M1["r08_lock_change_seen"] = (base8, wr("unlock", A8.replace("(locked yes)\n\t\t(net \"L\")", "(net \"L\")", 1)), CHANGED)  # source: review 8, lock_change_seen
# review 9: diff misses on the arc board
_via9 = '\t(via (at 33 33) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net "N"))\n'
M1["r09_via_layers_changed"] = (wr("r9via_a", app8(ARC9, _via9)), wr("r9via_b", app8(ARC9, _via9.replace('"F.Cu" "B.Cu"', '"F.Cu" "In1.Cu"'))), CHANGED)  # source: review 9, via_layers_changed
_arc9 = re.search(r"\t\(arc\n.*?\n\t\)\n", ARC9, re.S).group(0)
M1["r09_arc_lock_changed"] = (arc8, wr("r9arclock", ARC9.replace(_arc9, _arc9.replace("\t\t(layer", "\t\t(locked yes)\n\t\t(layer", 1))), CHANGED)  # source: review 9, arc_lock_changed
_z9 = '\t(zone (net "GND") (layer "B.Cu") (uuid "12345678-0000-4000-8000-000000000009") (polygon (pts (xy 1 1) (xy 5 1) (xy 5 5))) (polygon (pts (xy 10 10) (xy 15 10) (xy 15 15))))\n'
M1["r09_zone_second_outline_changed"] = (wr("r9z2_a", app8(ARC9, _z9)), wr("r9z2_b", app8(ARC9, _z9.replace("(xy 15 15)", "(xy 15 19)"))), CHANGED)  # source: review 9, zone_second_outline_changed
_zc9 = '\t(zone (net "GND") (layer "B.Cu") (uuid "12345678-0000-4000-8000-00000000000a") (connect_pads (clearance 0.3)) (polygon (pts (xy 1 1) (xy 5 1) (xy 5 5))))\n'
M1["r09_zone_clearance_changed"] = (wr("r9zc_a", app8(ARC9, _zc9)), wr("r9zc_b", app8(ARC9, _zc9.replace("(clearance 0.3)", "(clearance 0.6)"))), CHANGED)  # source: review 9, zone_clearance_changed
_fpe9 = '\t(footprint "cut" (layer "F.Cu") (at 30 20) (property "Reference" "H9" (at 0 0 0) (layer "F.SilkS")) (fp_line (start -2 -2) (end 2 -2) (layer "Edge.Cuts") (stroke (width 0.1) (type solid))))\n'
M1["r09_footprint_edge_cut_moved"] = (wr("r9fpe_a", app8(ARC9, _fpe9)), wr("r9fpe_b", app8(ARC9, _fpe9.replace("(end 2 -2)", "(end 3 -2)"))), CHANGED)  # source: review 9, footprint_edge_cut_moved
M1["r09_pad_layer_order_only"] = (arc8, wr("r9padlayers", ARC9.replace('(layers "F.Cu" "F.Mask" "F.Paste")', '(layers "F.Cu" "F.Paste" "F.Mask")', 1)), IDENT)  # source: review 9, pad_layer_order_only
M1["r09_pad_shape_rect_to_circle"] = (arc8, wr("r9padshape", ARC9.replace("smd rect", "smd circle", 1)), CHANGED)  # source: review 9, pad_shape_rect_to_circle
M1["r09_number_format_only"] = (wr("r9num_a", app8(ARC9, _via9)), wr("r9num_b", app8(ARC9, _via9.replace("(at 33 33)", "(at 33.000 33.0000)"))), IDENT)  # source: review 9, number_format_only
M1["r09_footprint_value_changed"] = (arc8, wr("r9value", ARC9.replace('(property "Value" "R"', '(property "Value" "C"', 1)), CHANGED)  # source: review 9, footprint_value_changed
# review 10 (closures): a second outline added to a filled zone
_st = open(build("gate", "stitch")).read()
_zs, _ze = zblock(_st, -1)
_z = _st[_zs:_ze]
M1["r10_zone_second_outline"] = (wr("r10z2_a", _st), wr("r10z2_b", _st[:_zs] + _z.replace("\t\t(polygon", "\t\t(polygon\n\t\t\t(pts (xy 50 2) (xy 55 2) (xy 55 8) (xy 50 8))\n\t\t)\n\t\t(polygon", 1) + _st[_ze:]), CHANGED)  # source: review 10, zone_second_outline
# review 10: zone settings, copper graphics, footprint zones, pad overrides, a cut-out; and pcbnew re-saves
_d10 = open(build("gate", "diff10")).read()
_zs, _ze = zblock(_d10, -1)  # the top-level GND zone (footprint zones come first in the file)
_zt = _d10[_zs:_ze]
_z10 = lambda name, new: (wr(f"r10_{name}_a", _d10), wr(f"r10_{name}_b", _d10[:_zs] + new + _d10[_ze:]), CHANGED)
M1["r10_zone_thermal_gap"] = _z10("tg", _zt.replace("(thermal_gap 0.5)", "(thermal_gap 1.5)"))  # source: review 10, zone_thermal_gap
M1["r10_zone_thermal_bridge"] = _z10("tb", _zt.replace("(thermal_bridge_width 0.5)", "(thermal_bridge_width 1.5)"))  # source: review 10, zone_thermal_bridge
M1["r10_zone_connect_pads_none"] = _z10("cpn", _zt.replace("(connect_pads\n", "(connect_pads no\n"))  # source: review 10, zone_connect_pads_none
M1["r10_zone_island_mode"] = _z10("isl", _zt.replace("(island_removal_mode 0)", "(island_removal_mode 1)"))  # source: review 10, zone_island_mode
M1["r10_zone_hatched"] = _z10("hatch", re.sub(r"\(fill\b", "(fill (mode hatch)", _zt, count=1))  # source: review 10, zone_hatched
M1["r10_copper_gr_poly_added"] = (wr("r10poly_a", _d10), wr("r10poly_b", app10(_d10, '\t(gr_poly\n\t\t(pts (xy 40 30) (xy 45 30) (xy 45 35) (xy 40 35))\n\t\t(stroke (width 0) (type solid))\n\t\t(fill yes)\n\t\t(layer "F.Cu")\n\t\t(net "GND")\n\t)')), CHANGED)  # source: review 10, copper_gr_poly_added
M1["r10_copper_gr_text_added"] = (wr("r10text_a", _d10), wr("r10text_b", app10(_d10, '\t(gr_text "X" (at 40 40 0) (layer "F.Cu") (effects (font (size 2 2) (thickness 0.3))))')), CHANGED)  # source: review 10, copper_gr_text_added
_fzs, _fze = zblock(_d10, 0)
M1["r10_fp_zone_outline"] = (wr("r10fz_a", _d10), wr("r10fz_b", _d10[:_fzs] + _d10[_fzs:_fze].replace("(xy 66 32)", "(xy 70 32)") + _d10[_fze:]), CHANGED)  # source: review 10, fp_zone_outline
sys.path.insert(0, LIB)
from gate_board import blocks  # noqa: E402
_ps, _pe = blocks(_d10, "pad")[0]
M1["r10_pad_zone_connect"] = (wr("r10pzc_a", _d10), wr("r10pzc_b", _d10[:_ps] + _d10[_ps:_pe - 1] + " (zone_connect 0))" + _d10[_pe:]), CHANGED)  # source: review 10, pad_zone_connect
_withc = app10(_d10, '\t(gr_circle (center 40 25) (end 42 25) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))')
M1["r10_edge_circle_radius"] = (wr("r10circ_a", _withc), wr("r10circ_b", _withc.replace("(end 42 25)", "(end 43 25)")), CHANGED)  # source: review 10, edge_circle_radius
R10_RESAVE = {
    "resave_base": _d10,
    "resave_via_layers_reversed": app10(_d10, '\t(via (at 20 30) (size 0.6) (drill 0.3) (layers "B.Cu" "F.Cu") (net "GND"))'),
    "resave_minimal_zone": app10(_d10, '\t(zone (net "GND") (layer "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0.30)) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 2 22) (xy 20 22) (xy 20 33) (xy 2 33))))'),
    "resave_partial_keepout": app10(_d10, '\t(zone (layers "F.Cu") (hatch edge 0.5) (keepout (tracks not_allowed)) (polygon (pts (xy 25 5) (xy 30 5) (xy 30 15) (xy 25 15))))'),
    "resave_zone_layers_FB": app10(_d10, '\t(zone (net "GND") (layers "F&B.Cu") (uuid "aaaaaaaa-0000-0000-0000-000000000001") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 2 22) (xy 20 22) (xy 20 33) (xy 2 33))))'),
    "resave_track_width_long": app10(_d10, '\t(segment (start 5 40) (end 30 40) (width 0.20000001) (layer "F.Cu") (net "S"))'),
}
for _n, _t in R10_RESAVE.items():
    M1["r10_" + _n] = (*resaved("r10_" + _n, _t), IDENT)  # source: review 10, <name> (each R10_RESAVE key)
# review 11: footprint settings and items on copper changed through pcbnew; re-saves of hand-written text
_d11a = diff11("none")
for _n in ("footprint_zone_connection_none", "footprint_local_clearance", "dimension_on_F_Cu", "target_on_F_Cu", "reference_text_on_F_Cu", "gr_rect_on_F_Cu", "pad_thermal_spoke_angle_90"):
    M1["r11_" + _n] = (_d11a, diff11(_n), CHANGED)  # source: review 11, <name> (gr_rect_on_F_Cu is its "(control)")
_d11 = open(_d11a).read()
_fp11 = lambda extra: ('(footprint "X" (layer "F.Cu") (at 50 40) (property "Reference" "J9" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)))) '
                       '(property "Value" "X" (at 0 0) (layer "F.Fab") (effects (font (size 1 1)))) '
                       f'(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net "GND") {extra}))')
R11_HAND = {
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
    "pad_thermal_hand": _fp11("(zone_connect 2) (thermal_bridge_width 0.30) (thermal_gap 0.5)"),
    "fp_zone_hand": ('(footprint "X" (layer "F.Cu") (at 50 40) (property "Reference" "J8" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)))) '
                     '(property "Value" "X" (at 0 0) (layer "F.Fab") (effects (font (size 1 1)))) '
                     '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net "GND")) '
                     '(zone (net "GND") (layer "F.Cu") (connect_pads (clearance 0.3)) (polygon (pts (xy 47 37) (xy 53 37) (xy 53 43) (xy 47 43)))))'),
    "fp_text_on_cu": _fp11("").replace('(pad "1"', '(fp_text user "CU" (at 0 2) (layer "F.Cu") (effects (font (size 1 1)))) (pad "1"'),
    "fp_poly_on_cu": _fp11("").replace('(pad "1"', '(fp_poly (pts (xy 0 2) (xy 1 2) (xy 1 3)) (width 0.1) (fill solid) (layer "F.Cu")) (pad "1"'),
}
_i11 = _d11.rstrip().rfind(")")
for _n, _t in R11_HAND.items():
    M1["r11_" + _n] = (*resaved("r11_" + _n, _d11[:_i11] + "\t" + _t + "\n)\n"), IDENT)  # source: review 11, <name> (each R11_HAND key)
# review 12: copper text and graphics changes, footprint copper items, zone holes; re-saves of hand-written text
_d12 = open(build("gate", "diff12")).read()
_end12 = _d12.rstrip().rfind(")")
_with12 = lambda *items: _d12[:_end12] + "".join("\t" + t + "\n" for t in items) + ")\n"
_fp12 = lambda extra: ('(footprint "X" (layer "F.Cu") (uuid "aaaaaaaa-1111-4222-8333-444455556666") (at 50 40) '
                       '(property "Reference" "J9" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1)))) '
                       '(property "Value" "X" (at 0 0) (layer "F.Fab") (effects (font (size 1 1)))) '
                       f'{extra} (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask") (net "GND")))')
_TXT = '(gr_text "CU" (at 10 30 0) (layer "F.Cu") (uuid "bbbbbbbb-1111-4222-8333-444455556666") (effects (font (size 1 1) (thickness 0.15))))'
_POLY = '(gr_poly (pts (xy 5 30) (arc (start 8 30) (mid 9 31) (end 8 32)) (xy 5 32)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (net "GND") (uuid "cccccccc-1111-4222-8333-444455556666"))'
_FPL = '(fp_line (start 0 2) (end 3 2) (stroke (width 0.2) (type solid)) (layer "F.Cu") (uuid "dddddddd-1111-4222-8333-444455556666"))'
_FPP = '(fp_poly (pts (xy 0 2) (xy 2 2) (xy 2 4)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (uuid "eeeeeeee-1111-4222-8333-444455556666"))'
_FPA = '(fp_poly (pts (xy 0 2) (arc (start 2 2) (mid 3 3) (end 2 4)) (xy 0 4)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (uuid "eeeeeeee-1111-4222-8333-444455556667"))'
_FPT = '(fp_text user "CU" (at 0 2 0) (layer "F.Cu") (uuid "ffffffff-1111-4222-8333-444455556666") (effects (font (size 1 1) (thickness 0.15))))'
_PRP = '(property "Cu" "MARK" (at 0 2 0) (layer "F.Cu") (uuid "ffffffff-1111-4222-8333-444455556667") (effects (font (size 1 1) (thickness 0.15))))'
_FPR = '(fp_rect (start 0 2) (end 2 4) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Cu") (uuid "ffffffff-1111-4222-8333-444455556668"))'
_ZH = ('(zone (net "GND") (layer "F.Cu") (uuid "12121212-1111-4222-8333-444455556666") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) '
       '(fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 40 2) (xy 70 2) (xy 70 20) (xy 40 20))) (polygon (pts (xy 50 8) (xy 55 8) (xy 55 12) (xy 50 12))))')
R12_MISS = {
    "gr_text_font_size": (_TXT, _TXT.replace("(size 1 1)", "(size 3 3)")),
    "gr_text_thickness": (_TXT, _TXT.replace("(thickness 0.15)", "(thickness 0.5)")),
    "gr_text_knockout": (_TXT, _TXT.replace('(layer "F.Cu")', '(layer "F.Cu" knockout)')),
    "gr_text_mirror_justify": (_TXT, _TXT.replace("(thickness 0.15)))", "(thickness 0.15)) (justify left bottom mirror))")),
    "gr_text_bold": (_TXT, _TXT.replace("(thickness 0.15))", "(thickness 0.15) (bold yes))")),
    "gr_poly_arc_mid_moved": (_POLY, _POLY.replace("(mid 9 31)", "(mid 12 31)")),
    "gr_poly_fill_hatch": (_POLY, _POLY.replace("(fill yes)", "(fill hatch)")),
    "fp_line_cu_width": (_fp12(_FPL), _fp12(_FPL.replace("(width 0.2)", "(width 1.5)"))),
    "fp_poly_cu_fill": (_fp12(_FPP), _fp12(_FPP.replace("(fill yes)", "(fill no)"))),
    "fp_poly_cu_arc_mid": (_fp12(_FPA), _fp12(_FPA.replace("(mid 3 3)", "(mid 6 3)"))),
    "fp_text_cu_moved": (_fp12(_FPT), _fp12(_FPT.replace("(at 0 2 0)", "(at 4 2 0)"))),
    "fp_text_cu_text": (_fp12(_FPT), _fp12(_FPT.replace('"CU"', '"COPPER TEXT"'))),
    "fp_text_cu_size": (_fp12(_FPT), _fp12(_FPT.replace("(size 1 1)", "(size 3 3)"))),
    "fp_property_cu_moved": (_fp12(_PRP), _fp12(_PRP.replace("(at 0 2 0)", "(at 4 2 0)"))),
    "fp_rect_cu_fill": (_fp12(_FPR), _fp12(_FPR.replace("(fill no)", "(fill yes)"))),
    "fp_attr_zone_connect": (_fp12("(zone_connect 1)"), _fp12("(zone_connect 0)")),
    "gr_text_moved": (_TXT, _TXT.replace("(at 10 30 0)", "(at 12 30 0)")),  # a control
    "fp_line_cu_moved": (_fp12(_FPL), _fp12(_FPL.replace("(end 3 2)", "(end 4 2)"))),  # a control
    "zone_hole_moved": (_ZH, _ZH.replace("(xy 50 8) (xy 55 8) (xy 55 12) (xy 50 12)", "(xy 60 8) (xy 65 8) (xy 65 12) (xy 60 12)")),
    "zone_hole_removed": (_ZH, _ZH.replace(" (polygon (pts (xy 50 8) (xy 55 8) (xy 55 12) (xy 50 12)))", "")),
    "n5_value_to_B_Cu": (_fp12(""), _fp12("").replace('(property "Value" "X" (at 0 0) (layer "F.Fab")', '(property "Value" "X" (at 0 0) (layer "B.Cu")')),
    "n5_pad_clearance": (_fp12(""), _fp12("").replace('(net "GND"))', '(net "GND") (clearance 0.5))')),
}
for _n, (_a, _b) in R12_MISS.items():
    M1["r12_" + _n] = (wr(f"r12_{_n}_a", _with12(_a)), wr(f"r12_{_n}_b", _with12(_b)), CHANGED)  # source: review 12, <name> (each R12_MISS key)
R12_RESAVE = {
    "gr_poly_no_stroke": '(gr_poly (pts (xy 5 30) (xy 8 30) (xy 8 33)) (fill yes) (layer "F.Cu") (net "GND"))',
    "gr_rect_fill_none": '(gr_rect (start 5 30) (end 8 33) (stroke (width 0.2) (type solid)) (fill none) (layer "F.Cu"))',
    "gr_arc_on_cu": '(gr_arc (start 5 30) (mid 6 31) (end 7 30) (stroke (width 0.2) (type solid)) (layer "F.Cu"))',
    "gr_text_no_angle": '(gr_text "X" (at 10 30) (layer "F.Cu") (effects (font (size 1 1) (thickness 0.15))))',
    "gr_poly_with_arc": '(gr_poly (pts (xy 5 30) (arc (start 8 30) (mid 9 31) (end 8 32)) (xy 5 32)) (stroke (width 0.1) (type solid)) (fill yes) (layer "F.Cu") (net "GND"))',
    "target_on_cu": '(target plus (at 30 30) (size 5) (width 0.1) (layer "F.Cu"))',
    "dimension_on_cu": ('(dimension (type aligned) (layer "F.Cu") (pts (xy 5 30) (xy 25 30)) (height 2) '
                        '(gr_text "20 mm" (at 15 28 0) (layer "F.Cu") (effects (font (size 1 1) (thickness 0.15)))) (format (units 2) (units_format 1) (precision 2)) '
                        '(style (thickness 0.15) (arrow_length 1.27) (text_position_mode 0) (extension_height 0.58642) (extension_offset 0.5)))'),
    "fp_line_cu_width_only": _fp12('(fp_line (start 0 2) (end 3 2) (width 0.2) (layer "F.Cu"))'),
    "fp_zone_connect_attr": _fp12("(zone_connect 0) (clearance 0.20)"),
    "gr_text_knockout": '(gr_text "X" (at 10 30) (layer "F.Cu" knockout) (effects (font (size 1 1) (thickness 0.15))))',
    "zone_with_hole": _ZH,
    "n4_zone_prio0_name_empty_2layer": '(zone (net "GND") (name "") (layers "F.Cu" "B.Cu") (priority 0) (hatch full 0.508) (connect_pads (clearance 0.25)) (min_thickness 0.2) (filled_areas_thickness no) (fill (thermal_gap 0.4) (thermal_bridge_width 0.4)) (polygon (pts (xy 41 3) (xy 69 3) (xy 69 19) (xy 41 19))))',
    "n4_rule_area_net_empty": '(zone (net "") (layer "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) (keepout (tracks allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) (footprints allowed)) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 41 22) (xy 69 22) (xy 69 28) (xy 41 28))))',
    "n4_hatch_zone": '(zone (net "GND") (layer "B.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (mode hatch) (thermal_gap 0.5) (thermal_bridge_width 0.5) (hatch_thickness 0.8) (hatch_gap 1.2) (hatch_orientation 45)) (polygon (pts (xy 41 22) (xy 69 22) (xy 69 28) (xy 41 28))))',
    "n4_gr_line_width_b": '(gr_line (start 41.25 30) (end 49.125 31.5) (width 0.25) (layer "F.Cu") (net "GND"))',
    "n4_pad_numbers_text": _fp12("").replace('(net "GND"))', '(net "GND") (clearance 0.250) (thermal_bridge_angle 90.0))'),
}
for _n, _t in R12_RESAVE.items():
    M1["r12_resave_" + _n] = (*resaved("r12_rs_" + _n, _with12(_t)), IDENT)  # source: review 12, <name> (each R12_RESAVE key)
for name, (a, b, test) in M1.items():
    d, problems = run(a, b)
    results[name] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "done" and test(d["data"]) else f"unexpected: {json.dumps(d.get('data'))[:400]}")
# ---- end of reviews 8 to 12 ----
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
