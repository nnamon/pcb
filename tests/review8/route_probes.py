"""Review 8's probes (joined the suite from the reviewer's scripts) for the M1 additions to `pcb route` (review 8): prewired copper on a ripped net, and --width.

Usage: python3 route_probes.py pcb-binary freerouting.jar workdir
"""
import json
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
from contract_check import check  # noqa: E402
import kisexp  # noqa: E402

pcb, jar, work = os.path.abspath(sys.argv[1]), sys.argv[2], os.path.abspath(sys.argv[3])
os.makedirs(work, exist_ok=True)
REGION = "10,5,50,35"
results = []


def report(name, ok, evidence):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {evidence}", flush=True)


def route(name, variant, args, prewire=None):
    b = os.path.join(work, f"{name}.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "..", "lib", "synth_board.py"), variant, b], check=True, capture_output=True)
    if prewire is not None:
        pf = os.path.join(work, f"{name}.prewire.json")
        json.dump(prewire, open(pf, "w"))
        args = args + ["--prewire", pf]
    out = os.path.join(work, f"{name}.out.kicad_pcb")
    r = subprocess.run([pcb, "--json", "route", b, "--region", REGION, "--freerouting", jar, "--work", os.path.join(work, name + "_w"), "-o", out, *args], capture_output=True, text=True)
    d, problems = check(r.stdout, r.returncode)
    assert not problems, problems
    return d, out


def segs(path, net):
    if not os.path.exists(path):
        return []
    src = kisexp.parse(open(path).read())
    return [(tuple(x.nums("start")), tuple(x.nums("end")), x.find("layer").arg(1), x.nums("width")[0]) for x in src.find_all("segment") if x.find("net").arg(1) == net]


def has(path, net, a, c, width=None):
    return any(sorted([s, e]) == sorted([a, c]) and (width is None or abs(w - width) < 1e-6) for s, e, _, w in segs(path, net))


# 1. prewire widens an input track of W (0.4 -> 0.5); W is ripped. The owner's 0.5 mm track must survive
d, out = route("prewire_width_rip", "base", ["--rip", "W", "--nets", "W"], [{"op": "set_width", "net": "W", "layer": "F.Cu", "start": [15, 10], "end": [30, 10], "from": 0.4, "to": 0.5}])
dest = d.get("written", out)
report("prewired_set_width_survives_rip", has(dest, "W", (15.0, 10.0), (30.0, 10.0), 0.5),
       f"outcome {d['outcome']}, ripped {d['data'].get('ripped_segments')}, W tracks in {os.path.basename(dest)}: {segs(dest, 'W')}")

# 2. prewire: delete all copies of an input track and lay it again (the duplicate_removed pattern); the net is ripped
d, out = route("prewire_readd_rip", "base", ["--rip", "W", "--nets", "W"], [{"op": "delete", "what": "track", "net": "W", "layer": "F.Cu", "start": [30, 10], "end": [38, 10], "all": True}, {"op": "add_track", "net": "W", "layer": "F.Cu", "width": 0.45, "points": [[30, 10], [38, 10]]}])
dest = d.get("written", out)
report("prewired_readd_survives_rip", has(dest, "W", (30.0, 10.0), (38.0, 10.0), 0.45),
       f"outcome {d['outcome']}, ripped {d['data'].get('ripped_segments')}, W tracks: {segs(dest, 'W')}")

# 3. prewire stub on L from pad L2, L ripped: the stub ends where ripped copper ended, so pruning may take it
d, out = route("prewire_stub_ripped_net", "base", ["--rip", "L", "--nets", "L"], [{"op": "add_track", "net": "L", "layer": "F.Cu", "width": 0.2, "points": [[45, 20], [45, 23]], "free_end": True}])
dest = d.get("written", out)
report("prewired_stub_not_pruned", has(dest, "L", (45.0, 20.0), (45.0, 23.0)),
       f"outcome {d['outcome']}, pruned {d['data'].get('pruned_segments')}, attempts {d['data'].get('attempts')}, L tracks: {segs(dest, 'L')}")

# 4. --width given twice for one net: the second silently wins (no refusal)
d, out = route("width_twice", "base", ["--nets", "N", "--width", "N=0.3", "--width", "N=0.25"])
report("width_twice_refused", d["outcome"] == "refused", f"outcome {d['outcome']}, net_widths {d['data'].get('net_widths')}")

print(json.dumps({"probes": len(results), "failed": [r[0] for r in results if not r[1]]}))
sys.exit(0 if not [r for r in results if not r[1]] else 1)
