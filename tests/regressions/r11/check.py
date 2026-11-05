"""Runs review 11's probes and checks the outcome each case must have (the probes print evidence, one JSON line per
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


# the gate's markers: zones never filled, with hand-written text, and copied footprints all keep their own fills
for c in cases("gate11.py"):
    if "fill_mismatch" in c and (any(o[0] != "done" for o in c["outcomes"]) or any(c["fill_mismatch"].values()) or c["distinct_files"] != 1):
        fails.append(f"gate11 {c['case']}: {json.dumps(c)[:300]}")
# prewire stubs: anchored in a never-filled zone, at a pad, joined at a bend
for c in cases("prewire11.py"):
    if c.get("outcome") != "done":
        fails.append(f"prewire11 {c['case']}: {json.dumps(c)[:300]}")
# diff: copper-affecting changes are seen; KiCad re-saves of hand-written text are not changes
for c in cases("diff11.py"):
    want = {"miss?": False, "resave": True}.get(c.get("kind"))
    if want is not None and c.get("identical") is not want:
        fails.append(f"diff11 {c['case']}: identical {c.get('identical')} (want {want}) {json.dumps(c.get('reported'))[:200]}")
print(json.dumps({"ok": not fails, "failed": fails}, indent=1))
sys.exit(0 if not fails else 1)
