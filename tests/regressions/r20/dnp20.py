"""Schematic flags (DNP, not in BOM, not on board, a user field named DNP) from the KiCad schematic through the
netlist, `pcb sync`, check, gate and release (review 19, closure 49), on the M4 project after its flow (routed). Also
a flag cleared after it was synced, and the flags set by hand on the board in pcbnew.

Usage: python3 dnp20.py workdir
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r20lib import board, copy_base, emit, export_netlist, fresh, pcb, pcbnew_run, slim  # noqa: E402

work = sys.argv[1]
fresh(work)
REFS = ("C2", "C3", "C4", "C5", "C6", "C7")


def flag(sch, ref, old, new):
    t = open(sch).read()
    i = t.index(f'(symbol (lib_id "pk:{ref}")')
    j = t.index(old, i)
    assert j - i < 300, (ref, old)
    open(sch, "w").write(t[:j] + new + t[j + len(old):])


def add_field(sch, ref, name, value):
    t = open(sch).read()
    i = t.index(f'(symbol (lib_id "pk:{ref}")')
    j = t.index('    (pin "1"', i)
    open(sch, "w").write(t[:j] + f'    (property "{name}" "{value}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n' + t[j:])


def attrs(d):
    a = pcbnew_run(board(d), f"print(json.dumps({{r: (fp(r).GetAttributes() if fp(r) else None) for r in {REFS!r}}}))", save=False)
    return {r: (None if v is None else [k for k, bit in (("dnp", 64), ("not_in_bom", 8), ("not_in_pos", 4)) if v & bit]) for r, v in a.items()}


def segs(d):
    return open(board(d)).read().count("(segment ")


def through(d, name):
    c = pcb("check", "--project", d, "--work", os.path.join(work, name + "_c"))
    unw = sorted(f"{x['check']} {x['item']}" for x in c["data"].get("findings", []) if not x.get("waived"))
    msgs = [x["message"][:300] for x in c["data"].get("findings", []) if not x.get("waived")]
    g = pcb("gate", "pass", "layout", "--project", d, "--work", os.path.join(work, name + "_g"))
    out = os.path.join(work, name + "_out")
    r = pcb("release", "--project", d, "-o", out, "--work", os.path.join(work, name + "_r"))
    bom = glob.glob(os.path.join(out, "*_BOM.csv"))
    cpl = glob.glob(os.path.join(out, "*_CPL.csv"))
    in_bom = sorted({x.strip() for row in csv.DictReader(open(bom[0])) for x in row.get("Designator", "").split(",")} & set(REFS)) if bom else None
    in_cpl = sorted({row.get("Designator") for row in csv.DictReader(open(cpl[0]))} & set(REFS)) if cpl else None
    return {"check": {"outcome": c["outcome"], "unwaived": unw, "msgs": msgs}, "gate": slim(g), "release": slim(r),
            "bom_has": in_bom, "cpl_has": in_cpl, "left_out": [x for x in (r["data"].get("left_out") or []) if x.split(":")[0] in REFS]}


def netlist_props(d, refs):
    n = export_netlist(os.path.join(d, "schematic", "paddle-keyer.kicad_sch"), os.path.join(d, "r20.net"))
    import re
    t = re.sub(r"\s+", " ", open(n).read())
    out = {}
    for r in refs:
        i = t.find(f'(comp (ref "{r}")')
        if i < 0:
            out[r] = None
            continue
        j = t.find("(comp (ref", i + 5)
        blk = t[i:j if j > 0 else t.find("(libparts", i)]
        out[r] = re.findall(r'\(property \(name "([^"]+)"\)(?: \(value "([^"]*)"\))?', blk)
    return out


# 1. C3 DNP, C2 not in BOM, C6 excluded from simulation only; synced on the routed board
d = copy_base(work, "flags")
sch = os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
flag(sch, "C3", "(dnp no)", "(dnp yes)")
flag(sch, "C2", "(in_bom yes)", "(in_bom no)")
flag(sch, "C6", "(exclude_from_sim no)", "(exclude_from_sim yes)")
props = netlist_props(d, ("C2", "C3", "C6"))
s0 = segs(d)
s = pcb("sync", "--project", d, "--work", os.path.join(work, "flags_s"))
emit("flags_set", netlist=props, sync=slim(s), replaced=s["data"].get("replaced"), segments_before=s0, segments_after=segs(d),
     attrs=attrs(d), **through(d, "flags"))

# 2. the flags cleared again (C2 back in the BOM, C3 fitted), then sync
flag(sch, "C3", "(dnp yes)", "(dnp no)")
flag(sch, "C2", "(in_bom no)", "(in_bom yes)")
s = pcb("sync", "--project", d, "--work", os.path.join(work, "cleared_s"))
emit("flags_cleared", sync=slim(s), replaced=s["data"].get("replaced"), attrs=attrs(d), **through(d, "cleared"))

# 3. C4 not on the board (KiCad leaves it out of the netlist)
d = copy_base(work, "on_board")
sch = os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
flag(sch, "C4", "(on_board yes)", "(on_board no)")
s = pcb("sync", "--project", d, "--work", os.path.join(work, "onb_s"))
emit("not_on_board", netlist=netlist_props(d, ("C4",)), sync=slim(s))

# 4. C5 with a user field named DNP whose value is "No"
d = copy_base(work, "dnp_field")
sch = os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
add_field(sch, "C5", "DNP", "No")
s = pcb("sync", "--project", d, "--work", os.path.join(work, "field_s"))
emit("dnp_field_no", netlist=netlist_props(d, ("C5",)), sync=slim(s), replaced=s["data"].get("replaced"), attrs=attrs(d), **through(d, "field"))

# 5. the schematic changed after the gate, with no sync: C3 DNP, R1 5.1k to 4.7k. Release straight away
d = copy_base(work, "after_gate")
sch = os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
st0 = pcb("gate", "status", "--project", d)
flag(sch, "C3", "(dnp no)", "(dnp yes)")
t = open(sch).read()
i = t.index('(symbol (lib_id "pk:R1")')
j = t.index('"5.1k"', i)
open(sch, "w").write(t[:j] + '"4.7k"' + t[j + 6:])
st1 = pcb("gate", "status", "--project", d)
c = pcb("check", "--project", d, "--work", os.path.join(work, "ag_c"))
out = os.path.join(work, "ag_out")
r = pcb("release", "--project", d, "-o", out, "--work", os.path.join(work, "ag_r"))
bom = glob.glob(os.path.join(out, "*_BOM.csv"))
rows = [row for row in csv.DictReader(open(bom[0]))] if bom else []
emit("schematic_changed_after_gate", gate_before=[(g["name"], g["fresh"]) for g in st0["data"].get("gates", [])],
     gate_after=[(g["name"], g["fresh"]) for g in st1["data"].get("gates", [])],
     check={"outcome": c["outcome"], "unwaived": sorted(f"{x['check']} {x['item']}" for x in c["data"].get("findings", []) if not x.get("waived"))},
     release=slim(r), bom_c3=[x for x in rows if "C3" in [y.strip() for y in x.get("Designator", "").split(",")]],
     bom_r1=[x for x in rows if "R1" in [y.strip() for y in x.get("Designator", "").split(",")]])

# 6. on a fresh copy: C7 "exclude from BOM" ticked by hand in pcbnew (KiCad's footprint properties); the schematic says fit it
d = copy_base(work, "hand")
pcbnew_run(board(d), "f = fp('C7'); f.SetExcludedFromBOM(True)")
emit("hand_exclude_from_bom", attrs=attrs(d), **through(d, "hand"))

# 7. on a fresh copy: C7 "exclude from position files" ticked by hand
d = copy_base(work, "hand_pos")
pcbnew_run(board(d), "f = fp('C7'); f.SetExcludedFromPosFiles(True)")
emit("hand_exclude_from_pos", attrs=attrs(d), **through(d, "hand_pos"))
