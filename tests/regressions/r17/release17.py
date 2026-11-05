"""pcb release after review 16's closures: two releases of one board give the same files; release fills the zones
again (closure 30), so a board whose stored fills are stale releases the fills a fresh fill makes; the
`.rejected.N` folders (closure 35).

Usage: python3 release17.py workdir
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r17lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


def cmp(a, b, name, board=None):
    args = ["compare-gerbers", a, b, "--work", W("cmp_" + name)]
    if board:
        args += ["--board", board]
    x = L.pcb(*args)
    return dict(outcome=x["outcome"], code=x["code"], msg=x["msg"][:200], differing={k: [(u["side"], u["mm2"]) for u in v.get("unexplained", [])][:4] for k, v in x["data"].get("layers", {}).items() if v.get("unexplained")})


# reproducible: one gated project released twice into two folders; every file the same but for KiCad's date lines
d = L.paddle(work, "rep")
g = L.gate(d, W("rep_g"))
r1 = L.release(d, W("rep_out1"), W("rep_r1"))
r2 = L.release(d, W("rep_out2"), W("rep_r2"))
diff = []
if r1.get("written") and r2.get("written"):
    for n in sorted(os.listdir(r1["written"])):
        a, b = os.path.join(r1["written"], n), os.path.join(r2["written"], n)
        if n.endswith(".zip"):
            za, zb = L.zip_texts(a), L.zip_texts(b)
            if sorted(za) != sorted(zb):
                diff.append(f"{n}: members differ")
            for m in sorted(za):
                if L.strip_dates(za[m]) != L.strip_dates(zb.get(m, "")):
                    diff.append(f"{n}:{m}")
        elif n != "CHECKSUMS.txt" and open(a, "rb").read() != open(b, "rb").read():
            diff.append(n)
board_after = open(L.board(d)).read() == open(L.board(L.paddle(work, "rep_fresh"))).read()
L.emit("reproducible", gate=L.slim(g), r1=L.slim(r1), r2=L.slim(r2), differing=diff, board_untouched_by_release=board_after)

# stale fill (closure 30): review 16's NPTH hole (1.0 mm) added inside the GND pour with pcbnew after pcb zone, fills
# not refilled. The release must hold a fresh fill: no copper at the hole, and copper equal to the same board's
# release after pcbnew fills it
FILL = "b.BuildConnectivity()\nzs = list(b.Zones())\npcbnew.ZONE_FILLER(b).Fill(zs)\n"
d = L.paddle(work, "fill_stale")
HOLE = '''
x, y = 21.1526, 21.234
f = pcbnew.FOOTPRINT(b)
f.SetReference("H9"); f.SetValue("hole"); f.Reference().SetVisible(False)
f.SetPosition(V(x, y))
p = pcbnew.PAD(f)
p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
p.SetSize(V(1.0, 1.0)); p.SetDrillSize(V(1.0, 1.0))
p.SetLayerSet(pcbnew.PAD.UnplatedHoleMask())
f.Add(p); p.SetPosition(V(x, y))
b.Add(f)
'''
L.post(L.board(d), HOLE)
d2 = W("fill_fresh")
shutil.copytree(d, d2)
L.post(L.board(d2), FILL)
outs = {}
for nm, dd in (("stale", d), ("fresh", d2)):
    c, un = L.check(dd, W(nm + "_c"))
    g, r = L.gate_release(dd, work, "fill_" + nm)
    outs[nm] = dict(check=L.slim(c), unwaived=un, gate=L.slim(g), release=L.slim(r), dfm=[(f["rule"], f["layer"]) for f in (r["data"].get("verify") or {}).get("dfm", [])][:8], written=r.get("written"))
cu = {}
if outs["stale"]["written"]:
    from shapely.geometry import Point
    z = L.unzip(os.path.join(outs["stale"]["written"], L.ZIP), W("fs_z"))
    cx, cy = L.pyq(L.board(d), 'c = b.GetBoardEdgesBoundingBox().GetCenter(); print(json.dumps([MM(c.x), MM(c.y)]))')
    hole = Point(21.1526 - cx, cy - 21.234).buffer(0.6)
    for lay in ("F_Cu", "B_Cu"):
        cu[lay] = round(L.gshape(L.find(z, lay)).intersection(hole).area, 4)
both = outs["stale"]["written"] and outs["fresh"]["written"]
L.emit("fill_stale", stale=outs["stale"], fresh=outs["fresh"], copper_within_0_1mm_of_hole_mm2=cu,
       stale_vs_fresh=cmp(os.path.join(outs["stale"]["written"], L.ZIP), os.path.join(outs["fresh"]["written"], L.ZIP), "sf") if both else None)

# rejected releases: a short (an A track across B's pad), every check finding waived; released three times into one
# folder name. Each lands in its own .rejected[.N]; a file the owner put in the first is kept
SHORT = '''
fp("R1", 10, 10, [("1", 0, 0, "A", 1.0, 1.0), ("2", 4, 0, "B", 1.0, 1.0)])
track("A", 10, 10, 14, 10, 0.25)
'''
d = L.synth(work, "short", SHORT)
L.waive_all(d, W("short_c"))
g = L.gate(d, W("short_g"))
out = W("short_out")
seen = []
for k in range(3):
    r = L.release(d, out, W(f"short_r{k}"))
    seen.append([r["outcome"], os.path.basename(r.get("written") or "")])
    if k == 0 and r.get("written"):
        open(os.path.join(r["written"], "owner_notes.txt"), "w").write("mine")
L.emit("rejected_numbered", gate=L.slim(g), releases=seen, out_exists=os.path.exists(out),
       owner_file_kept=os.path.exists(W("short_out.rejected", "owner_notes.txt")),
       folders=sorted(n for n in os.listdir(work) if n.startswith("short_out")))
