"""Review 8's probes (joined the suite from the reviewer's scripts) for `pcb init` and `pcb status` (review 8).

Usage: python3 project_probes.py pcb-binary workdir
"""
import json
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "lib"))
from contract_check import check  # noqa: E402

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
results = []


def report(name, ok, evidence):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {evidence}")


def run(*args, cwd=None):
    r = subprocess.run([pcb, "--json", *args], capture_output=True, text=True, cwd=cwd)
    d, problems = check(r.stdout, r.returncode)
    assert not problems, (args, problems, r.stdout[-300:])
    return d


def synth(path, variant="base"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run([sys.executable, os.path.join(here, "..", "..", "lib", "synth_board.py"), variant, path], check=True, capture_output=True)


def short(d):
    return f"outcome {d['outcome']} {d.get('error', {}).get('code', '')} problems={d['data'].get('problems')} warnings={[w['code'] for w in d['warnings']]}"


# 1. init from a board outside the project folder: `board` must be relative to pcb.toml, so status finds the board
synth(os.path.join(work, "p1", "boards", "b.kicad_pcb"))
os.makedirs(os.path.join(work, "p1", "proj"))
d = run("init", "boards/b.kicad_pcb", "-o", "proj/pcb.toml", cwd=os.path.join(work, "p1"))
written_board = d["data"].get("board")
s = run("status", "--project", os.path.join(work, "p1", "proj"), "--no-drc")
report("init_board_path_relative_to_pcb_toml", s["outcome"] == "done", f"init wrote board = {written_board!r}; status: {short(s)} {s.get('error', {}).get('message', '')[:120]}")

# 2. init from a board whose file name does not end in .kicad_pcb: init must not write a file status refuses
synth(os.path.join(work, "p2", "b.kicad_pcb"))
shutil.move(os.path.join(work, "p2", "b.kicad_pcb"), os.path.join(work, "p2", "b.kicad_pcb.v2"))
d = run("init", os.path.join(work, "p2", "b.kicad_pcb.v2"))
s = run("status", "--project", os.path.join(work, "p2"), "--no-drc")
report("init_output_passes_status_odd_name", not (d["outcome"] == "done" and s["outcome"] == "refused"), f"init {d['outcome']}; status {short(s)}")

# 3. init with --name "" : same rule
synth(os.path.join(work, "p3", "b.kicad_pcb"))
d = run("init", os.path.join(work, "p3", "b.kicad_pcb"), "--name", "")
s = run("status", "--project", os.path.join(work, "p3"), "--no-drc")
report("init_output_passes_status_empty_name", not (d["outcome"] == "done" and s["outcome"] == "refused"), f"init {d['outcome']}; status {short(s)}")

# 4. a 4-layer board with an inner layer typed "mixed": KiCad counts it as copper, so init must say 4 layers
synth(os.path.join(work, "p4", "b.kicad_pcb"), "four")
p4 = os.path.join(work, "p4", "b.kicad_pcb")
t = open(p4).read()
t = t.replace('(4 "In1.Cu" signal)', '(4 "In1.Cu" mixed)', 1)
open(p4, "w").write(t)
d = run("init", p4)
report("init_counts_mixed_copper_layer", d["data"].get("layers") == 4, f"init layers={d['data'].get('layers')} fab={d['data'].get('fab')}")

# 5. VERSION and TAGS.tsv: mismatch warned; recorded tag found
synth(os.path.join(work, "repo", "proj", "design", "b.kicad_pcb"))
d = run("init", os.path.join(work, "repo", "proj", "design", "b.kicad_pcb"), "--name", "proj")
open(os.path.join(work, "repo", "proj", "VERSION"), "w").write("0.2.0\n")
open(os.path.join(work, "repo", "TAGS.tsv"), "w").write("tag\tcommit\tmessage\nproj-v0.1.0\tabc\tx\n")
s = run("status", "--project", os.path.join(work, "repo", "proj", "design"), "--no-drc")
report("version_mismatch_warned", "version-mismatch" in [w["code"] for w in s["warnings"]], short(s))
report("tag_found", s["data"]["tag"]["recorded"] is True, s["data"]["tag"])
# a tag that differs only by a prefix must not count
open(os.path.join(work, "repo", "TAGS.tsv"), "w").write("xproj-v0.1.0\tabc\tx\nproj-v0.1.0-rc\tabc\tx\n")
s = run("status", "--project", os.path.join(work, "repo", "proj", "design"), "--no-drc")
report("tag_prefix_not_counted", s["data"]["tag"]["recorded"] is False, s["data"]["tag"])

# 6. dates and ranges inside the file: an impossible date and a negative keep-out growth are problems
if not os.path.exists(os.path.join(work, "p3", "pcb.toml")):
    run("init", os.path.join(work, "p3", "b.kicad_pcb"), "--name", "p3")
base_toml = open(os.path.join(work, "p3", "pcb.toml")).read().replace('name = ""', 'name = "p3"')
bad = base_toml.replace("[decisions]", "[decisions]\nx = { text = \"t\", date = \"2026-13-45\" }", 1) + '\n[[keepout]]\nname = "k"\nrect = [0, 0, 10, 10]\ngrow_mm = -5\nlayers = "all"\n'
open(os.path.join(work, "p3", "pcb.toml"), "w").write(bad)
s = run("status", "--project", os.path.join(work, "p3"), "--no-drc")
report("impossible_date_is_a_problem", any("decisions.x" in p for p in s["data"].get("problems", [])), short(s))
report("negative_grow_is_a_problem", any("grow" in p for p in s["data"].get("problems", [])), short(s))

# 7. the board pcb.toml names is missing: refused as a config problem, not an I/O failure
open(os.path.join(work, "p3", "pcb.toml"), "w").write(base_toml.replace('board = "b.kicad_pcb"', 'board = "gone.kicad_pcb"'))
s = run("status", "--project", os.path.join(work, "p3"), "--no-drc")
report("missing_board_reported_as_config", s["outcome"] == "refused", f"outcome {s['outcome']} {s.get('error')}")

# 8. schema written as a float: the message names the schema value
open(os.path.join(work, "p3", "pcb.toml"), "w").write(base_toml.replace("schema = 1", "schema = 1.0"))
s = run("status", "--project", os.path.join(work, "p3"), "--no-drc")
report("schema_float_message", "no schema key" not in s.get("error", {}).get("message", ""), s.get("error", {}).get("message", "")[:150])

print(json.dumps({"probes": len(results), "failed": [r[0] for r in results if not r[1]]}))
sys.exit(0 if not [r for r in results if not r[1]] else 1)
