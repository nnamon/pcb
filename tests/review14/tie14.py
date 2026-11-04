"""Review 14: net-tie closures (review 13, findings 10, 11 and 14) with through-hole and bottom-side pads, and valid
ties the new refusals must still accept. One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 tie14.py workdir
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r14lib as L  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

TOML = """[[net_tie]]
footprint = "T1"
pads = ["1", "2"]
absorb_net = "X"
absorb_vias_net = "B"
"""
G1 = {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]}
THT = lambda num, x, y, net: {"num": num, "at": (x, y), "size": (1.6, 1.6), "shape": "circle", "kind": "tht", "drill": 0.8, "net": net}
T1_THT = {"ref": "T1", "at": (30, 20), "pads": [THT("1", 27, 20, "A"), THT("2", 33, 20, "B")]}


def run(name, spec, toml=TOML):
    d = L.build(os.path.join(work, name), spec, toml)
    v, code, prob, out = L.zone(d)
    res = {}
    if v.get("outcome") in ("done", "rejected"):
        r = L.inspect(v["data"]["written"])
        res = dict(t1_copper=sorted((c["layer"], [round(x, 2) for x in c["a"]], [round(x, 2) for x in c["b"]]) for c in r["fps"]["T1"]["copper"]),
                   tracks=sorted((t["net"], t["layer"]) for t in r["tracks"]), pads={p["num"]: p["net"] for p in r["fps"]["T1"]["pads"]},
                   x_gone="X" not in r["nets"], group=L.tie_groups(v["data"]["written"], "T1"))
    L.emit(name, contract=prob, **L.summary(v), **res)


# 1. through-hole tie pads: the coil leaves pad 1 on B.Cu, crosses to F.Cu at a via, and reaches pad 2 on F.Cu
run("tht_tie", {"fps": [T1_THT, G1], "tracks": [(27, 20, 30, 22, "X", 0.25, "B.Cu"), (30, 22, 33, 20, "X", 0.25, "F.Cu")], "vias": [(30, 22, "X")]},
    TOML.replace('["1", "2"]', '["1", "2", "3"]'))

# 2. a B.Cu run that passes through a through-hole pad of C on another part: real copper on C's pad on B.Cu; it must
#    not become tie copper or a done run
run("tht_other_net", {"fps": [T1_THT, G1, {"ref": "U3", "at": (30, 24), "pads": [THT("1", 30, 24, "C")]}],
                      "tracks": [(27, 20, 30, 24, "X", 0.25, "B.Cu"), (30, 24, 33, 20, "X", 0.25, "B.Cu")]})

# 3. a bottom-side SMD tie with its run on B.Cu, under an F.Cu SMD pad of C on another part: one run, tie copper
T1_BOT = {"ref": "T1", "at": (30, 20), "side": "bottom", "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"}]}
run("bottom_under_top_pad", {"fps": [T1_BOT, G1, {"ref": "U3", "at": (30, 22), "pads": [{"num": "1", "at": (30, 22), "size": (1.2, 1.2), "net": "C"}]}],
                             "tracks": [(27, 20, 30, 22, "X", 0.25, "B.Cu"), (30, 22, 33, 20, "X", 0.25, "B.Cu")]})

# 4. absorb_vias_net names the absorbed net itself
run("vias_net_is_absorbed", {"fps": [T1_THT, G1], "tracks": [(27, 20, 30, 22, "X", 0.25, "B.Cu"), (30, 22, 33, 20, "X", 0.25, "F.Cu")], "vias": [(30, 22, "X")]},
    TOML.replace('absorb_vias_net = "B"', 'absorb_vias_net = "X"').replace('["1", "2"]', '["1", "2", "3"]'))

# 5. a valid tie plus an absorbed run between two pads of A on other parts: retyped to A, not refused
T1 = {"ref": "T1", "at": (30, 20), "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"}]}
run("retype_other_parts", {"fps": [T1, G1, {"ref": "U1", "at": (10, 30), "pads": [{"num": "1", "at": (10, 30), "net": "A"}]},
                                   {"ref": "U2", "at": (20, 30), "pads": [{"num": "1", "at": (20, 30), "net": "A"}]}],
                           "tracks": [(27, 20, 33, 20, "X", 0.25, "F.Cu"), (10, 30, 20, 30, "X", 0.25, "F.Cu")]})

# 6. the absorbed net reaches a pad of the tie footprint itself (T1 pad 3 on X)
run("absorbed_pad_on_tie", {"fps": [{"ref": "T1", "at": (30, 20), "pads": [{"num": "1", "at": (27, 20), "net": "A"}, {"num": "2", "at": (33, 20), "net": "B"},
                                                                           {"num": "3", "at": (30, 24), "net": "X"}]}, G1],
                            "tracks": [(27, 20, 33, 20, "X", 0.25, "F.Cu")]})
