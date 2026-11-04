"""pcb check's staleness after reviews 17 and 18: the dry runs of pcb paste and pcb art and their content comparison
(closure 39 and note 44), the board against the circuit and [[place]] (closure 41), each on the M4 paddle keyer after
its whole flow. Harmless KiCad saves must stay current; real differences must be stale.

Usage: python3 stale19.py workdir
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import add, board, check, copy_base, emit, export_netlist, fresh, pcb, post, pyq, short, slim, sub, through, use_netlist  # noqa: E402

work = sys.argv[1]
fresh(work)


def run(name, edit=None, toml=None, rel=False):
    d = copy_base(work, name)
    if edit:
        edit(d)
    if toml:
        toml(d)
    w = os.path.join(work, name + "_w")
    if rel:
        return d, through(d, w, os.path.join(work, name + "_out"))
    return d, short(check(d, w))


_, c = run("control")
emit("control", check=c)

# ---- harmless saves

_, c = run("kicad_save", lambda d: post(board(d), "pass"))
emit("kicad_save", check=c)


def save_twice_rerun(d):
    post(board(d), "pass")
    for s in ("paste", "art"):
        r = pcb(s, "--project", d, "--work", os.path.join(d, "w_" + s))
        assert r["outcome"] == "done", r
    post(board(d), "pass")


_, c = run("kicad_save_rerun_save", save_twice_rerun)
emit("kicad_save_rerun_save", check=c)


def refill_save(d):
    post(board(d), "pcbnew.ZONE_FILLER(b).Fill(b.Zones())")


_, c = run("kicad_refill_save", refill_save)
emit("kicad_refill_save", check=c)

# a part moved and moved back in pcbnew, as a KiCad user does by accident
_, c = run("kicad_move_back", lambda d: post(board(d), "f = fp('R1'); p = f.GetPosition(); f.SetPosition(V(TM(p.x) + 3, TM(p.y))); f.SetPosition(p)"))
emit("kicad_move_back", check=c)

# ---- paste output changed after pcb paste

_, c = run("pip_dropped", lambda d: post(board(d), "for q in fp('J1').Pads():\n    if q.GetNumber() == '13':\n        q.SetLayerSet(q.GetLayerSet().RemoveLayer(pcbnew.F_Paste))"))
emit("pip_dropped", check=c)

AP = "ap = [q for q in fp('U1').Pads() if q.GetNumber() == '']\n"
_, c = run("aperture_moved", lambda d: post(board(d), AP + "p = ap[0].GetPosition(); ap[0].SetPosition(V(TM(p.x) + 0.05, TM(p.y)))"))
emit("aperture_moved", check=c)
_, c = run("aperture_round", lambda d: post(board(d), AP + "[q.SetShape(pcbnew.PAD_SHAPE_CIRCLE) for q in ap]"), rel=True)
emit("aperture_round", **c)
_, c = run("aperture_turned", lambda d: post(board(d), AP + "[q.SetOrientationDegrees(45) for q in ap]"))
emit("aperture_turned", check=c)
# a pad-level paste margin closing the pin-in-paste openings (a footprint update can bring one)
_, c = run("pip_margin", lambda d: post(board(d), "for q in fp('J1').Pads():\n    if q.GetNumber() in ('13', '14'):\n        q.SetLocalSolderPasteMargin(FM(-1.5))"), rel=True)
emit("pip_margin", **c)

# ---- art output changed after pcb art

ART = "g = [x for x in b.Groups() if x.GetName() == 'pcb:art:version'][0]\nshapes = [x for x in g.GetItems() if x.GetClass() == 'PCB_SHAPE']\n"
_, c = run("art_point", lambda d: post(board(d), ART + "o = shapes[0].GetPolyShape().Outline(0); p = o.CPoint(0); o.SetPoint(0, pcbnew.VECTOR2I(p.x + FM(0.01), p.y))"))
emit("art_point", check=c)
_, c = run("art_layer", lambda d: post(board(d), ART + "[s.SetLayer(pcbnew.F_SilkS) for s in shapes]"))
emit("art_layer", check=c)
_, c = run("art_moved", lambda d: post(board(d), ART + "[s.Move(V(0.5, 0)) for s in shapes]"))
emit("art_moved", check=c)


# note 44: version raised, pcb art run on a scratch copy, its record line pasted into the board
def record_copied(d):
    sub(os.path.join(d, "pcb.toml"), 'version = "2.0.0"', 'version = "2.0.1"')
    s = d + "_scratch"
    shutil.copytree(d, s)
    r = pcb("art", "--project", s, "--work", os.path.join(s, "w"))
    assert r["outcome"] == "done", r
    rec = re.search(r'\(gr_text "pcb:inputs:art [0-9a-f]+"', open(board(s)).read())[0]
    t = open(board(d)).read()
    open(board(d), "w").write(re.sub(r'\(gr_text "pcb:inputs:art [0-9a-f]+"', rec, t))


_, c = run("record_copied", record_copied, rel=True)
emit("record_copied", **c)

# ---- the circuit (closure 41)


def netedit(fn):
    def e(d):
        t = open(export_netlist(d)).read()
        use_netlist(d, fn(t))
    return e


def r1_block(t):
    i = t.index('(ref "R1")')
    j = t.index("(comp", i)
    return i, j


def r1_value(t):
    i, j = r1_block(t)
    return t[:i] + t[i:j].replace('(value "5.1k")', '(value "4.7k")', 1) + t[j:]


_, c = run("netlist_exported_unchanged", netedit(lambda t: t))
emit("netlist_exported_unchanged", check=c)
_, c = run("sync_value", netedit(r1_value))
emit("sync_value", check=c)


def r1_lcsc(t):
    i, j = r1_block(t)
    assert "C25905" in t[i:j]
    return t[:i] + t[i:j].replace("C25905", "C25744") + t[j:]


_, c = run("sync_lcsc", netedit(r1_lcsc))
emit("sync_lcsc", check=c)


def move_pin(t):
    # R1.1 taken off CC1, so it and J1.A5 are each alone on a net
    m = re.search(r'\(node\s+\(ref "R1"\)\s+\(pin "1"\).*?\n\t\t\t\)', t, re.S)
    assert m, "R1.1 node"
    return t[:m.start()] + t[m.end():]


_, c = run("sync_pin_dropped", netedit(move_pin))
emit("sync_pin_dropped", check=c)

# R1's footprint on the board replaced by another land pattern (0603 pads), same reference, value, LCSC and nets
FP0603 = ("f = fp('R1')\nfor q in f.Pads():\n    p = q.GetFPRelativePosition(); s = 1 if p.x > 0 else -1\n"
          "    q.SetFPRelativePosition(V(s * 0.775, 0)); q.SetSize(V(0.9, 0.95))\n")
d, c = run("footprint_changed_on_board", lambda d: post(board(d), FP0603), rel=True)
emit("footprint_changed_on_board", **c, parts=slim(pcb("parts", "--project", d, "--work", os.path.join(work, "fpc_parts"))))

# ---- [[place]] (closure 41)

def place_shift(d):
    t = open(os.path.join(d, "pcb.toml")).read()
    i = t.index('ref = "R1"')
    m = re.compile(r"at = \[([-0-9.]+), ([-0-9.]+)\]").search(t, i)
    open(os.path.join(d, "pcb.toml"), "w").write(t[:m.start()] + f"at = [{float(m[1]) + 0.05}, {m[2]}]" + t[m.end():])


_, c = run("place_shift_005", place_shift)
emit("place_shift_005", check=c)


def place_rot(d):
    t = open(os.path.join(d, "pcb.toml")).read()
    i = t.index('ref = "R1"')
    m = re.compile(r"rot_deg = ([-0-9.]+)").search(t, i)
    open(os.path.join(d, "pcb.toml"), "w").write(t[:m.start()] + f"rot_deg = {float(m[1]) + 180}" + t[m.end():])


_, c = run("place_rot_180", place_rot)
emit("place_rot_180", check=c)
_, c = run("board_moved_001", lambda d: post(board(d), "f = fp('R1'); p = f.GetPosition(); f.SetPosition(V(TM(p.x) + 0.01, TM(p.y)))"))
emit("board_moved_001", check=c)
_, c = run("board_turned_360", lambda d: post(board(d), "f = fp('R1'); f.SetOrientationDegrees(f.GetOrientationDegrees() + 360)"))
emit("board_turned_360", check=c)
