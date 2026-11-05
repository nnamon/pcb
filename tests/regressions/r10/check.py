"""Runs review 10's probes and checks the outcome each case must have (the probes print evidence, one JSON line per
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


def lines(script):
    r = subprocess.run([sys.executable, os.path.join(here, script), os.path.join(work, script[:-3])], capture_output=True, text=True, env=env)
    out = []
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if ln.startswith("{") or ln.startswith("["):
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return r.returncode, out


fails = []
# the gate's zone pairing: every run done, every fill pcbnew's, the same bytes each run
for script in ("gate_probes.py",):
    rc, got = lines(script)
    if rc or not got:
        fails.append(f"{script}: exit {rc}, {len(got)} cases")
    for c in got:
        if any(o[0] != "done" for o in c["outcomes"]) or any(c["fill_mismatch"].values()) or c["distinct_files"] != 1:
            fails.append(f"{script} {c['case']}: {json.dumps(c)[:300]}")
want = {
    "gate_probes2.py": {"zone_layers_reversed_no_uuid": "done", "via_in_filled_footprint_zone": "rejected"},
    "join_probes.py": {"no_zone_track": "refused", "never_filled_track": "rejected", "never_filled_via": "rejected", "stale_fill_track": "rejected", "stale_fill_via": "rejected",
                       "islands_kept_never_filled_track": "rejected", "fp_zone_never_filled_via": "rejected", "track_on_B_under_F_zone": "refused"},
    "closure_probes.py": {"move_stitching_via": "done", "move_feed_via": "rejected", "set_width_fill_fed_track": "done", "move_stitching_via_out_of_pour": "refused", "rejected_run_files_removed": "done"},
    "prewire_probes.py": {"single_segment_stub": "done", "two_segment_stub": "done", "two_segment_stub_join_far": "done", "free_end_also_reached": "done"},
}
for script, cases in want.items():
    rc, got = lines(script)
    seen = {c["case"]: c for c in got if isinstance(c, dict) and "case" in c}
    for name, outcome in cases.items():
        c = seen.get(name)
        if c is None:
            fails.append(f"{script} {name}: no result (exit {rc})")
        elif c.get("outcome") != outcome:
            fails.append(f"{script} {name}: {c.get('outcome')} (want {outcome}) {json.dumps(c)[:250]}")
    for c in seen.values():
        if "ok" in c and c["ok"] is not True:
            fails.append(f"{script} {c['case']}: {json.dumps(c)[:250]}")
        if c.get("case") == "rejected_run_files_removed" and any(f.startswith("out.rejected") for f in c.get("files", [])):
            fails.append(f"{script} rejected_run_files_removed: {c['files']}")
# diff probes print [name, PASS/FAIL, ...]
rc, got = lines("diff_probes.py")
if rc or not got:
    fails.append(f"diff_probes.py: exit {rc}, {len(got)} cases")
for c in got:
    if isinstance(c, list) and len(c) > 1 and c[1] != "PASS":
        fails.append(f"diff_probes.py {c[0]}: {json.dumps(c)[:250]}")
print(json.dumps({"ok": not fails, "failed": fails}, indent=1))
sys.exit(0 if not fails else 1)
