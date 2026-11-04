"""Re-sync keeping copper when only the part changed (review 19, closure 55), on the routed M4 board after its flow.

- R1's value 5.1k to 5.10k: no --rip needed; segments kept; check, gate, release.
- R1's LCSC C25905 to C25744 (both JLCPCB package R0402): the same.
- R1's LCSC to a made-up part whose EasyEDA package is also titled R0402 but whose pads sit 0.4 mm further apart
  and are 0.2 mm wider: the board's lib id (`jlc:R0402`) stays, so the copper stays. Does check stop the board?
- Control: a different package (R0603, C25905's pads drawn as 0603): refused without --rip.

Usage: python3 resync20.py workdir
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r20lib import board, copy_base, emit, fresh, jlc, pcb, pcbnew_run, slim  # noqa: E402

work = sys.argv[1]
fresh(work)


def r1_sym(sch, old, new):
    t = open(sch).read()
    i = t.index('(symbol (lib_id "pk:R1")')
    j = t.index(old, i)
    assert j - i < 600, old
    open(sch, "w").write(t[:j] + new + t[j + len(old):])


def segs(d):
    return open(board(d)).read().count("(segment ")


R1Q = ("f = fp('R1')\nprint(json.dumps({'lib': str(f.GetFPID().GetUniStringLibItemName()), 'pads': sorted([[p.GetNumber(), round(TM(p.GetPosition().x - f.GetPosition().x), 3), "
       "round(TM(p.GetPosition().y - f.GetPosition().y), 3), round(TM(p.GetSize().x), 3), round(TM(p.GetSize().y), 3)] for p in f.Pads()])}))")


def run(name, edit, fake=None):
    d = copy_base(work, name)
    sch = os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
    if fake:
        code, comp = fake
        json.dump(comp, open(os.path.join(d, "parts", f"{code}.easyeda.json"), "w"))
        json.dump(jlc(code), open(os.path.join(d, "parts", f"{code}.jlc.json"), "w"))
    edit(sch)
    before = pcbnew_run(board(d), R1Q, save=False)
    s0 = segs(d)
    s = pcb("sync", "--project", d, "--work", os.path.join(work, name + "_s"))
    res = {"sync": slim(s), "replaced": s["data"].get("replaced"), "segments_before": s0, "segments_after": segs(d), "r1_before": before}
    if s["outcome"] == "done":
        res["r1_after"] = pcbnew_run(board(d), R1Q, save=False)
        c = pcb("check", "--project", d, "--work", os.path.join(work, name + "_c"))
        res["check"] = {"outcome": c["outcome"], "unwaived": sorted(f"{x['check']} {x['item']}" for x in c["data"].get("findings", []) if not x.get("waived"))}
        res["gate"] = slim(pcb("gate", "pass", "layout", "--project", d, "--work", os.path.join(work, name + "_g")))
        r = pcb("release", "--project", d, "-o", os.path.join(work, name + "_out"), "--work", os.path.join(work, name + "_r"))
        res["release"] = slim(r)
    emit(name, **res)


run("value_only", lambda sch: r1_sym(sch, '"5.1k"', '"5.10k"'))
run("lcsc_same_package", lambda sch: (r1_sym(sch, '"LCSC" "C25905"', '"LCSC" "C25744"'), r1_sym(sch, '"5.1k"', '"10k"')))

# a made-up R0402 with other pads: C25905's record, its two pads moved 0.2 mm out each and 0.2 mm wider
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "paddle_keyer_m4", "parts", "C25905.easyeda.json")
comp = json.load(open(base))
pk = comp["result"]["packageDetail"]["dataStr"]
ox = float(pk["head"]["x"])
shapes = []
for s in pk["shape"]:
    f = s.split("~")
    if f[0] == "PAD":
        x = float(f[2])
        f[2] = str(x + (0.7874 if x > ox else -0.7874))  # 0.2 mm
        f[4] = str(float(f[4]) + 0.7874)
        f[10] = ""  # the outline: the RECT pad is drawn from its size
        s = "~".join(f)
    shapes.append(s)
pk["shape"] = shapes
assert comp["result"]["packageDetail"]["title"] == "R0402"
run("lcsc_same_title_other_pads", lambda sch: r1_sym(sch, '"LCSC" "C25905"', '"LCSC" "C9400001"'), fake=("C9400001", comp))

# control: the same pads under another package title
comp2 = json.loads(json.dumps(comp))
comp2["result"]["packageDetail"]["title"] = "R0402W"
run("lcsc_other_title_other_pads", lambda sch: r1_sym(sch, '"LCSC" "C25905"', '"LCSC" "C9400002"'), fake=("C9400002", comp2))
