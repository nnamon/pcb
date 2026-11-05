"""`pcb sync` on a board that exists: a part's LCSC code and value changed in the schematic, to another part with
the same JLCPCB package; and the new-board outline frame.

Usage: python3 sync18.py workdir
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r18lib import copy_fixture, emit, export_netlist, fresh, pcb, pyq, slim, use_netlist  # noqa: E402

work = sys.argv[1]
fresh(work)

FIELDS = r'''
def lc(f):
    try:
        return f.GetFieldText("LCSC")
    except KeyError:
        return ""
f = b.FindFootprintByReference(sys.argv[2])
print(json.dumps({"lcsc": lc(f), "value": f.GetValue(), "lib": str(f.GetFPID().GetUniStringLibItemName())}))
'''

d = copy_fixture(work, "lcsc_change")
r1 = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
before = pyq(os.path.join(d, "board.kicad_pcb"), FIELDS, "R1")
net = open(export_netlist(d)).read()
old = '(ref "R1")\n\t\t\t(value "5.1k")\n\t\t\t(footprint "pcb:C25905")\n\t\t\t(fields\n\t\t\t\t(field\n\t\t\t\t\t(name "LCSC") "C25905")'
assert old in net
net = net.replace(old, old.replace("5.1k", "10k").replace('"LCSC") "C25905"', '"LCSC") "C25744"'))
use_netlist(d, net)
r2 = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
after = pyq(os.path.join(d, "board.kicad_pcb"), FIELDS, "R1")
rp = pcb("parts", "--project", d, "--work", os.path.join(d, "w"))
codes = {p["lcsc"]: p["refs"] for p in rp["data"].get("parts", [])}
emit("lcsc_change", first=slim(r1), second=slim(r2), second_data={k: r2["data"].get(k) for k in ("replaced", "renetted", "added", "removed")},
     before=before, after=after, netlist_says={"lcsc": "C25744", "value": "10k"}, parts_refs_C25905=codes.get("C25905"), parts_refs_C25744=codes.get("C25744"))
