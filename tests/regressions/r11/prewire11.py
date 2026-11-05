"""Review 11: prewire chain pruning against anchors the pruning does not see. Stand-in java from review 9.
usage: PCB_BIN=... python3 prewire11.py WORKDIR"""
import json
import os
import subprocess
import sys

T10 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
R9 = os.path.join(T10, "regressions", "r09")
LIB = os.path.join(T10, "lib")
sys.path.insert(0, LIB)
import kisexp  # noqa: E402

PCB = os.environ["PCB_BIN"]
JAR = "/opt/freerouting/freerouting-2.5.0.jar"
work = os.path.abspath(sys.argv[1])


def segs(path, net):
    if not path or not os.path.exists(path):
        return []
    src = kisexp.parse(open(path).read())
    return sorted((tuple(x.nums("start")), tuple(x.nums("end")), x.find("layer").arg(1)) for x in src.find_all("segment") if x.find("net").arg(1) == net)


def route(name, prewire, wires, extra="", args=("--rip", "L", "--nets", "L")):
    d = os.path.join(work, name)
    os.makedirs(d, exist_ok=True)
    b = os.path.join(d, "in.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(LIB, "synth_board.py"), "base", b], check=True, capture_output=True)
    if extra:
        t = open(b).read().rstrip()
        open(b, "w").write(t[:-1] + extra + "\n)\n")
    pf = os.path.join(d, "prewire.json")
    json.dump(prewire, open(pf, "w"))
    out = os.path.join(d, "out.kicad_pcb")
    for f in (out, out.replace(".kicad_pcb", ".rejected.kicad_pcb")):
        if os.path.exists(f):
            os.remove(f)
    for tag in ("route_region", "route_open"):
        subprocess.run([sys.executable, os.path.join(R9, "fake", "mkses.py"), os.path.join(d, tag + ".ses"), *wires], check=True)
    env = dict(os.environ, FAKE_DIR=d)
    cmd = [PCB, "--json", "route", b, "--region", "10,5,50,35", "--freerouting", JAR, "--java", os.path.join(R9, "fake", "fakejava"),
           "--work", os.path.join(d, "w"), "-o", out, "--prewire", pf, "--timeout", "60", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    js = json.loads(r.stdout)
    data = js.get("data", {})
    res = {"case": name, "outcome": js["outcome"], "exit": r.returncode, "error": js.get("error"), "pruned": data.get("pruned_segments"),
           "prewired": data.get("prewired"), "regressions": data.get("regressions"), "L_written": segs(data.get("written"), "L")}
    print(json.dumps(res, default=str))
    return res


T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)
# an L zone on F.Cu around pad L2 (45,20), never filled; the prewire stub starts inside it (joined by its outline)
ZONE = ('\t(zone (net "L") (layer "F.Cu") (uuid "11111111-2222-3333-4444-555555555555") (hatch edge 0.5) (connect_pads (clearance 0.2)) '
        '(min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts (xy 42 17) (xy 48 17) (xy 48 31) (xy 42 31))))')

# A: two-segment stub from inside the never-filled L zone, free at the far end; the router joins the far segment
route("anchor_unfilled_zone_two_seg", [T("L", "F.Cu", 0.2, (44, 28), (40, 28), (34, 28), free_end=True)], ["L:F.Cu:0.2:20,20;37,28"], extra=ZONE)
# B: the same, one segment (review 9's shape; the piece from the zone to the join was never prunable before)
route("anchor_unfilled_zone_one_seg", [T("L", "F.Cu", 0.2, (44, 28), (34, 28), free_end=True)], ["L:F.Cu:0.2:20,20;37,28"], extra=ZONE)
# C: control without the zone: stub from the pad L2
route("anchor_pad_two_seg", [T("L", "F.Cu", 0.2, (45, 20), (40, 28), (34, 28), free_end=True)], ["L:F.Cu:0.2:20,20;37,28"])
# D: router joins at the stub's bend (a vertex, not a segment's middle): the far segment is a dead tail
route("join_at_bend", [T("L", "F.Cu", 0.2, (45, 20), (40, 28), (34, 28), free_end=True)], ["L:F.Cu:0.2:20,20;40,28"])
# E: the stub's free end lies on input copper (the S track at y 30), router joins mid-stub
route("free_end_on_other_input", [T("L", "F.Cu", 0.2, (45, 20), (40, 26), (34, 26), free_end=True)], ["L:F.Cu:0.2:20,20;37,26"])
