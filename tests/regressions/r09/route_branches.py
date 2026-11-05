"""pcb route's choice between runs, driven by a fake java that writes chosen sessions (review 9, check 6).
usage: route_branches.py pcb work [case ...]
Base board, region 10,5,50,35, --nets N,S. N1 (20,15)-N2 (40,15) unrouted; S3 (30,34) unconnected; L runs on F.Cu
along y 20 from x 20 to 45."""
import json
import os
import subprocess
import sys

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(here, "lib"))
from contract_check import check  # noqa: E402

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
only = sys.argv[3:]
os.makedirs(work, exist_ok=True)
FJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake", "fakejava")
MK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake", "mkses.py")
S_OK = "S:F.Cu:0.2:30,34;30,30"
S_SHORT_LOOP = "S:F.Cu:0.2:25,30;25,14.5;35,14.5;35,30"  # both ends on the S track, crosses L twice
N_OK = "N:F.Cu:0.2:20,15;40,15"
N_SHORT = "N:F.Cu:0.2:20,15;30,20;40,15"  # crosses L at (30,20)

CASES = {
    # name: (region session wires or 'fail'/'sleep', open session, expect)
    "first_closes_all": ([S_OK, N_OK], None, dict(attempts=1, used=0, outcome="done")),
    "preferred_open_rejected_region_kept": ([], [N_SHORT], dict(attempts=2, used=0, outcome="done")),
    "preferred_region_rejected_open_kept": ([S_OK, S_SHORT_LOOP], [], dict(attempts=2, used=1, outcome="done")),
    "both_rejected": ([S_OK, S_SHORT_LOOP], [S_OK, S_SHORT_LOOP, N_OK], dict(attempts=2, used=1, outcome="rejected")),
    "tie_first_kept": ([S_OK], [N_OK], dict(attempts=2, used=0, outcome="done")),
    "second_fails": ([S_OK], "fail", dict(attempts=1, used=0, outcome="done", warn="second-run-failed")),
    "second_times_out": ([S_OK], "sleep", dict(attempts=1, used=0, outcome="done", warn="second-run-failed")),
    "first_fails": ("fail", [N_OK], dict(outcome="failed")),
}


def run(name, reg, opn, exp):
    d = os.path.join(work, name)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        p = os.path.join(d, f)
        if os.path.isfile(p):
            os.remove(p)
    b = os.path.join(d, "in.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "lib", "synth_board.py"), "base", b], check=True, capture_output=True)
    for tag, spec in (("route_region", reg), ("route_open", opn)):
        if spec == "fail":
            open(os.path.join(d, tag + ".fail"), "w").write("")
        elif spec == "sleep":
            open(os.path.join(d, tag + ".sleep"), "w").write("30")
            subprocess.run([sys.executable, MK, os.path.join(d, tag + ".ses")], check=True)
        elif spec is not None:
            subprocess.run([sys.executable, MK, os.path.join(d, tag + ".ses"), *spec], check=True)
    out = os.path.join(d, "out.kicad_pcb")
    env = dict(os.environ, FAKE_DIR=d)
    r = subprocess.run([pcb, "--json", "route", b, "--region", "10,5,50,35", "--nets", "N,S", "--freerouting", "/opt/freerouting/freerouting-2.5.0.jar", "--java", FJ,
                        "--work", os.path.join(d, "w"), "-o", out, "--timeout", "10"], capture_output=True, text=True, env=env)
    js, problems = check(r.stdout, r.returncode)
    data = js.get("data", {}) if js else {}
    files = sorted(f for f in os.listdir(d) if f.endswith((".kicad_pcb", ".kicad_pro")))
    got = dict(outcome=js and js["outcome"], attempts=len(data.get("attempts", [])), used=data.get("attempt_used"),
               written=os.path.basename(data.get("written", "") or ""), regressions=data.get("regressions"), still_open=data.get("still_open"),
               warnings=[w["code"] for w in (js or {}).get("warnings", [])], files=files, error=(js or {}).get("error"),
               attempts_detail=data.get("attempts"))
    ok = not problems and got["outcome"] == exp["outcome"]
    if exp["outcome"] != "failed":
        ok = ok and got["attempts"] == exp["attempts"] and got["used"] == exp["used"]
        # the written file exists; a done result leaves no .rejected; a rejected result leaves no out
        wr = got["written"]
        ok = ok and wr in files
        if got["outcome"] == "done":
            ok = ok and "out.rejected.kicad_pcb" not in files and not got["regressions"]
        if got["outcome"] == "rejected":
            ok = ok and "out.kicad_pcb" not in files and got["regressions"]
        if exp.get("warn"):
            ok = ok and exp["warn"] in got["warnings"]
        # the written board is the attempt reported: count its N and S segments against attempts[used]
        if wr in files and got["attempts_detail"]:
            src = open(os.path.join(d, wr)).read()
            orig = open(b).read()
            added = src.count("(segment") - orig.count("(segment")
            want = got["attempts_detail"][got["used"]]["added_segments"]
            got["added_in_file"] = added
            # the file holds the reported run's new segments; split kept tracks add pieces (a track split at k points
            # becomes k + 1), and ripped and pruned tracks leave, so only a lower bound is exact
            got["min_in_file"] = want - data.get("ripped_segments", 0) - data.get("pruned_segments", 0)
            ok = ok and want == data.get("added_segments") and added >= got["min_in_file"]
    print(f"{'PASS' if ok else 'FAIL'} {name}: {json.dumps(got)}{' CONTRACT ' + str(problems) if problems else ''}", flush=True)


for name, (reg, opn, exp) in CASES.items():
    if only and name not in only:
        continue
    run(name, reg, opn, exp)
