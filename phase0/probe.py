"""Phase 0 probe (tools/pcb/DESIGN.md): show that KiCad 7's pcbnew module and kicad-cli do what `pcb` relies on.

Builds a 30 x 20 mm, 4-layer test board with four 0603 pads pairs, nets A, B and GND, one locked track on A,
then runs:
  1. save and reload;
  2. Specctra DSN export, checking the locked track goes out as protected wiring;
  3. Freerouting headless on the DSN, then SES import;
  4. zone fill (a GND pour on B.Cu and a plane on In1.Cu);
  5. DRC report;
  6. kicad-cli Gerbers, drill, position file and PDF.
Prints one JSON object with a result per step.
Usage: python3 probe.py workdir freerouting.jar
"""
import json
import os
import re
import subprocess
import sys

import pcbnew

work, frjar = sys.argv[1], sys.argv[2]
os.makedirs(work, exist_ok=True)
res = {}
MM = pcbnew.FromMM


def pt(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


b = pcbnew.BOARD()
b.SetCopperLayerCount(4)
for x0, y0, x1, y1 in ((0, 0, 30, 0), (30, 0, 30, 20), (30, 20, 0, 20), (0, 20, 0, 0)):
    s = pcbnew.PCB_SHAPE(b)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pt(x0, y0)); s.SetEnd(pt(x1, y1))
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1))
    b.Add(s)
nets = {}
for n in ("A", "B", "GND"):
    ni = pcbnew.NETINFO_ITEM(b, n)
    b.Add(ni)
    nets[n] = ni


def resistor(ref, x, y, n1, n2):
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference(ref)
    fp.SetValue("1k")
    fp.SetFPID(pcbnew.LIB_ID("probe", "R0603"))
    fp.SetPosition(pt(x, y))
    for num, dx, net in (("1", -0.8, n1), ("2", 0.8, n2)):
        p = pcbnew.PAD(fp)
        p.SetNumber(num)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetSize(pcbnew.VECTOR2I(MM(0.8), MM(0.9)))
        ls = pcbnew.LSET()
        for L in (pcbnew.F_Cu, pcbnew.F_Paste, pcbnew.F_Mask):
            ls.AddLayer(L)
        p.SetLayerSet(ls)
        p.SetNet(nets[net])
        p.SetPos0(pt(dx, 0))           # KiCad 7: position inside the footprint
        p.SetPosition(pt(x + dx, y))
        fp.Add(p)
    b.Add(fp)
    return fp


resistor("R1", 6, 6, "A", "GND")
resistor("R2", 24, 6, "A", "GND")
resistor("R3", 6, 14, "B", "GND")
resistor("R4", 24, 14, "B", "GND")
# one locked track on A, R1.1 to the middle of the board (the router must keep it and finish the rest)
t = pcbnew.PCB_TRACK(b)
t.SetStart(pt(5.2, 6)); t.SetEnd(pt(5.2, 10)); t.SetWidth(MM(0.25)); t.SetLayer(pcbnew.F_Cu); t.SetNet(nets["A"])
t.SetLocked(True)
b.Add(t)
# zones: GND on B.Cu (pour) and In1.Cu (plane)
for layer in (pcbnew.B_Cu, pcbnew.In1_Cu):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(nets["GND"])
    ol = z.Outline()
    ol.NewOutline()
    for x, y in ((0.5, 0.5), (29.5, 0.5), (29.5, 19.5), (0.5, 19.5)):
        ol.Append(MM(x), MM(y))
    z.SetLocalClearance(MM(0.3))
    b.Add(z)
path = os.path.join(work, "probe.kicad_pcb")
b.Save(path)
b2 = pcbnew.LoadBoard(path)
res["1_save_reload"] = {"ok": len(b2.GetFootprints()) == 4 and len(b2.GetTracks()) == 1,
                        "footprints": len(b2.GetFootprints()), "tracks": len(b2.GetTracks())}

dsn = os.path.join(work, "probe.dsn")
ok = pcbnew.ExportSpecctraDSN(b2, dsn)
txt = open(dsn).read() if ok else ""
wiring = txt[txt.find("(wiring"):] if "(wiring" in txt else ""
locked_fixed = "(type fix)" in wiring or "(type protect)" in wiring
res["2_dsn_export"] = {"ok": bool(ok) and locked_fixed, "exported": bool(ok),
                       "locked_track_fixed": locked_fixed,
                       "wiring_excerpt": re.sub(r"\s+", " ", wiring[:300])}

ses = os.path.join(work, "probe.ses")
r = subprocess.run(["xvfb-run", "-a", "java", "-jar", frjar, "-de", dsn, "-do", ses, "-mp", "20"],
                   capture_output=True, text=True, timeout=600)
ok_ses = os.path.exists(ses)
# KiCad 7's ImportSpecctraSES only imports into the GUI's open board, so the session is read here (pcb does this in Rust).
# Specctra units: (resolution um N) -> value / N um; KiCad's DSN export negates y.
st = open(ses).read() if ok_ses else ""
rm = re.search(r"\(resolution\s+(\w+)\s+(\d+)\)", st)
scale = (1000.0 if rm and rm.group(1) == "mm" else 1.0) / float(rm.group(2)) if rm else 1.0   # -> um
layers = {b2.GetLayerName(l): l for l in range(pcbnew.PCB_LAYER_ID_COUNT) if pcbnew.IsCopperLayer(l)}
added_t = added_v = 0
for blk in re.split(r"\(net ", st.split("(network_out", 1)[1])[1:] if "(network_out" in st else []:
    name = blk.split(None, 1)[0].strip('"')
    net = b2.FindNet(name)
    for wm in re.finditer(r"\(wire\s*\(path (\S+) ([\d.]+)((?:\s+-?[\d.]+)+)\s*\)", blk):
        vals = [float(v) * scale for v in wm.group(3).split()]
        pts = [(vals[i], -vals[i + 1]) for i in range(0, len(vals), 2)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            tr = pcbnew.PCB_TRACK(b2)
            tr.SetStart(pcbnew.VECTOR2I(int(x0 * 1000), int(y0 * 1000)))
            tr.SetEnd(pcbnew.VECTOR2I(int(x1 * 1000), int(y1 * 1000)))
            tr.SetWidth(int(float(wm.group(2)) * scale * 1000))
            tr.SetLayer(layers.get(wm.group(1), pcbnew.F_Cu))
            tr.SetNet(net)
            b2.Add(tr)
            added_t += 1
    for vm in re.finditer(r'\(via "[^"]+" (-?[\d.]+) (-?[\d.]+)', blk):
        v = pcbnew.PCB_VIA(b2)
        v.SetPosition(pcbnew.VECTOR2I(int(float(vm.group(1)) * scale * 1000), int(-float(vm.group(2)) * scale * 1000)))
        v.SetDrill(MM(0.3)); v.SetWidth(MM(0.6)); v.SetNet(net)
        b2.Add(v)
        added_v += 1
res["3_route_import"] = {"ok": ok_ses and added_t > 0, "ses": ok_ses, "tracks_added": added_t, "vias_added": added_v,
                         "freerouting_rc": r.returncode, "locked_kept": len([tr for tr in b2.GetTracks() if tr.IsLocked()])}

filler = pcbnew.ZONE_FILLER(b2)
zones = b2.Zones()
filler.Fill(zones)
filled = [z.IsFilled() for z in zones]
res["4_zone_fill"] = {"ok": all(filled) and len(filled) == 2, "zones_filled": filled}
b2.Save(path)

rpt = os.path.join(work, "drc.rpt")
okd = pcbnew.WriteDRCReport(b2, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
rtxt = open(rpt).read() if os.path.exists(rpt) else ""
m = re.search(r"\*\* Found (\d+) DRC violations", rtxt)
u = re.search(r"\*\* Found (\d+) unconnected pads", rtxt)
res["5_drc"] = {"ok": bool(okd) and m is not None, "violations": int(m.group(1)) if m else None,
                "unconnected": int(u.group(1)) if u else None}

out = {}
for name, cmd in (("gerbers", ["kicad-cli", "pcb", "export", "gerbers", "-o", os.path.join(work, "gbr") + "/", path]),
                  ("drill", ["kicad-cli", "pcb", "export", "drill", "-o", os.path.join(work, "gbr") + "/", path]),
                  ("pos", ["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "-o",
                           os.path.join(work, "pos.csv"), path]),
                  ("pdf", ["kicad-cli", "pcb", "export", "pdf", "--layers", "F.Cu,F.SilkS,Edge.Cuts", "-o",
                           os.path.join(work, "top.pdf"), path])):
    os.makedirs(os.path.join(work, "gbr"), exist_ok=True)
    rr = subprocess.run(cmd, capture_output=True, text=True)
    out[name] = rr.returncode == 0
files = sorted(os.listdir(os.path.join(work, "gbr")))
res["6_kicad_cli"] = {"ok": all(out.values()) and any("In1" in f for f in files), "steps": out, "files": files}
res["ok"] = all(v["ok"] for k, v in res.items() if k != "ok")
print(json.dumps(res, indent=1))
