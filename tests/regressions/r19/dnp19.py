"""A schematic part marked DNP, or excluded from the BOM, through pcb sync, check and release. The release builds
the BOM and CPL from the board's footprint attributes, so sync must carry the schematic's flags there, and check
must see a difference.

Usage: python3 dnp19.py workdir
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import board, check, copy_base, emit, fresh, pcb, pyq, short, slim, through  # noqa: E402

work = sys.argv[1]
fresh(work)


def flag(sch, ref, old, new):
    t = open(sch).read()
    i = t.index(f'(symbol (lib_id "pk:{ref}")')
    j = t.index(old, i)
    assert j - i < 300, (ref, old)
    open(sch, "w").write(t[:j] + new + t[j + len(old):])


d = copy_base(work, "dnp")
sch = os.path.join(d, "schematic", "paddle-keyer.kicad_sch")
flag(sch, "C3", "(dnp no)", "(dnp yes)")
flag(sch, "C2", "(in_bom yes)", "(in_bom no)")
s = pcb("sync", "--project", d, "--work", os.path.join(work, "dnp_s"))
attrs = pyq(board(d), "print(json.dumps({r: fp(r).GetAttributes() for r in ('C2', 'C3', 'C4')}))")
attrs = {r: {"value": a, "dnp": bool(a & 64), "exclude_from_bom": bool(a & 8), "exclude_from_pos": bool(a & 4)} for r, a in attrs.items()}
t = through(d, os.path.join(work, "dnp_w"), os.path.join(work, "dnp_out"))
bom = glob.glob(os.path.join(work, "dnp_out", "*_BOM.csv"))
cpl = glob.glob(os.path.join(work, "dnp_out", "*_CPL.csv"))
in_bom = sorted({r.strip() for row in csv.DictReader(open(bom[0])) for r in row.get("Designator", "").split(",")} & {"C2", "C3"}) if bom else None
in_cpl = sorted({row.get("Designator") for row in csv.DictReader(open(cpl[0]))} & {"C2", "C3"}) if cpl else None
emit("dnp_and_not_in_bom", sync=slim(s), board_attrs=attrs, **t, released_bom_has=in_bom, released_cpl_has=in_cpl)
