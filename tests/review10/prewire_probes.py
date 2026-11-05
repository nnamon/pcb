"""Review 10: prewire free-end pruning in pcb route, driven by review 9's stand-in java (crafted sessions).
usage: python3 prewire_probes.py WORKDIR"""
import json
import os
import subprocess
import sys

R9 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review9")
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
import kisexp  # noqa: E402

PCB = os.environ.get("PCB_BIN", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "target", "release", "pcb"))
JAR = "/opt/freerouting/freerouting-2.5.0.jar"
work = os.path.abspath(sys.argv[1])


def segs(path, net):
    if not path or not os.path.exists(path):
        return []
    src = kisexp.parse(open(path).read())
    return sorted((tuple(x.nums("start")), tuple(x.nums("end")), x.find("layer").arg(1)) for x in src.find_all("segment") if x.find("net").arg(1) == net)


def route(name, prewire, wires, args=("--rip", "L", "--nets", "L")):
    d = os.path.join(work, name)
    os.makedirs(d, exist_ok=True)
    b = os.path.join(d, "in.kicad_pcb")
    subprocess.run([sys.executable, os.path.join(LIB, "synth_board.py"), "base", b], check=True, capture_output=True)
    pf = os.path.join(d, "prewire.json")
    json.dump(prewire, open(pf, "w"))
    out = os.path.join(d, "out.kicad_pcb")
    for f in (out, out.replace(".kicad_pcb", ".rejected.kicad_pcb")):
        if os.path.exists(f):
            os.remove(f)
    subprocess.run([sys.executable, os.path.join(R9, "fake", "mkses.py"), os.path.join(d, "route_region.ses"), *wires], check=True)
    env = dict(os.environ, FAKE_DIR=d)
    cmd = [PCB, "--json", "route", b, "--region", "10,5,50,35", "--freerouting", JAR, "--java", os.path.join(R9, "fake", "fakejava"),
           "--work", os.path.join(d, "w"), "-o", out, "--prewire", pf, "--timeout", "60", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    js = json.loads(r.stdout)
    data = js.get("data", {})
    print(json.dumps({"case": name, "outcome": js["outcome"], "exit": r.returncode, "error": js.get("error"), "pruned": data.get("pruned_segments"),
                      "split": data.get("split_tracks"), "regressions": data.get("regressions"), "L": segs(data.get("written"), "L")}))


T = lambda net, layer, w, *pts, **kw: dict(op="add_track", net=net, layer=layer, width=w, points=[list(p) for p in pts], **kw)

# 1. control: review 9's single-segment stub, router joins its middle
route("single_segment_stub", [T("L", "F.Cu", 0.2, (45, 20), (40, 22), free_end=True)], ["L:F.Cu:0.2:20,20;42.5,21"])
# 2. a two-segment stub, free at the far end; the router joins the segment next to the pad
route("two_segment_stub", [T("L", "F.Cu", 0.2, (45, 20), (40, 22), (36, 22), free_end=True)], ["L:F.Cu:0.2:20,20;42.5,21"])
# 3. two-segment stub, router joins the free segment (control for 2)
route("two_segment_stub_join_far", [T("L", "F.Cu", 0.2, (45, 20), (40, 22), (36, 22), free_end=True)], ["L:F.Cu:0.2:20,20;38,22"])
# 4. a stub whose free end the router also reaches: nothing should be pruned
route("free_end_also_reached", [T("L", "F.Cu", 0.2, (45, 20), (40, 22), free_end=True)], ["L:F.Cu:0.2:20,20;42.5,21", "L:F.Cu:0.2:42.5,21;40,22"])
