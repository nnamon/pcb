"""Prewire protection in pcb route (review 9, check 3). Real Freerouting unless a case gives sessions for the fake.
usage: prewire_probes.py pcb work [case ...]"""
import json
import os
import subprocess
import sys

here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(here, "lib"))
from contract_check import check  # noqa: E402
import kisexp  # noqa: E402

pcb, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
only = sys.argv[3:]
JAR = "/opt/freerouting/freerouting-2.5.0.jar"
FJ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake", "fakejava")
MK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake", "mkses.py")


def segs(path, net):
    if not path or not os.path.exists(path):
        return []
    src = kisexp.parse(open(path).read())
    return [(tuple(x.nums("start")), tuple(x.nums("end")), x.find("layer").arg(1), x.nums("width")[0]) for x in src.find_all("segment") if x.find("net").arg(1) == net]


def vias(path, net):
    src = kisexp.parse(open(path).read())
    return [tuple(x.nums("at")) for x in src.find_all("via") if x.find("net").arg(1) == net]


def has(path, net, a, c, width=None, layer=None):
    return any(sorted([s, e]) == sorted([a, c]) and (width is None or abs(w - width) < 1e-6) and (layer is None or l == layer) for s, e, l, w in segs(path, net))


def route(name, variant, args, prewire, sessions=None, extra=""):
    d = os.path.join(work, name)
    os.makedirs(d, exist_ok=True)
    b = os.path.join(d, "in.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(here, "lib", "synth_board.py"), variant, b], check=True, capture_output=True)
    if extra:
        t = open(b).read().rstrip()
        open(b, "w").write(t[:-1] + extra + ")\n")
    pf = os.path.join(d, "prewire.json")
    json.dump(prewire, open(pf, "w"))
    out = os.path.join(d, "out.kicad_pcb")
    for f in (out, out.replace(".kicad_pcb", ".rejected.kicad_pcb")):
        if os.path.exists(f):
            os.remove(f)
    cmd = [pcb, "--json", "route", b, "--region", "10,5,50,35", "--freerouting", JAR, "--work", os.path.join(d, "w"), "-o", out, "--prewire", pf, "--timeout", "120", *args]
    env = dict(os.environ)
    if sessions:
        env["FAKE_DIR"] = d
        cmd += ["--java", FJ]
        for tag, wires in sessions.items():
            subprocess.run([sys.executable, MK, os.path.join(d, tag + ".ses"), *wires], check=True)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    js, problems = check(r.stdout, r.returncode)
    data = js.get("data", {})
    return js, data, data.get("written"), problems, b


def report(name, ok, ev):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {ev}", flush=True)


def want(name):
    return not only or name in only


T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)

# 1. set_width on another W track than review 8's probe, W ripped, real router
if want("p1_set_width_middle_track"):
    js, d, dest, pr, b = route("p1_set_width_middle_track", "base", ["--rip", "W", "--nets", "W"], [dict(op="set_width", net="W", layer="F.Cu", start=[30, 10], end=[38, 10], to=0.5, **{"from": 0.4})])
    report("p1_set_width_middle_track", has(dest, "W", (30.0, 10.0), (38.0, 10.0), 0.5) and not pr, f"{js['outcome']} ripped={d.get('ripped_segments')} W={segs(dest, 'W')} {pr}")

# 2. prewire via plus track on ripped net N... N has no copper; use L: a prewire L via and B.Cu track inside the region
if want("p2_prewire_via_and_track_on_ripped_net"):
    js, d, dest, pr, b = route("p2_prewire_via_and_track_on_ripped_net", "base", ["--rip", "L", "--nets", "L"],
                               [T("L", "F.Cu", 0.2, (45, 20), (42, 22)), dict(op="add_via", net="L", at=[42, 22], size=0.8, drill=0.4), T("L", "B.Cu", 0.2, (42, 22), (35, 22), free_end=True)])
    ok = has(dest, "L", (45.0, 20.0), (42.0, 22.0)) and (42.0, 22.0) in vias(dest, "L") and any(l == "B.Cu" and (42.0, 22.0) in (s, e) for s, e, l, w in segs(dest, "L"))
    report("p2_prewire_via_and_track_on_ripped_net", ok and not pr, f"{js['outcome']} written={os.path.basename(dest or '')} regressions={d.get('regressions')} L={segs(dest, 'L')} vias={vias(dest, 'L') if dest else None}")

# 3. the router ends a wire in the middle of a prewire stub: the stub's far piece is a tail, but prewire, so kept
if want("p3_router_joins_middle_of_prewire_stub"):
    js, d, dest, pr, b = route("p3_router_joins_middle_of_prewire_stub", "base", ["--rip", "L", "--nets", "L"],
                               [T("L", "F.Cu", 0.2, (45, 20), (40, 22), free_end=True)],
                               sessions={"route_region": ["L:F.Cu:0.2:20,20;42.5,21"]})
    # the stub's free end past the router's join goes; the rest of the stub stays (review 9, 8)
    report("p3_router_joins_middle_of_prewire_stub", js["outcome"] == "done" and not has(dest, "L", (42.5, 21.0), (40.0, 22.0)) and has(dest, "L", (45.0, 20.0), (42.5, 21.0)),
           f"{js['outcome']} pruned={d.get('pruned_segments')} split={d.get('split_tracks')} regressions={d.get('regressions')} L={segs(dest, 'L')}")

# 4. a prewire track that lies wholly inside the rip margin on a ripped net, met by ripped copper at one end
#    (the 'tail' rule): prewire L track continuing the ripped (20,20)-(45,20) track's end
if want("p4_prewire_tail_on_ripped_end"):
    js, d, dest, pr, b = route("p4_prewire_tail_on_ripped_end", "base", ["--rip", "L", "--nets", "L"],
                               [T("L", "B.Cu", 0.2, (30, 24), (33, 26), free_end=True)],
                               sessions={"route_region": ["L:F.Cu:0.2:20,20;45,20"]})
    report("p4_prewire_tail_on_ripped_end", has(dest, "L", (30.0, 24.0), (33.0, 26.0)), f"{js['outcome']} pruned={d.get('pruned_segments')} regressions={d.get('regressions')} L={segs(dest, 'L')}")

# 5. input copper must not be counted as prewire: a prewire op on W leaves L's input tracks rippable
if want("p5_input_still_ripped"):
    js, d, dest, pr, b = route("p5_input_still_ripped", "base", ["--rip", "L", "--nets", "L"],
                               [dict(op="set_width", net="W", layer="F.Cu", start=[30, 10], end=[38, 10], to=0.45, **{"from": 0.4})],
                               sessions={"route_region": ["L:F.Cu:0.2:20,20;30,22;45,20"]})
    report("p5_input_still_ripped", not has(dest, "L", (20.0, 20.0), (45.0, 20.0)) and d.get("ripped_segments") == 2, f"{js['outcome']} ripped={d.get('ripped_segments')} L={segs(dest, 'L')}")

# 6. imported-style board (no uuids): prewire re-adds an input track with the same text after deleting it; and a
#    duplicate laid by the prewire over an input track
NOUUID = '\t(segment (start 12 32) (end 40 32) (width 0.2) (layer "F.Cu") (net "S"))\n\t(segment (start 40 32) (end 45 30) (width 0.2) (layer "F.Cu") (net "S"))\n'
if want("p6_identical_readd_counts_as_input"):
    js, d, dest, pr, b = route("p6_identical_readd_counts_as_input", "base", ["--rip", "S", "--nets", "S"],
                               [DT := dict(op="delete", what="track", net="S", layer="F.Cu", start=[12, 32], end=[40, 32]), T("S", "F.Cu", 0.2, (12, 32), (40, 32))],
                               sessions={"route_region": []}, extra=NOUUID)
    report("p6_identical_readd_counts_as_input (NOTE only)", True, f"{js['outcome']} ripped={d.get('ripped_segments')} prewired={d.get('prewired')} S={segs(dest, 'S')}")
