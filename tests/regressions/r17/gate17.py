"""The gate's hash of pcb.toml as canonical TOML (closure 33): a header-shaped line inside a multi-line string, and
edits that change layout but not content (comments, the order of tables and keys), which must leave the gate fresh.

Usage: python3 gate17.py workdir
"""
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


def fresh(d):
    s = L.pcb("gate", "status", "--project", d)
    return [x["fresh"] for x in s["data"].get("gates", [])]


# a waiver whose why holds a gate-header-shaped line; its max raised from 9 to 400 after the gate passed
d = L.paddle(work, "multiline")
L.toml_add(d, '[[waiver]]\nwhy = """probe\n[gates.zz]\n"""\ncheck = "drc"\nitem = "silk_overlap <no net>"\nmax = 9')
g = L.gate(d, W("ml_g"))
f0 = fresh(d)
L.toml_sub(d, "max = 9\n", "max = 400\n")
L.emit("multiline_max", gate=L.slim(g), fresh_before=f0, fresh_after=fresh(d))

# layout only: comments added and changed, [assembly] moved to the end, two keys of [project] swapped
d = L.paddle(work, "layout")
g = L.gate(d, W("lay_g"))
f0 = fresh(d)
L.toml_sub(d, "# the RP2040's exposed pad", "# a changed comment\n# the RP2040's exposed pad")
t = open(os.path.join(d, "pcb.toml")).read()
a0 = t.index("[assembly]")
a1 = t.index("# GND pours on both sides")
t = t[:a0] + t[a1:] + "\n" + t[a0:a1]
t = t.replace('name = "paddle-keyer"\nversion = "1.0.0"', 'version = "1.0.0"\nname = "paddle-keyer"')
open(os.path.join(d, "pcb.toml"), "w").write(t)
c, un = L.check(d, W("lay_c"))
L.emit("layout_only", gate=L.slim(g), fresh_before=f0, fresh_after=fresh(d), check_after=L.slim(c), unwaived=un)

# content: a waiver's why reworded (a value, so stale)
d = L.paddle(work, "content")
g = L.gate(d, W("ct_g"))
L.toml_sub(d, 'why = "footprint outlines of U1 and C10', 'why = "outlines of U1 and C10')
L.emit("why_changed", fresh_after=fresh(d))
