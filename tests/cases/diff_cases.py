"""Cases for `pcb diff`, on the boards tests/cases/edit_cases.py writes (so each change is known from its
operations), plus a board read from a git revision.

Usage: python3 diff_cases.py pcb-binary edit-cases-workdir workdir
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402

pcb, ew, work = sys.argv[1:4]
os.makedirs(work, exist_ok=True)


def run(*args, cwd=None):
    r = subprocess.run([os.path.abspath(pcb), "--json", "diff", *args], capture_output=True, text=True, cwd=cwd)
    d, problems = check(r.stdout, r.returncode)
    return d, problems


E = lambda case, out=False: os.path.join(ew, f"{case}{'.out' if out else ''}.kicad_pcb")
results = {}
# name: (a, b, test on data)
CASES = {
    "identical": (E("join_n"), E("join_n"), lambda d: d["identical"] and not d["copper"] and not d["footprints"]),
    "added_track": (E("join_n"), E("join_n", True), lambda d: d["copper"] == {"N": {"tracks_added": 1, "tracks_removed": 0, "length_added_mm": 20.0, "length_removed_mm": 0.0, "vias_added": 0, "vias_removed": 0}} and not d["footprints"]),
    "tracks_and_vias": (E("join_n_through_vias"), E("join_n_through_vias", True), lambda d: (d["copper"]["N"]["tracks_added"], d["copper"]["N"]["vias_added"]) == (3, 2)),
    "width_change": (E("set_width"), E("set_width", True), lambda d: (d["copper"]["W"]["tracks_added"], d["copper"]["W"]["tracks_removed"]) == (1, 1)),
    "footprint_moved": (E("move_footprint"), E("move_footprint", True), lambda d: [(f["ref"], f["change"]) for f in d["footprints"]] == [("N2", "moved")] and not d["copper"]),
    "reversed": (E("join_n", True), E("join_n"), lambda d: d["copper"]["N"]["tracks_removed"] == 1),
}
for name, (a, b, test) in CASES.items():
    d, problems = run(a, b)
    results[name] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "done" and test(d["data"]) else f"unexpected: {json.dumps(d.get('data'))[:400]}")

# a git revision: commit the input, then compare HEAD:board with the edited file
g = os.path.join(work, "repo")
shutil.rmtree(g, ignore_errors=True)
os.makedirs(g)
shutil.copy(E("join_n"), os.path.join(g, "b.kicad_pcb"))
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
for c in (["init", "-q"], ["add", "b.kicad_pcb"], ["commit", "-q", "-m", "x"]):
    subprocess.run(["git", *c], cwd=g, check=True, capture_output=True, env=env)
shutil.copy(E("join_n", True), os.path.join(g, "b.kicad_pcb"))
d, problems = run("HEAD:b.kicad_pcb", "b.kicad_pcb", cwd=g)
results["git_revision"] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "done" and d["data"]["copper"].get("N", {}).get("tracks_added") == 1 else f"unexpected: {json.dumps(d.get('data'))[:300]}")
d, problems = run("HEAD:no-such.kicad_pcb", "b.kicad_pcb", cwd=g)
results["missing_revision_fails"] = "; ".join(problems) if problems else ("ok" if d["outcome"] == "failed" else f"outcome {d['outcome']}")
png = os.path.join(work, "diff.png")
d, problems = run(E("join_n"), E("join_n", True), "--png", png)
results["png"] = "; ".join(problems) if problems else ("ok" if os.path.getsize(png) > 1000 and d.get("written") == png else "no PNG")
bad = {k: v for k, v in results.items() if v != "ok"}
print(json.dumps({"ok": not bad, "cases": len(results), "failed": bad}, indent=1))
sys.exit(0 if not bad else 1)
