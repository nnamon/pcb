"""The `stale` check and its inputs records (`pcb:inputs:<command>` on Cmts.User): review 16's closures 25 and 29
again, and whether the record can be fooled: a KiCad save, the commands' output removed or moved after they ran,
a record copied in, a waiver, and pcb.toml settings no record covers ([[place]]).

Usage: python3 stale17.py workdir
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r17lib as L  # noqa: E402

work = os.path.abspath(sys.argv[1])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def W(*p):
    return os.path.join(work, *p)


def stale_of(c):
    return sorted(f["item"] for f in c["data"].get("findings", []) if f["check"] == "stale")


def records(d):
    return sorted(re.findall(r'"pcb:inputs:(\w+) (\w+)"', open(L.board(d)).read()))


# control: the base project checks clean, gates and releases
d = L.paddle(work, "control")
c, un = L.check(d, W("control_c"))
g, r = L.gate_release(d, work, "control")
CTL_OUT = r.get("written")
L.emit("control", check=L.slim(c), unwaived=un, records=records(d), gate=L.slim(g), release=L.slim(r))


def compare_ctl(name, z):
    if not (z and os.path.exists(z) and CTL_OUT):
        return None
    x = L.pcb("compare-gerbers", z, os.path.join(CTL_OUT, L.ZIP), "--work", W("cmp_" + name))
    return dict(outcome=x["outcome"], code=x["code"], differing={k: len(v.get("unexplained", [])) for k, v in x["data"].get("layers", {}).items() if v.get("unexplained")},
                drill_only=[len(x["data"].get("drill", {}).get("only_a", []) or []), len(x["data"].get("drill", {}).get("only_b", []) or [])])


# 25 and 29: each pcb.toml change not applied; check must find it stale and the gate must not pass
CHANGES = {
    "version": ('version = "1.0.0"', 'version = "1.0.1"'),
    "label_moved": ("at = [-6.2, 15.95]", "at = [-6.2, 10.0]"),
    "paste_dropped": ('[[paste]]\npad = "U1.57"\nwindows = [2, 2]\nsize_mm = 1.25\nweb_mm = 0.35\n', ""),
    "zone_clearance": ("clearance_mm = 0.25", "clearance_mm = 0.3"),
    "label_removed": ('[[text]]\nname = "label12"\ntext = "v{version}"', '[[text]]\nname = "label12"\ntext = "v1.0.0"'),
}
for name, (old, new) in CHANGES.items():
    d = L.paddle(work, "s_" + name)
    L.toml_sub(d, old, new)
    c, un = L.check(d, W(name + "_c"))
    g, r = L.gate_release(d, work, "s_" + name)
    L.emit("stale_" + name, check=L.slim(c), stale=stale_of(c), unwaived=un, gate=L.slim(g), release=L.slim(r))

# a stale finding with a waiver naming it: no waiver covers stale
d = L.paddle(work, "s_waived")
L.toml_sub(d, 'version = "1.0.0"', 'version = "1.0.1"')
L.toml_add(d, '[[waiver]]\ncheck = "stale"\nitem = "art"\nmax = 5\nwhy = "probe"')
c, un = L.check(d, W("waived_c"))
g = L.gate(d, W("waived_g"))
L.emit("stale_waived", check=L.slim(c), unwaived=un, gate=L.slim(g))

# a KiCad save (pcbnew load and save, nothing changed): the records survive and check stays clean
d = L.paddle(work, "s_kicad_save")
before = records(d)
L.post(L.board(d), "pass")
c, un = L.check(d, W("ks_c"))
L.emit("kicad_save", records_before=before, records_after=records(d), stale=stale_of(c), unwaived=un)

# a KiCad save that moves the record text (the owner drags it): read by content, so still clean
d = L.paddle(work, "s_record_moved")
L.post(L.board(d), 'for t in b.GetDrawings():\n    if t.GetClass() == "PCB_TEXT" and t.GetText().startswith("pcb:inputs:"):\n        t.Move(V(30, 30))')
c, un = L.check(d, W("rm_c"))
L.emit("record_moved", stale=stale_of(c), unwaived=un)

# the art run's output removed after it ran (the version label's group deleted in KiCad), record kept
DEL = '''
for g in list(b.Groups()):
    if g.GetName() == "pcb:art:label12":
        for it in list(g.GetItems()):
            b.Remove(it)
        b.Remove(g)
'''
d = L.paddle(work, "s_label_deleted")
L.post(L.board(d), DEL)
c, un = L.check(d, W("ld_c"))
g, r = L.gate_release(d, work, "s_label_deleted")
L.emit("label_deleted", check=L.slim(c), stale=stale_of(c), unwaived=un, gate=L.slim(g), release=L.slim(r),
       vs_control=compare_ctl("ld", os.path.join(r["written"], L.ZIP)) if r.get("written") else None)

# pcb paste's windows undone in KiCad (as "update footprint from library" does): U1.57 has its full paste opening
# again, the aperture pads are gone, the record stays
UNDO = '''
f = b.FindFootprintByReference("U1")
gone = 0
for p in list(f.Pads()):
    if p.GetNumber() == "57" and p.IsOnLayer(pcbnew.F_Cu):
        ls = p.GetLayerSet(); ls.AddLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
    elif not p.IsOnLayer(pcbnew.F_Cu) and not p.IsOnLayer(pcbnew.B_Cu):
        f.Remove(p); gone += 1
print(json.dumps(gone))
'''
d = L.paddle(work, "s_paste_undone")
n57 = L.post(L.board(d), UNDO)
c, un = L.check(d, W("pu_c"))
g, r = L.gate_release(d, work, "s_paste_undone")
L.emit("paste_undone", apertures_removed=next((int(x) for x in n57.split() if x.isdigit()), None), check=L.slim(c), stale=stale_of(c), unwaived=un, gate=L.slim(g), release=L.slim(r),
       vs_control=compare_ctl("pu", os.path.join(r["written"], L.ZIP)) if r.get("written") else None)

# a record copied from another run: version raised, pcb art run on a scratch copy, its record line pasted into the
# board, which still prints v1.0.0
d = L.paddle(work, "s_record_copied")
L.toml_sub(d, 'version = "1.0.0"', 'version = "1.0.1"')
sc = W("s_record_scratch")
shutil.copytree(d, sc)
a = L.pcb("art", "--project", sc, "--work", W("rc_art"))
new = dict(records(sc))["art"]
t = open(L.board(d)).read()
open(L.board(d), "w").write(re.sub(r'"pcb:inputs:art \w+"', f'"pcb:inputs:art {new}"', t))
c, un = L.check(d, W("rc_c"))
g, r = L.gate_release(d, work, "s_record_copied")
L.emit("record_copied", art=L.slim(a), check=L.slim(c), stale=stale_of(c), unwaived=un, release=L.slim(r))

# [[place]]: an entry at R1's current place, pcb place run, then the entry moved 2 mm and not applied
d = L.paddle(work, "s_place")
q = L.pyq(L.board(d), '''
bb = b.GetBoardEdgesBoundingBox(); cx, cy = MM(bb.GetCenter().x), MM(bb.GetCenter().y)
f = b.FindFootprintByReference("R1"); p = f.GetPosition()
print(json.dumps([round(MM(p.x) - cx, 4), round(cy - MM(p.y), 4), f.GetOrientationDegrees(), "bottom" if f.IsFlipped() else "top"]))''')
L.toml_add(d, f'[[place]]\nref = "R1"\nat = [{q[0]}, {q[1]}]\nrot_deg = {q[2]:g}\nside = "{q[3]}"')
pl = L.pcb("place", "--project", d, "--work", W("pl_place"))
c0, un0 = L.check(d, W("pl_c0"))
L.toml_sub(d, f"at = [{q[0]}, {q[1]}]", f"at = [{q[0] + 2.0}, {q[1]}]")
c1, un1 = L.check(d, W("pl_c1"))
L.emit("place_not_applied", r1=q, place=L.slim(pl), check_before=L.slim(c0), unwaived_before=un0, check_after=L.slim(c1), stale_after=stale_of(c1), unwaived_after=un1)
