"""pcb release and pcb gate on the paddle-keyer board: refusals (P1, P2), the gate's inputs, BOM and CPL (turned and
bottom-side parts with offsets against pcbnew's own footprint transform, renames, DNP and hand fit), checksums,
reproducibility, a rejected release's folder, and the read-back's misses (a thin track, thin silkscreen, copper at a
cut-out, copper off the board).

Usage: python3 release15.py workdir
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r15lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
STEM = "paddle-keyer_v1.0.0"


def W(*p):
    return os.path.join(work, *p)


def cpl(out):
    # a rejected release moves aside to <out>.rejected since review 15's closure (17) (designer's edit)
    if not os.path.exists(out) and os.path.exists(out + ".rejected"):
        out = out + ".rejected"
    return {r["Designator"]: (float(r["Mid X"][:-2]), float(r["Mid Y"][:-2]), r["Layer"], float(r["Rotation"])) for r in L.rows(os.path.join(out, f"{STEM}_CPL.csv"))}


def bom(out):
    return [(r["Designator"], r["LCSC Part #"]) for r in L.rows(os.path.join(out, f"{STEM}_BOM.csv"))]


def gate(d, tag):
    return L.pcb("gate", "pass", "layout", "--project", d, "--work", W(tag + "_gw"))


def force_gate(d, tag):
    """Waive every unwaived pcb check finding (the probe is about release, not the board), then pass the gate."""
    c = L.pcb("check", "--project", d, "--work", W(tag + "_fc"))
    for f in c["data"].get("findings", []):
        if not f["waived"]:
            L.toml_add(d, f'[[waiver]]\ncheck = "{f["check"]}"\nitem = "{f["item"]}"\nmax = 500\nwhy = "probe"\n')
    return gate(d, tag)


def release(d, tag):
    return L.pcb("release", "--project", d, "-o", W(tag + "_out"), "--work", W(tag + "_rw"))


# --- refusals: P1 and P2
d = L.paddle(work, "p1")
r = release(d, "p1")
L.emit("p1_no_gate", **L.slim(r), out_exists=os.path.exists(W("p1_out")))

d = L.paddle(work, "p2")
g = gate(d, "p2")
L.post(os.path.join(d, "board.kicad_pcb"), 'b.FindFootprintByReference("R11").SetValue("4.7k")')
s = L.pcb("gate", "status", "--project", d)
r = release(d, "p2")
L.emit("p2_value_changed", gate=L.slim(g), status=[(x["name"], x["fresh"]) for x in s["data"].get("gates", [])], **L.slim(r))

# --- the gate's inputs: files beside the board that change what pcb check sees
for name, what in (("pro_severity", "pro"), ("dru_beside", "dru")):
    d = L.paddle(work, name)
    g = gate(d, name)
    if what == "pro":
        p = os.path.join(d, "board.kicad_pro")
        t = open(p).read()
        # turn KiCad's clearance and track-width checks off: the fab's own rules then report nothing
        t2 = re.sub(r'"rule_severities"\s*:\s*\{', '"rule_severities": {"clearance": "ignore", "track_width": "ignore", ', t, count=1)
        if t2 == t:
            t2 = t.replace('"design_settings": {', '"design_settings": {"rule_severities": {"clearance": "ignore", "track_width": "ignore"}, ', 1)
        open(p, "w").write(t2)
    else:
        open(os.path.join(d, "board.kicad_dru"), "w").write('(version 1)\n(rule "loose" (constraint clearance (min 0.01mm)))\n')
    s = L.pcb("gate", "status", "--project", d)
    L.emit("gate_" + name, gate=L.slim(g), fresh=[x["fresh"] for x in s["data"].get("gates", [])], files=s["data"].get("files"))

# the severity file defeats the fab's rules: a 0.1 mm track passes pcb check once track_width is "ignore"
def severities(d, **kw):
    import json
    p = os.path.join(d, "board.kicad_pro")
    j = json.load(open(p))
    j.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {}).update(kw)
    json.dump(j, open(p, "w"), indent=2)


d = L.paddle(work, "pro_hides")
L.post(os.path.join(d, "board.kicad_pcb"), 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT":\n        t.SetWidth(mm(0.1))')
c0 = L.pcb("check", "--project", d, "--work", W("pro_hides_c0"))
severities(d, track_width="ignore")
c1 = L.pcb("check", "--project", d, "--work", W("pro_hides_c1"))
L.emit("check_pro_hides", before=[f["item"] for f in c0["data"].get("findings", []) if not f["waived"]], after=[f["item"] for f in c1["data"].get("findings", []) if not f["waived"]],
       outcome_after=c1["outcome"])

# gate table spelt with spaces, which TOML allows
d = L.paddle(work, "gate_spaces")
g = gate(d, "gs1")
L.toml_sub(d, "[gates.layout]", "[ gates.layout ]")
s = L.pcb("gate", "status", "--project", d)
g2 = gate(d, "gs2")
L.emit("gate_spaces", status=L.slim(s), fresh=[x["fresh"] for x in s["data"].get("gates", [])], second_pass=L.slim(g2))

# a comment after the gate's table: lost when the gate is passed again
d = L.paddle(work, "gate_comment")
g = gate(d, "gc1")
L.toml_add(d, "# owner: keep this note\n[decisions.keep]\ntext = \"x\"\ndate = \"2026-11-01\"")
t0 = open(os.path.join(d, "pcb.toml")).read()
# move the gate table to just before the comment
t1 = re.sub(r"\n\[gates\.layout\][^\[]*", "\n", t0)
gt = re.search(r"\[gates\.layout\][^\[]*", t0).group(0)
t1 = t1.replace("# owner: keep this note", gt.strip() + "\n# owner: keep this note")
open(os.path.join(d, "pcb.toml"), "w").write(t1)
g2 = gate(d, "gc2")
L.emit("gate_comment", second_pass=L.slim(g2), comment_kept="# owner: keep this note" in open(os.path.join(d, "pcb.toml")).read())

# --- BOM and CPL: turned and bottom-side parts with offsets, against where pcbnew puts the offset point
ORACLE = '''
import math
def where(ref, ox, oy, flip=False, turn=None):
    f = b.FindFootprintByReference(ref)
    if turn is not None:
        f.SetOrientationDegrees(turn)
    if flip:
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    p = pcbnew.PAD(f)
    p.SetNumber("probe")
    p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    f.Add(p)
    p.SetFPRelativePosition(V(ox, -oy))
    q = p.GetPosition()
    out = [pcbnew.ToMM(q.x), pcbnew.ToMM(q.y), f.GetOrientationDegrees(), f.IsFlipped()]
    f.Remove(p)
    return out
bb = b.GetBoardEdgesBoundingBox()
cx, cy = pcbnew.ToMM(bb.GetCenter().x), pcbnew.ToMM(bb.GetCenter().y)
res = {"J2": where("J2", -0.1, 0.2, flip=True, turn=0), "J1": where("J1", 0, 0.125, turn=30), "C2": where("C2", 0.3, -0.2, flip=True, turn=30), "centre": [cx, cy],
       "C2_lcsc": b.FindFootprintByReference("C2").GetFieldText("LCSC")}
print("ORACLE", json.dumps(res))
'''
d = L.paddle(work, "cpl")
o = L.post(os.path.join(d, "board.kicad_pcb"), "import json\n" + ORACLE)
orc = __import__("json").loads(o.split("ORACLE ", 1)[1].splitlines()[0])
L.toml_sub(d, 'machine_sides = ["top"]', 'machine_sides = ["top", "bottom"]')
L.toml_sub(d, "cpl_offset_mm = [-0.1, 0]", "cpl_offset_mm = [-0.1, 0.2]")
L.toml_add(d, f'[parts.{orc["C2_lcsc"]}]\ncpl_offset_mm = [0.3, -0.2]\nsource = "probe"\n')
g = force_gate(d, "cpl")
r = release(d, "cpl") if g["outcome"] == "done" else g
got = cpl(W("cpl_out")) if os.path.exists(W("cpl_out", f"{STEM}_CPL.csv")) or os.path.exists(W("cpl_out.rejected", f"{STEM}_CPL.csv")) else {}
cx, cy = orc["centre"]
want = {k: [round(orc[k][0] - cx, 3), round(cy - orc[k][1], 3)] for k in ("J2", "J1", "C2")}
# KiCad's own position file for the same board, for the rotation it gives a bottom part
pos = W("cpl_pos.csv")
subprocess.run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", pos, os.path.join(d, "board.kicad_pcb")], capture_output=True)
kpos = {r["Ref"]: (float(r["PosX"]), float(r["PosY"]), float(r["Rot"]), r["Side"]) for r in L.rows(pos)} if os.path.exists(pos) else {}
L.emit("cpl_offsets", release=L.slim(r), gate=L.slim(g) if g["outcome"] != "done" else "done",
       J2_bottom=dict(want=want["J2"], got=got.get("J2", [None, None])[:2], layer=got.get("J2", [0, 0, None])[2], rot=got.get("J2", [0, 0, 0, None])[3], kicad_pos_rot=kpos.get("J2", [0, 0, None])[2], board_rot=orc["J2"][2]),
       J1_turned=dict(want=want["J1"], got=got.get("J1", [None, None])[:2], rot=got.get("J1", [0, 0, 0, None])[3]),
       C2_bottom=dict(want=want["C2"], got=got.get("C2", [None, None])[:2], rot=got.get("C2", [0, 0, 0, None])[3], kicad_pos_rot=kpos.get("C2", [0, 0, None])[2], board_rot=orc["C2"][2]))

# --- renames, DNP, hand fit, exclusion
d = L.paddle(work, "rename")
L.toml_sub(d, 'designators = { R_A = "R12"', 'designators = { R_A = "R11"')
g = gate(d, "rename")
r = release(d, "rename") if g["outcome"] == "done" else g
c = cpl(W("rename_out")) if os.path.exists(W("rename_out", f"{STEM}_CPL.csv")) else {}
n_r11 = sum(1 for k in open(W("rename_out", f"{STEM}_CPL.csv")).read().splitlines() if k.startswith("R11,")) if c else None
L.emit("rename_collision", **L.slim(r), r11_rows_in_cpl=n_r11)

d = L.paddle(work, "dnp")
L.post(os.path.join(d, "board.kicad_pcb"), 'b.FindFootprintByReference("R14").SetDNP(True)\nb.FindFootprintByReference("R15").SetExcludedFromBOM(True)\nb.FindFootprintByReference("R16").SetExcludedFromPosFiles(True)')
L.toml_sub(d, "[assembly]\n", '[assembly]\nhand_fit = ["R17"]\n')
g = gate(d, "dnp")
r = release(d, "dnp") if g["outcome"] == "done" else g
c = cpl(W("dnp_out")) if os.path.exists(W("dnp_out", f"{STEM}_CPL.csv")) else {}
bm = [x for x, _ in bom(W("dnp_out"))] if c else []
L.emit("dnp_handfit", **L.slim(r), in_cpl=[k for k in ("R14", "R15", "R16", "R17") if k in c], in_bom=[k for k in ("R14", "R15", "R16", "R17") if any(k in x.split(",") for x in bm)],
       left_out=r["data"].get("left_out", [])[-6:])

# --- checksums, reproducibility, a release beside an older one
d = L.paddle(work, "repro")
g = gate(d, "repro")
r1 = release(d, "repro1")
r2 = release(d, "repro2")
same = {}
for f in (f"{STEM}_BOM.csv", f"{STEM}_CPL.csv"):
    same[f] = open(W("repro1_out", f), "rb").read() == open(W("repro2_out", f), "rb").read()
z1, z2 = zipfile.ZipFile(W("repro1_out", f"{STEM}_gerbers.zip")), zipfile.ZipFile(W("repro2_out", f"{STEM}_gerbers.zip"))
diff_lines = {}
for n in z1.namelist():
    a, b_ = z1.read(n).decode(errors="replace").splitlines(), z2.read(n).decode(errors="replace").splitlines()
    dl = [x for x, y in zip(a, b_) if x != y] + (["<length differs>"] if len(a) != len(b_) else [])
    if dl:
        diff_lines[n] = sorted({re.sub(r"[\d:T+\-]+", "#", x)[:60] for x in dl})
sums_ok = all(hashlib.sha256(open(W("repro1_out", ln.split("  ")[1]), "rb").read()).hexdigest() == ln.split("  ")[0] for ln in open(W("repro1_out", "CHECKSUMS.txt")).read().splitlines())
L.emit("repro", r1=L.slim(r1), r2=L.slim(r2), csv_same=same, zip_names_same=z1.namelist() == z2.namelist(), zip_diff_lines=diff_lines, checksums_ok=sums_ok)

# --- the read-back: what it misses on the final files
def readback(name, code, waivers, zone=True):
    d = L.paddle(work, name)
    if code:
        L.post(os.path.join(d, "board.kicad_pcb"), code)
    if zone:
        z = L.pcb("zone", "--project", d, "--work", W(name + "_zw"))
    c = L.pcb("check", "--project", d, "--work", W(name + "_cw"))
    items = sorted({f["item"] for f in c["data"].get("findings", []) if not f["waived"]})
    for it in items:
        L.toml_add(d, f'[[waiver]]\ncheck = "drc"\nitem = "{it}"\nmax = 500\nwhy = "probe: the read-back must see this on its own"\n')
    for w in waivers:
        L.toml_add(d, w)
    g = gate(d, name)
    r = release(d, name) if g["outcome"] == "done" else g
    v = r["data"].get("verify", {})
    return dict(check_found=items, release=L.slim(r), problems=r["data"].get("problems", [])[:6], dfm=[(f["rule"], f["layer"], f["detail"][:60]) for f in v.get("dfm", [])][:6],
                opens=v.get("opens"), shorts=v.get("shorts"))


# a 0.10 mm track between two pads (XOUT), its DRC finding waived: the Gerbers carry 0.10 mm copper
L.emit("rb_thin_track", **readback("rb_thin_track", 'for t in b.GetTracks():\n    if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "XOUT":\n        t.SetWidth(mm(0.1))', []))
# silkscreen lines 0.12 mm and 0.10 mm wide (GUIDELINES: 0.15 mm), in the board's free silk area on the back
SILK = '''
for w, y in ((0.12, 30.0), (0.10, 31.0), (0.07, 32.0)):
    s = pcbnew.PCB_SHAPE(b)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(24.0, y)); s.SetEnd(V(27.0, y))
    s.SetWidth(mm(w)); s.SetLayer(pcbnew.F_SilkS)
    b.Add(s)
'''
L.emit("rb_thin_silk", **readback("rb_thin_silk", SILK, []))
# a 1 mm round cut-out in the board, 0.1 mm from a GND pour edge after zone, and copper (a no-net square) off the board
CUT = '''
c = pcbnew.PCB_SHAPE(b)
c.SetShape(pcbnew.SHAPE_T_CIRCLE)
c.SetCenter(V(27.5, 45.0)); c.SetEnd(V(28.0, 45.0))
c.SetLayer(pcbnew.Edge_Cuts); c.SetWidth(mm(0.05))
b.Add(c)
t = pcbnew.PCB_TRACK(b)
t.SetStart(V(26.9, 44.0)); t.SetEnd(V(26.9, 46.0)); t.SetWidth(mm(0.2)); t.SetLayer(pcbnew.B_Cu); t.SetNet(net("GND"))
b.Add(t)
'''
L.emit("rb_cutout", **readback("rb_cutout", CUT, [], zone=False))
OFF = '''
s = pcbnew.PCB_SHAPE(b)
s.SetShape(pcbnew.SHAPE_T_RECT)
s.SetStart(V(37.0, 50.0)); s.SetEnd(V(38.0, 51.0))
s.SetFilled(True); s.SetLayer(pcbnew.F_Cu); s.SetNet(net("GND"))
b.Add(s)
'''
L.emit("rb_off_board", **readback("rb_off_board", OFF, [], zone=False))
# a short in the Gerbers alone: a GND track over a V3V3 pad, DRC waived; the release must reject and say short
SHORT = '''
f = b.FindFootprintByReference("C2")
p = [p for p in f.Pads() if p.GetNetname() != "GND"][0]
q = p.GetPosition()
t = pcbnew.PCB_TRACK(b)
t.SetStart(q); t.SetEnd(pcbnew.VECTOR2I(q.x + mm(0.8), q.y)); t.SetWidth(mm(0.2)); t.SetLayer(pcbnew.F_Cu); t.SetNet(net("GND"))
b.Add(t)
'''
res = readback("rb_short", SHORT, [], zone=False)
files = sorted(os.listdir(W("rb_short_out"))) if os.path.isdir(W("rb_short_out")) else []
L.emit("rb_short_folder", **res, files=files)
