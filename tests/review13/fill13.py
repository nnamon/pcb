"""Review 13: the gate's filled flag, `(fill yes ...)`. What pcbnew writes after a fill, what KiCad does with saved
fills that lack the flag, and whether the oracle edits that read the flag as fill state can hide a real change.
One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 fill13.py workdir
"""
import json
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import r13lib as L  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
spec = {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
                {"ref": "G2", "at": (50, 30), "pads": [{"num": "1", "at": (50, 30), "net": "GND"}]}]}
d = L.build(os.path.join(work, "flag"), spec, '[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\n')
v, code, prob, out = L.zone(d)
pc = os.path.join(d, "work", "candidate_filled.kicad_pcb")
pcb_text = open(pc).read() if os.path.exists(pc) else ""
L.emit("pcbnew_writes_flag", contract=prob, **L.summary(v), pcbnew_flags=pcb_text.count("(fill yes"), written_flags=open(out).read().count("(fill yes") if os.path.exists(out) else None)

# the same board with the flag taken off: does pcbnew still load the fills, and does DRC (no refill) see them?
noflag = os.path.join(d, "noflag.kicad_pcb")
open(noflag, "w").write(open(out).read().replace("(fill yes ", "(fill "))
shutil.copy(os.path.join(d, "out.kicad_pro"), os.path.join(d, "noflag.kicad_pro"))
probe = r'''
import pcbnew, sys
b = pcbnew.LoadBoard(sys.argv[1])
z = [z for z in b.Zones() if not z.GetIsRuleArea()][0]
print("R", z.IsFilled(), round(z.GetFilledPolysList(pcbnew.F_Cu).Area() / 1e12, 2))
'''
res = {}
for name, p in [("flag", out), ("noflag", noflag)]:
    o = subprocess.run([sys.executable, "-c", probe, p], capture_output=True, text=True).stdout
    ln = [x for x in o.splitlines() if x.startswith("R")][0].split()
    res[name] = {"is_filled": ln[1] == "True", "area": float(ln[2]), "drc": L.drc(p)[0]}
L.emit("flag_meaning", **res)

# check_splice.py and gate12.py blank "(fill yes" across the whole file, and KiCad 10 writes a filled graphic shape as
# "(fill yes)": a gate that dropped " yes" from a copper rectangle would pass them
inp = os.path.join(work, "gr_in.kicad_pcb")
t = open(out).read()
i = t.rstrip().rfind(")")
t = t[:i] + '\t(gr_rect (start 2 30) (end 6 34) (stroke (width 0.1) (type solid)) (fill yes) (layer "B.Cu") (uuid "12345678-1234-4234-8234-123456789abc"))\n' + t[i:]
open(inp, "w").write(t)
outp = os.path.join(work, "gr_out.kicad_pcb")
open(outp, "w").write(t.replace('(fill yes) (layer "B.Cu")', '(fill) (layer "B.Cu")'))
o = subprocess.run([sys.executable, os.path.join(here, "..", "review9", "check_splice.py"), inp, outp], capture_output=True, text=True)
try:
    j = json.loads(o.stdout[o.stdout.index("{"):])
except ValueError:
    j = {"error": o.stderr[-300:]}
L.emit("check_splice_masks_shape_fill", prefix_identical=j.get("prefix_identical"), appended=j.get("appended"))
