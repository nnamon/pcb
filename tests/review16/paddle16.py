"""The paddle-keyer project through pcb's own flow (import, zone, paste, art, check, gate pass, release), with faults
put in at the board, pcb.toml or the released files. Covers review 15's closures for the golden comparison, the
frame, check, gate and release, and looks for what the gate and release still let through.

Usage: python3 paddle16.py workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r16lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
ZIP = f"{L.STEM}_gerbers.zip"


def W(*p):
    return os.path.join(work, *p)


def flow(name, board_code=None, toml=None, rezone=False, waive=False):
    """A paddle copy, a fault, gate, release. Returns (folder, gate, release)."""
    d = L.paddle(work, name)
    b = os.path.join(d, "board.kicad_pcb")
    if board_code:
        L.post(b, board_code)
    if toml:
        toml(d)
    if rezone:
        z = L.pcb("zone", "--project", d, "--work", W(name + "_zw"))
        assert z["outcome"] in ("done", "rejected"), z
    if waive:
        L.waive_all(d, W(name + "_cw"))
    g = L.gate(d, W(name + "_gw"))
    r = L.release(d, W(name + "_out"), W(name + "_rw")) if g["outcome"] == "done" else g
    return d, g, r


def golden(a, name, board=None):
    args = ["compare-gerbers", a, L.GOLDEN_ZIP, "--work", W("cmp_" + name), "--explain", L.EXPLAIN]
    if board:
        args += ["--board", board]
    c = L.pcb(*args)
    un = {k: [(u["side"], u["mm2"], u["bbox"]) for u in v.get("unexplained", [])][:3] for k, v in c["data"].get("layers", {}).items() if v.get("unexplained")}
    return dict(compare=L.slim(c), unexplained=un, missing=c["data"].get("missing"), layers=sorted(c["data"].get("layers", {})), drill=c["data"].get("drill", {}).get("matched"),
                error=c["data"].get("error"))


# --- control: the paddle keyer released by pcb against the ordered files (closures 1, 2, 4)
d, g, r = flow("control")
CTL, CTL_OUT = d, r.get("written")
L.emit("control", gate=L.slim(g), release=L.slim(r), gerber_layers=r["data"].get("gerber_layers"), problems=r["data"].get("problems"),
       **golden(os.path.join(CTL_OUT, ZIP), "control", os.path.join(d, "board.kicad_pcb")))

# 4: in the released files, each two-pad R and C on top sits where the CPL says: midway between its two paste pads
from shapely.geometry import Point  # noqa: E402
gz = L.unzip(os.path.join(CTL_OUT, ZIP), W("control_z"))
paste = L.gshape(L.find(gz, r"F_Paste"))
cents = [q.centroid for q in getattr(paste, "geoms", [paste])]
edge = L.gshape(L.find(gz, r"Edge_Cuts")).bounds
cp = L.cpl(os.path.join(CTL_OUT, f"{L.STEM}_CPL.csv"))
checked, bad = 0, []
for ref, (x, y, side, rot) in cp.items():
    if side != "Top" or not re.match(r"^[RC]\d+$", ref):
        continue
    near = sorted(cents, key=lambda c: c.distance(Point(x, y)))[:2]
    mid = ((near[0].x + near[1].x) / 2, (near[0].y + near[1].y) / 2)
    checked += 1
    if abs(mid[0] - x) > 0.03 or abs(mid[1] - y) > 0.03:
        bad.append([ref, [x, y], [round(mid[0], 3), round(mid[1], 3)]])
L.emit("origin_cpl_on_pads", checked=checked, off=bad, outline_centre=[round((edge[0] + edge[2]) / 2, 4), round((edge[1] + edge[3]) / 2, 4)])

# 4: the same board plotted in KiCad's page frame differs in frame; --align compares it anyway
pf = W("pageframe")
os.makedirs(pf)
subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,F.Paste,F.SilkS,B.SilkS,Edge.Cuts", "--no-protel-ext", "-o", pf + "/", os.path.join(CTL, "board.kicad_pcb")], check=True, capture_output=True)
subprocess.run(["kicad-cli", "pcb", "export", "drill", "--excellon-separate-th", "--excellon-units", "mm", "-o", pf + "/", os.path.join(CTL, "board.kicad_pcb")], check=True, capture_output=True)
c1 = L.pcb("compare-gerbers", pf, os.path.join(CTL_OUT, ZIP), "--work", W("cmp_pf"))
c2 = L.pcb("compare-gerbers", pf, os.path.join(CTL_OUT, ZIP), "--align", "--work", W("cmp_pf2"))
L.emit("frame", page_frame=L.slim(c1), error=c1["data"].get("error"), aligned=L.slim(c2))

# 1: layers deleted from the released set, and a set whose names and X2 attributes are gone
for name, pat in (("gone_fpaste", r"F_Paste"), ("gone_bsilk", r"B_Silk"), ("gone_bmask", r"B_Mask")):
    v = W(name)
    shutil.copytree(gz, v)
    os.remove(L.find(v, pat))
    L.emit("layer_" + name, **golden(v, name, os.path.join(CTL, "board.kicad_pcb")))
v = W("anon")
shutil.copytree(gz, v)
for i, f in enumerate(sorted(os.listdir(v))):
    p = os.path.join(v, f)
    if f.endswith(".gbr") and "Edge" not in f:
        t = "\n".join(ln for ln in open(p).read().splitlines() if not ln.startswith(("%TF", "%TA", "%TO", "%TD", "G04 #@!")))
        open(p, "w").write(t)
        os.rename(p, os.path.join(v, f"layer{i}.gbr"))
L.emit("layer_anon", **golden(v, "anon", os.path.join(CTL, "board.kicad_pcb")))

# 3: every 0.22 mm V3V3, DVDD and VBUS track on F.Cu narrowed to 0.15 mm, then zone, check (waived), gate, release
NARROW = 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() in ("V3V3", "DVDD", "VBUS") and t.GetLayer() == pcbnew.F_Cu and t.GetWidth() > mm(0.2):\n        t.SetWidth(mm(0.15))'
d, g, r = flow("narrow_f", NARROW, rezone=True, waive=True)
L.emit("narrow_f", release=L.slim(r), **golden(os.path.join(r["written"], ZIP), "narrow_f", os.path.join(d, "board.kicad_pcb")) if r.get("written") else {})

# silkscreen: every label's growth raised from 0.02 to 0.08 mm (strokes 0.12 mm wider), art run, released, compared
def grow(d):
    t = open(os.path.join(d, "pcb.toml")).read().replace("grow_mm = 0.02", "grow_mm = 0.08")
    open(os.path.join(d, "pcb.toml"), "w").write(t)
    a = L.pcb("art", "--project", d, "--work", os.path.join(d, "aw"))
    assert a["outcome"] == "done", a


d, g, r = flow("silk_grow", toml=grow)
L.emit("silk_grow", release=L.slim(r), **golden(os.path.join(r["written"], ZIP), "silk_grow", os.path.join(d, "board.kicad_pcb")) if r.get("written") else {})


# --- check
def sev(d, kinds):
    p = os.path.join(d, "board.kicad_pro")
    j = json.load(open(p))
    j.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {}).update({k: "ignore" for k in kinds})
    json.dump(j, open(p, "w"), indent=2)


FAB = ["track_width", "clearance", "hole_size", "via_diameter", "hole_to_hole", "copper_edge_clearance", "hole_clearance", "annular_width", "drill_out_of_range"]
d = L.paddle(work, "pro_ignore")
L.post(os.path.join(d, "board.kicad_pcb"), 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT":\n        t.SetWidth(mm(0.10))')
sev(d, FAB)
c = L.pcb("check", "--project", d, "--work", W("pro_ignore_c"))
L.emit("check_pro_ignore", **L.slim(c), unwaived=[f["item"] for f in c["data"].get("findings", []) if not f["waived"]])

# a project file that ignores unconnected items: pcb check passes an open board; the read-back must stop it
d = L.paddle(work, "pro_open")
L.post(os.path.join(d, "board.kicad_pcb"), 'ts = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT"]\nb.Remove(max(ts, key=lambda t: t.GetLength()))')
sev(d, ["unconnected_items", "track_dangling"])
c = L.pcb("check", "--project", d, "--work", W("pro_open_c"))
g = L.gate(d, W("pro_open_g"))
r = L.release(d, W("pro_open_out"), W("pro_open_r")) if g["outcome"] == "done" else g
L.emit("check_pro_open", check=L.slim(c), gate=L.slim(g), release=L.slim(r), problems=r["data"].get("problems"))

# the board's own stricter rules: a custom rule (VBUS 0.5 mm) and a netclass clearance of 0.3 mm, each against
# KiCad's own DRC of the same board
def kicad_drc(board, out):
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--refill-zones", "-o", out, board], capture_output=True)
    j = json.load(open(out))
    return sum(1 for v in j["violations"] if v["type"] == "clearance")


d = L.paddle(work, "own_dru")
open(os.path.join(d, "board.kicad_dru"), "w").write("(version 1)\n(rule \"vbus 0.5\" (condition \"A.NetName == 'VBUS' || B.NetName == 'VBUS'\") (constraint clearance (min 0.5mm)))\n")
k = kicad_drc(os.path.join(d, "board.kicad_pcb"), W("own_dru.json"))
c = L.pcb("check", "--project", d, "--work", W("own_dru_c"))
L.emit("check_own_dru", kicad_clearance=k, **L.slim(c), clearance_found=sum(f["count"] for f in c["data"].get("findings", []) if f["item"].startswith("clearance")))
d = L.paddle(work, "own_netclass")
p = os.path.join(d, "board.kicad_pro")
j = json.load(open(p))
j["net_settings"]["classes"][0]["clearance"] = 0.3
json.dump(j, open(p, "w"), indent=2)
k = kicad_drc(os.path.join(d, "board.kicad_pcb"), W("own_nc.json"))
c = L.pcb("check", "--project", d, "--work", W("own_nc_c"))
L.emit("check_own_netclass", kicad_clearance=k, **L.slim(c), clearance_found=sum(f["count"] for f in c["data"].get("findings", []) if f["item"].startswith("clearance")))

# 10: a fab rule set for another layer count
d = L.paddle(work, "fab_layers")
L.toml_sub(d, "layers = 2", "layers = 4")
c1 = L.pcb("check", "--project", d, "--work", W("fl1"))
L.toml_sub(d, "layers = 4", "layers = 2")
L.toml_sub(d, 'fab = "jlcpcb-2layer-1.6mm"', 'fab = "jlcpcb-4layer-1.6mm"')
c2 = L.pcb("check", "--project", d, "--work", W("fl2"))
L.emit("check_fab_layers", layers4_fab2=L.slim(c1), layers2_fab4=L.slim(c2))

# 11: U1 pad 5 loses its paste; U1 keeps its windows on pad 57
d = L.paddle(work, "paste5")
L.post(os.path.join(d, "board.kicad_pcb"), 'p = [p for p in b.FindFootprintByReference("U1").Pads() if p.GetNumber() == "5"][0]\nls = p.GetLayerSet(); ls.RemoveLayer(pcbnew.F_Paste); p.SetLayerSet(ls)')
c = L.pcb("check", "--project", d, "--work", W("paste5_c"))
L.emit("check_paste_pad5", **L.slim(c), paste=[f["item"] for f in c["data"].get("findings", []) if f["check"] == "paste"])

# 12: XOUT at 2 A, every XOUT track 1.0 mm, plus one 0.15 mm arc
ARC = '''
for t in b.GetTracks():
    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT":
        t.SetWidth(mm(1.0))
t0 = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT"][0]
s = t0.GetStart()
a = pcbnew.PCB_ARC(b)
a.SetStart(s); a.SetMid(pcbnew.VECTOR2I(s.x + mm(0.3), s.y + mm(0.3))); a.SetEnd(pcbnew.VECTOR2I(s.x + mm(0.6), s.y))
a.SetWidth(mm(0.15)); a.SetLayer(pcbnew.F_Cu); a.SetNet(t0.GetNet()); b.Add(a)
'''
d = L.paddle(work, "arc")
L.post(os.path.join(d, "board.kicad_pcb"), ARC)
L.toml_add(d, "[nets.XOUT]\ncurrent_a = 2.0")
c = L.pcb("check", "--project", d, "--work", W("arc_c"))
L.emit("check_arc", **L.slim(c), wc=[f["message"] for f in c["data"].get("findings", []) if f["check"] == "width-current"])

# 26: a GND via 0.5/0.3 mm (0.1 mm ring) beside a GND pad; the 0.5 mm label's finding (waived in the fixture)
d = L.paddle(work, "ring")
L.post(os.path.join(d, "board.kicad_pcb"), 'v = pcbnew.PCB_VIA(b)\nt = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "GND"][0]\nv.SetPosition(t.GetPosition()); v.SetWidth(mm(0.5)); v.SetDrill(mm(0.3)); v.SetNet(t.GetNet()); b.Remove(t); b.Add(v)')
c = L.pcb("check", "--project", d, "--work", W("ring_c"))
L.emit("check_ring_text", **L.slim(c), ring=[f["item"] for f in c["data"].get("findings", []) if f["check"] == "ring"],
       text=[(f["item"], bool(f["waived"])) for f in c["data"].get("findings", []) if f["check"] == "silk" and f["item"].startswith("text")])

# 22: a dfm waiver in pcb.toml, and a drc waiver whose max is exceeded
d = L.paddle(work, "waivers")
L.toml_add(d, '[[waiver]]\ncheck = "dfm"\nitem = "gap F.Cu"\nmax = 1\nwhy = "probe"')
L.toml_sub(d, "max = 28", "max = 20")
c = L.pcb("check", "--project", d, "--work", W("waivers_c"))
L.emit("check_waivers", **L.slim(c), wmsg=c["wmsg"])

# --- gate
d = L.paddle(work, "gate_pro")
L.gate(d, W("gp_g"))
s0 = L.pcb("gate", "status", "--project", d)
sev(d, ["silk_overlap"])
s1 = L.pcb("gate", "status", "--project", d)
d2 = L.paddle(work, "gate_dru")
L.gate(d2, W("gd_g"))
open(os.path.join(d2, "board.kicad_dru"), "w").write("(version 1)\n(rule \"x\" (constraint clearance (min 0.01mm)))\n")
s2 = L.pcb("gate", "status", "--project", d2)
r2 = L.release(d2, W("gate_dru_out"), W("gate_dru_r"))
L.emit("gate_inputs", fresh_before=[x["fresh"] for x in s0["data"].get("gates", [])], fresh_after_pro=[x["fresh"] for x in s1["data"].get("gates", [])],
       fresh_after_new_dru=[x["fresh"] for x in s2["data"].get("gates", [])], release_after_new_dru=L.slim(r2))

# 19: a header written with spaces; comment lines before, inside and after the gate table kept when passed again
d = L.paddle(work, "gate_text")
L.gate(d, W("gt_g1"))
t = open(os.path.join(d, "pcb.toml")).read()
t = t.replace("[gates.layout]", "# before the gate\n[ gates.layout ]\n# inside the gate") + "\n# after the gate\n"
open(os.path.join(d, "pcb.toml"), "w").write(t)
s = L.pcb("gate", "status", "--project", d)
g2 = L.gate(d, W("gt_g2"))
t2 = open(os.path.join(d, "pcb.toml")).read()
L.emit("gate_text", fresh=[x["fresh"] for x in s["data"].get("gates", [])], second=L.slim(g2),
       kept={k: k in t2 for k in ("# before the gate", "# inside the gate", "# after the gate")}, gate_tables=len(re.findall(r"^\[ ?gates\.layout ?\]", t2, re.M)))

# a waiver whose why is a multi-line string holding a line shaped like a gate header: the lines after it
# (check, item, max) drop out of the gate's hash
d = L.paddle(work, "gate_multiline")
L.toml_add(d, '[[waiver]]\nwhy = """probe\n[gates.zz]\n"""\ncheck = "drc"\nitem = "silk_overlap <no net>"\nmax = 9')
g = L.gate(d, W("gm_g"))
L.toml_sub(d, "max = 9", "max = 400")
s = L.pcb("gate", "status", "--project", d)
L.emit("gate_multiline", gate=L.slim(g), fresh_after_max_400=[x["fresh"] for x in s["data"].get("gates", [])])

# --- release
# 9: a rename onto a reference the board has; a swap of two renamed references is allowed
d = L.paddle(work, "rename")
L.toml_sub(d, 'R_A = "R12"', 'R_A = "R11"')
g = L.gate(d, W("rn_g"))
r = L.release(d, W("rename_out"), W("rename_r"))
d2 = L.paddle(work, "rename_swap")
L.toml_sub(d2, 'R_A = "R12", R_B = "R13"', 'R_A = "R_B", R_B = "R_A"')
g2 = L.gate(d2, W("rs_g"))
r2 = L.release(d2, W("swap_out"), W("swap_r"))
sw = L.cpl(os.path.join(r2["written"], f"{L.STEM}_CPL.csv")) if r2.get("written") and os.path.isdir(r2["written"]) else {}
L.emit("release_rename", onto_existing=L.slim(r), swap=L.slim(r2), swap_rows={k: sw[k][:2] for k in ("R_A", "R_B") if k in sw})

# 18: bottom-side assembly allowed: the release warns about bottom rotations
FLIP = 'f = b.FindFootprintByReference("C2")\nf.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)'
d, g, r = flow("bottom", FLIP, toml=lambda d: L.toml_sub(d, 'machine_sides = ["top"]', 'machine_sides = ["top", "bottom"]'), rezone=True, waive=True)
L.emit("release_bottom", gate=L.slim(g), release=L.slim(r), problems=r["data"].get("problems"), bottom_parts=r["data"].get("bottom_parts"),
       has_bpaste="B.Paste" in (r["data"].get("gerber_layers") or []))

# 25: the version raised in pcb.toml without running pcb art; a label moved without pcb art; a paste rule dropped
# without pcb paste. Each released set is compared with the control release (same files means the change is not on
# the board)
def raise_version(d):
    L.toml_sub(d, 'version = "1.0.0"', 'version = "1.0.1"')


def move_label(d):
    L.toml_sub(d, "at = [-6.2, 15.95]", "at = [-6.2, 10.0]")


def drop_paste(d):
    L.toml_sub(d, '[[paste]]\npad = "U1.57"\nwindows = [2, 2]\nsize_mm = 1.25\nweb_mm = 0.35\n', "")


for name, fn, zipname in (("stale_version", raise_version, "paddle-keyer_v1.0.1_gerbers.zip"), ("stale_label", move_label, ZIP), ("stale_paste", drop_paste, ZIP)):
    d, g, r = flow(name, toml=fn)
    c = L.pcb("compare-gerbers", os.path.join(r["written"], zipname), os.path.join(CTL_OUT, ZIP), "--work", W("cmp_" + name)) if r.get("written") else {"data": {}}
    L.emit(name, gate=L.slim(g), release=L.slim(r), same_as_control=c.get("outcome") == "done",
           differing={k: len(v.get("unexplained", [])) for k, v in c["data"].get("layers", {}).items() if v.get("unexplained")})

# stale zone fill: an NPTH hole (1.0 mm) added inside the GND pour after pcb zone. pcb check refills a copy, so it
# sees a clear pour; release plots the stored fill, which runs across the hole
HOLE = '''
x, y = 21.1526, 21.234
f = pcbnew.FOOTPRINT(b)
f.SetReference("H9"); f.SetValue("hole"); f.Reference().SetVisible(False); f.Reference().SetLayer(pcbnew.F_Fab)
f.SetPosition(V(x, y))
p = pcbnew.PAD(f)
p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
p.SetSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0))); p.SetDrillSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
p.SetLayerSet(pcbnew.PAD.UnplatedHoleMask())
f.Add(p); p.SetPosition(V(x, y))
b.Add(f)
'''
d = L.paddle(work, "stale_fill")
b = os.path.join(d, "board.kicad_pcb")
L.post(b, HOLE)
c = L.pcb("check", "--project", d, "--work", W("sf_c"))
subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "-o", W("sf_stored.json"), b], capture_output=True)
stored = sum(1 for v in json.load(open(W("sf_stored.json")))["violations"] if v["type"] == "hole_clearance")
g = L.gate(d, W("sf_g"))
r = L.release(d, W("stale_fill_out"), W("sf_r")) if g["outcome"] == "done" else g
cu = {}
if r.get("written"):
    z = L.unzip(os.path.join(r["written"], ZIP), W("sf_z"))
    cx, cy = L.pyq(b, 'c = b.GetBoardEdgesBoundingBox().GetCenter(); print(json.dumps([mm(c.x), mm(c.y)]))')
    hole = Point(21.1526 - cx, cy - 21.234).buffer(0.5)
    for lay in ("F_Cu", "B_Cu"):
        cu[lay] = round(L.gshape(L.find(z, lay)).intersection(hole).area / hole.area, 3)
L.emit("stale_fill", check=L.slim(c), check_unwaived=[f["item"] for f in c["data"].get("findings", []) if not f["waived"]], stored_fill_hole_clearance=stored,
       base_hole_clearance_waived=2, gate=L.slim(g), release=L.slim(r), problems=r["data"].get("problems"), hole_covered_by_copper=cu)

# 13: pcb paste and pcb art against their output schemas
d = L.paddle(work, "contracts")
pa = L.pcb("paste", "--project", d, "--work", W("ct_p"))
ar = L.pcb("art", "--project", d, "--work", W("ct_a"))
L.emit("contracts", paste=L.slim(pa), art=L.slim(ar))
