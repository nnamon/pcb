"""Re-sync of a changed part (review 18, closure 4): a part whose LCSC code or value changed in the same package is
replaced where it stands. Also values KiCad writes with escapes, a bottom-side part, a part with a paste rule, and
a routed board.

Usage: python3 resync19.py workdir
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import FX4, board, check, copy_base, emit, export_netlist, fresh, pcb, pyq, short, slim, sub, use_netlist  # noqa: E402

work = sys.argv[1]
fresh(work)

STATE = '''
out = {}
for r in sys.argv[2].split(","):
    f = fp(r)
    if f is None:
        out[r] = None
        continue
    p = f.GetPosition()
    out[r] = {"x": TM(p.x), "y": TM(p.y), "rot": f.GetOrientationDegrees(), "layer": f.GetLayerName(), "value": f.GetValue(),
              "lcsc": ([x.GetText() for x in f.GetFields() if x.GetName() == "LCSC"] or [None])[0], "lib": str(f.GetFPID().GetUniStringLibItemName()),
              "nets": sorted((q.GetNumber(), q.GetNetname()) for q in f.Pads() if q.GetNumber())}
print(json.dumps(out))
'''


def state(d, refs):
    import subprocess
    import json
    from r19lib import PRE
    r = subprocess.run([sys.executable, "-c", PRE + STATE, board(d), ",".join(refs)], capture_output=True, text=True)
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else r.stderr[-500:]


def comp_block(t, ref):
    i = t.index(f'(ref "{ref}")')
    j = t.index("(comp", i) if "(comp" in t[i:] else t.index("(nets", i)
    return i, j


def edit_comp(t, ref, old, new):
    i, j = comp_block(t, ref)
    assert old in t[i:j], (ref, old)
    return t[:i] + t[i:j].replace(old, new) + t[j:]


def synced(name, extra_toml=""):
    d = os.path.join(work, name)
    shutil.copytree(FX4, d, ignore=shutil.ignore_patterns("make_fixture.py"))
    if extra_toml:
        open(os.path.join(d, "pcb.toml"), "a").write("\n" + extra_toml + "\n")
    for s in ("sync", "place"):
        r = pcb(s, "--project", d, "--work", os.path.join(d, "w0" + s))
        assert r["outcome"] == "done", (s, r)
    return d


def resync(d, fn, refs, rip=False):
    before = state(d, refs)
    use_netlist(d, fn(open(export_netlist(d)).read()))
    r = pcb("sync", "--project", d, "--work", os.path.join(d, "w1"), *(["--rip"] if rip else []))
    after = state(d, refs)
    c = check(d, os.path.join(d, "w2"))
    c["unwaived_n"] = len(c["unwaived"])
    return {"sync": slim(r), "unwaived_after": c["unwaived"][:8], "replaced": r["data"].get("replaced"), "renetted": r["data"].get("renetted"), "ripped": {k: v for k, v in r["data"].items() if "rip" in k},
            "before": before, "after": after, "stale_after": c["stale"], "stale_msg": c["stale_msg"]}


# 1. R1 5.1k C25905 to 10k C25744, both R0402
d = synced("lcsc_and_value")
emit("lcsc_and_value", **resync(d, lambda t: edit_comp(edit_comp(t, "R1", "5.1k", "10k"), "R1", "C25905", "C25744"), ["R1"]))

# 2. the value alone
d = synced("value_only")
emit("value_only", **resync(d, lambda t: edit_comp(t, "R1", "5.1k", "5.10k"), ["R1"]))

# 3. values with characters KiCad escapes or that are not ASCII: no stale finding once synced
d = synced("odd_values")
emit("odd_values", **resync(d, lambda t: edit_comp(edit_comp(t, "R1", '"5.1k"', '"5.1k \\"1%\\""'), "R2", '(value "5.1k")', '(value "5.1kΩ ±1%")'), ["R1", "R2"]))

# 4. a part on the bottom (an M4 fixture part machine sides allow? test pads are not assembled) keeps its side
d = synced("bottom_part")
tp = [r for r in ("TP_FISH", "TP1", "TP2") if f'(ref "{r}")' in open(export_netlist(d)).read()]
emit("bottom_part_refs", refs=tp)
if tp:
    ref = tp[0]
    t = open(os.path.join(d, "pcb.toml")).read()
    i = t.index(f'ref = "{ref}"')
    side = re.compile(r'side = "(\w+)"').search(t, i)
    emit("bottom_part_side_in_toml", ref=ref, side=side[1])

    def new_value(t, ref=ref):
        i, _ = comp_block(t, ref)
        return edit_comp(t, ref, re.search(r'\(value "([^"]*)"\)', t[i:])[0], '(value "TP-new")')
    emit("bottom_part", **resync(d, new_value, [ref]))

# 5. U1, which carries [[paste]] windows, changes value: replaced, and check must find its paste output gone
d = synced("paste_part")
r = pcb("paste", "--project", d, "--work", os.path.join(d, "wpaste"))
emit("paste_part_paste", r=slim(r))
emit("paste_part", **resync(d, lambda t: edit_comp(t, "U1", re.search(r'\(value "([^"]*)"\)', t[comp_block(t, "U1")[0]:])[0], '(value "RP2040-B2")'), ["U1"]))

# 6. the routed M4 board: R1's value changes; its nets (CC1, GND) keep their pads
d = copy_base(work, "routed")
emit("routed_no_rip", **resync(d, lambda t: edit_comp(t, "R1", "5.1k", "5.10k"), ["R1"]))
d = copy_base(work, "routed_rip")
res = resync(d, lambda t: edit_comp(t, "R1", "5.1k", "5.10k"), ["R1"], rip=True)
res.pop("before"), res.pop("after")
emit("routed_rip", **res)
