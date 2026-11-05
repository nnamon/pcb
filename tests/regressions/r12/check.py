"""Runs review 12's probes and checks the outcome each case must have (the probes print evidence, one JSON line per
case; this file holds the verdicts). Exit 1 on any miss.

Usage: python3 check.py pcb-binary workdir
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
env = dict(os.environ, PCB_BIN=pcb)
fails = []


def cases(script):
    r = subprocess.run([sys.executable, os.path.join(here, script), os.path.join(work, script[:-3])], capture_output=True, text=True, env=env)
    out = []
    for ln in r.stdout.splitlines():
        if ln.startswith("{"):
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    if r.returncode or not out:
        fails.append(f"{script}: exit {r.returncode}, {len(out)} cases: {r.stderr[-400:]}")
    return out


# markers: every zone keeps its own fill, its own uuid, and no marker reaches the written board
for c in cases("gate12.py"):
    # a zone with no outline is refused with a message naming it (review 12, R5)
    if c.get("case") == "zone_without_polygon":
        if not all(o[0] == "refused" and "has no outline" in str(o[1]) for o in c["outcomes"]):
            fails.append(f"gate12 zone_without_polygon: {json.dumps(c)[:300]}")
        continue
    if "outcomes" in c and (any(o[0] != "done" for o in c["outcomes"]) or c.get("fill_mismatch") or c.get("distinct_files") != 1
                            or c.get("zone_uuids_kept") is False or c.get("markers_leaked") is True or c.get("removed")):
        fails.append(f"gate12 {c['case']}: {json.dumps(c)[:300]}")
# diff: copper-affecting changes seen, KiCad re-saves of hand-written text not changes
for c in cases("diff12.py"):
    want = {"miss?": False, "resave": True}.get(c.get("kind"))
    if want is not None and c.get("identical") is not want:
        fails.append(f"diff12 {c['case']}: identical {c.get('identical')} (want {want}) {json.dumps(c.get('reported'))[:200]}")
# prewire stubs: a stub the router never joined is kept, even beside one it did
want = {"anchor_zone_outside_hole": "done", "anchor_zone_in_hole": "refused", "join_inner_corner_3seg": "done", "one_stub_control": "rejected"}
seen = {c["case"]: c for c in cases("prewire12.py")}
for name, outcome in want.items():
    if seen.get(name, {}).get("outcome") != outcome:
        fails.append(f"prewire12 {name}: {json.dumps(seen.get(name))[:300]} (want {outcome})")
if seen.get("two_stubs_one_pad: stub 1 kept", {}).get("kept") is not True:
    fails.append(f"prewire12 two_stubs_one_pad: stub 1 not kept {json.dumps(seen.get('two_stubs_one_pad'))[:300]}")
print(json.dumps({"ok": not fails, "failed": fails}, indent=1))
sys.exit(0 if not fails else 1)
