"""Review 10: own reproductions of review 9 findings 3, 5, 6, 7 and 9.
usage: python3 closure_probes.py WORKDIR"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew  # noqa: E402
from lib import PCB, B, blocks, edit  # noqa: E402

R9 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "r09")
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib")
work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)


def show(name, d, **kw):
    print(json.dumps({"case": name, "outcome": d.get("outcome"), "code": (d.get("error") or {}).get("code"), "msg": ((d.get("error") or {}).get("message") or "")[:150],
                      "regressions": (d.get("data") or {}).get("regressions"), **kw}))


# 3 and 7: a GND stitching via and a GND track fed only through a B.Cu pour
g = B()
g.fp("G1", 10, 10, "GND", tht=True)
g.fp("G2", 30, 10, "GND")          # F.Cu pad, fed by a via to the B.Cu pour
g.trk(30, 10, 30, 14, "GND", w=0.3)
g.via(30, 14, "GND")
g.via(20, 25, "GND")               # stitching via on its own
g.trk(25, 30, 35, 30, "GND", w=0.3, layer=pcbnew.B_Cu)  # B.Cu track inside the pour, joined only by the fill
g.zone("GND", [pcbnew.B_Cu], (2, 2, 45, 40))
p = g.save(os.path.join(work, "stitch.kicad_pcb"), fill=True)
show("move_stitching_via", edit(p, [{"op": "move_via", "net": "GND", "at": [20, 25], "to": [22, 26]}], os.path.join(work, "s1.kicad_pcb"), os.path.join(work, "s1w")))
show("move_feed_via", edit(p, [{"op": "move_via", "net": "GND", "at": [30, 14], "to": [31, 14]}], os.path.join(work, "s2.kicad_pcb"), os.path.join(work, "s2w")))
show("set_width_fill_fed_track", edit(p, [{"op": "set_width", "net": "GND", "layer": "B.Cu", "start": [25, 30], "end": [35, 30], "from": 0.3, "to": 0.5}], os.path.join(work, "s3.kicad_pcb"), os.path.join(work, "s3w")))
show("move_stitching_via_out_of_pour", edit(p, [{"op": "move_via", "net": "GND", "at": [20, 25], "to": [55, 45]}], os.path.join(work, "s4.kicad_pcb"), os.path.join(work, "s4w")))

# 5 and 6: diff sees via layers, an arc lock, a zone's second outline, a zone clearance, a footprint value, footprint Edge.Cuts
src = open(p).read()


def dif(name, a, b, want_identical):
    pa, pb = os.path.join(work, name + "_a.kicad_pcb"), os.path.join(work, name + "_b.kicad_pcb")
    open(pa, "w").write(a)
    open(pb, "w").write(b)
    r = subprocess.run([PCB, "--json", "diff", pa, pb], capture_output=True, text=True)
    d = json.loads(r.stdout)["data"]
    print(json.dumps({"case": name, "ok": d["identical"] == want_identical, "identical": d["identical"], "fp": d["footprints"], "copper": d["copper"], "zones+": d["zones_added"], "zones-": d["zones_removed"]}))


def app(t, extra):
    t = t.rstrip()
    return t[:-1] + extra + "\n)\n"


vs, ve = blocks(src, "via")[1]
via = src[vs:ve]
dif("via_layers_FIn1", src, src[:vs] + via.replace('(layers "F.Cu" "B.Cu")', '(layers "F.Cu" "In1.Cu")') + src[ve:], False)
ARC = '\t(arc (start 5 35) (mid 10 33) (end 15 35) (width 0.2) (layer "F.Cu") (net "S")%s)'
dif("arc_lock", app(src, ARC % ""), app(src, ARC % " (locked yes)"), False)
zs, ze = blocks(src, "zone")[-1]
z = src[zs:ze]
z2 = z.replace("\t\t(polygon", "\t\t(polygon\n\t\t\t(pts (xy 50 2) (xy 55 2) (xy 55 8) (xy 50 8))\n\t\t)\n\t\t(polygon", 1)
dif("zone_second_outline", src, src[:zs] + z2 + src[ze:], False)
dif("zone_clearance", src, src[:zs] + z.replace("(clearance 0.3)", "(clearance 0.5)") + src[ze:], False)
fs, fe = blocks(src, "footprint")[0]
f = src[fs:fe]
dif("fp_value", src, src[:fs] + f.replace('"Value" "R"', '"Value" "10k"') + src[fe:], False)
EC = '\t\t(fp_line (start -0.5 -0.5) (end 0.5 0.5) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))\n'
f_ec = f[:-1] + EC + ")"
dif("fp_edge_cuts", src[:fs] + f_ec + src[fe:], src[:fs] + f_ec.replace("(end 0.5 0.5)", "(end 0.6 0.5)") + src[fe:], False)

# 9: preferred (second) run rejected, first kept: no .rejected.kicad_pro left
d = os.path.join(work, "r9")
os.makedirs(d, exist_ok=True)
b = os.path.join(d, "in.kicad_pcb")
subprocess.run([sys.executable, os.path.join(LIB, "synth_board.py"), "base", b], check=True, capture_output=True)
MK = os.path.join(R9, "fake", "mkses.py")
# first run leaves N open; second closes N straight through the W track at y 10 (a short), so it is rejected
subprocess.run([sys.executable, MK, os.path.join(d, "route_region.ses")], check=True)
subprocess.run([sys.executable, MK, os.path.join(d, "route_open.ses"), "N:F.Cu:0.2:20,15;30,15;30,10;40,10;40,15"], check=True)
out = os.path.join(d, "out.kicad_pcb")
r = subprocess.run([PCB, "--json", "route", b, "--region", "10,5,50,35", "--nets", "N", "--freerouting", "/opt/freerouting/freerouting-2.5.0.jar", "--java", os.path.join(R9, "fake", "fakejava"),
                    "--work", os.path.join(d, "w"), "-o", out, "--timeout", "30"], capture_output=True, text=True, env=dict(os.environ, FAKE_DIR=d))
js = json.loads(r.stdout)
print(json.dumps({"case": "rejected_run_files_removed", "outcome": js["outcome"], "attempt_used": js["data"].get("attempt_used"), "files": sorted(os.listdir(d))}))
