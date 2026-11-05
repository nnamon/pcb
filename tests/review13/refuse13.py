"""Review 13: refusals, paths and the DRC allowance of `pcb zone`, each run checked against the output contract.
One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 refuse13.py workdir
"""
import hashlib
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import r13lib as L  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)

BASE = {"fps": [{"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
                {"ref": "G2", "at": (50, 30), "pads": [{"num": "1", "at": (50, 30), "net": "GND"}]},
                {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]},
                {"ref": "P2", "at": (40, 20), "pads": [{"num": "1", "at": (40, 20), "net": "P"}]}],
        "tracks": [(10, 20, 40, 20, "P", 0.3, "F.Cu")]}
GOOD = """[[zone]]
net = "GND"
layers = ["F.Cu"]
clearance_mm = 0.3

[nets.P]
fill_grow_mm = 1.0
"""


def digest(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def case(name, body, outname=None, work_arg=None, project=None, prep=None, timeout=120):
    d = L.build(os.path.join(work, name), BASE, body)
    if prep:
        prep(d)
    before = digest(os.path.join(d, "board.kicad_pcb"))
    out = outname(d) if callable(outname) else (outname or os.path.join(d, "out.kicad_pcb"))
    w = work_arg(d) if callable(work_arg) else (work_arg or os.path.join(d, "work"))
    args = [L.PCB, "--json", "zone", "--project", project(d) if project else d, "-o", out, "--work", w]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        v, prob = L.check(r.stdout, r.returncode)
        v = v or {}
    except subprocess.TimeoutExpired:
        v, prob = {"outcome": "timeout"}, []
    after = digest(os.path.join(d, "board.kicad_pcb"))
    L.emit(name, contract=prob, **L.summary(v), input_changed=before != after and out != os.path.join(d, "board.kicad_pcb"),
           out_exists=os.path.isfile(out), files=sorted(f for f in os.listdir(d) if f.endswith(".kicad_pcb")))
    return d


# config refusals
case("unknown_key", GOOD + "\n[fill]\nlayer = [\"F.Cu\"]\n")
case("zone_clearance_inf", GOOD.replace("clearance_mm = 0.3", "clearance_mm = inf"))
case("thermal_gap_inf", GOOD.replace("clearance_mm = 0.3", "clearance_mm = 0.3\nthermal = { gap_mm = inf, spoke_mm = 0.5 }"))
case("keepout_rect_inf", GOOD + '\n[[keepout]]\nname = "k"\nrect = [0, 0, inf, 10]\nlayers = "all"\nforbid = ["pour"]\n')
case("zone_clearance_nan", GOOD.replace("clearance_mm = 0.3", "clearance_mm = nan"))
case("min_width_zero", GOOD.replace("clearance_mm = 0.3", "clearance_mm = 0.3\nmin_width_mm = 0"))
case("connect_bad", GOOD.replace("clearance_mm = 0.3", "clearance_mm = 0.3\nconnect = \"full\""))
case("fill_layer_missing", GOOD + '\n[fill]\nlayers = ["In1.Cu"]\n')
case("keepout_layer_missing", GOOD + '\n[[keepout]]\nname = "k"\nrect = [0, 0, 5, 5]\nlayers = ["In2.Cu"]\nforbid = ["pour"]\n')
case("keepout_layers_word", GOOD + '\n[[keepout]]\nname = "k"\nrect = [0, 0, 5, 5]\nlayers = "every"\nforbid = ["pour"]\n')
case("stitch_net_missing", GOOD + '\n[[stitch]]\nnet = "NOPE"\npitch_mm = 5\nsize_mm = 0.6\ndrill_mm = 0.3\n')
case("stitch_drill_ge_size", GOOD + '\n[[stitch]]\nnet = "GND"\npitch_mm = 5\nsize_mm = 0.3\ndrill_mm = 0.3\n')
case("allow_max_negative", GOOD + '\n[[drc_allow]]\nkind = "clearance"\nmax = -1\nwhy = "x"\n')
case("allow_unknown_net", GOOD + '\n[[drc_allow]]\nkind = "clearance"\nnets = ["NOPE"]\nmax = 1\nwhy = "x"\n')
case("allow_unknown_kind", GOOD + '\n[[drc_allow]]\nkind = "clearence"\nmax = 1\nwhy = "x"\n')
case("width_rule_unknown_net", GOOD + '\n[nets.OLD]\nwidth_mm = 0.5\n')
case("pad_override_no_dot", GOOD + '\n[[pad_override]]\npad = "G1"\nzone_connection = "none"\n')
case("schema_2", GOOD, prep=lambda d: open(os.path.join(d, "pcb.toml"), "w").write((L.HEAD.format(layers=2) + "\n" + GOOD).replace("schema = 1", "schema = 2")))
case("board_missing", GOOD, prep=lambda d: os.remove(os.path.join(d, "board.kicad_pcb")))
case("no_pcb_toml", GOOD, prep=lambda d: os.remove(os.path.join(d, "pcb.toml")))
case("project_as_file", GOOD, project=lambda d: os.path.join(d, "pcb.toml"))

# paths
case("out_is_folder", GOOD, outname=lambda d: d)
case("out_folder_missing", GOOD, outname=lambda d: os.path.join(d, "nope", "out.kicad_pcb"))
case("work_is_file", GOOD, work_arg=lambda d: os.path.join(d, "pcb.toml"))
case("out_is_candidate", GOOD, outname=lambda d: os.path.join(d, "work", "candidate.kicad_pcb"), prep=lambda d: os.makedirs(os.path.join(d, "work")))
case("out_default_overwrites", GOOD, outname=lambda d: os.path.join(d, "board.kicad_pcb"))
# a rejected result with the input as output: the input must stay, the result goes beside it
case("rejected_onto_input", GOOD + '\n[[keepout]]\nname = "notrack"\nrect = [20, 18, 30, 22]\nlayers = "all"\nforbid = ["track"]\n', outname=lambda d: os.path.join(d, "board.kicad_pcb"))

# the DRC allowance: GND pads G1..G4 (through-hole) joined only by the F.Cu pour, AGND pads A1, A2 only by the B.Cu
# pour; a pad override `none` cuts a pad off, one unconnected item each
ABASE = {"fps": [{"ref": f"G{i}", "at": (x, y), "pads": [{"num": "1", "at": (x, y), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "GND"}]}
                 for i, (x, y) in enumerate([(5, 5), (55, 5), (5, 35), (55, 35)], 1)] +
                [{"ref": f"A{i}", "at": (x, y), "pads": [{"num": "1", "at": (x, y), "size": (1.7, 1.7), "shape": "circle", "kind": "tht", "drill": 1.0, "net": "AGND"}]}
                 for i, (x, y) in enumerate([(20, 20), (40, 20)], 1)]}
AZ = """[[zone]]
net = "GND"
layers = ["F.Cu"]
clearance_mm = 0.3

[[zone]]
net = "AGND"
layers = ["B.Cu"]
clearance_mm = 0.3
"""


def cut(*pads):
    return "".join(f'\n[[pad_override]]\npad = "{p}.1"\nzone_connection = "none"\n' for p in pads)


def allow(kind, nets, m):
    n = "" if nets is None else "nets = [" + ", ".join(f'"{x}"' for x in nets) + "]\n"
    return f'\n[[drc_allow]]\nkind = "{kind}"\n{n}max = {m}\nwhy = "review 13"\n'


def acase(name, body, chain_from=None):
    d = os.path.join(work, name)
    if chain_from:
        os.makedirs(d)
        shutil.copy(chain_from, os.path.join(d, "board.kicad_pcb"))
        shutil.copy(os.path.join(os.path.dirname(chain_from), "board.kicad_pro"), d)
        L.write_toml(d, 2, body)
    else:
        L.build(d, ABASE, body)
    v, code, prob, out = L.zone(d)
    dd = v.get("data") or {}
    L.emit(name, contract=prob, **L.summary(v), before=dd.get("drc_total_before"), after=dd.get("drc_total_after"))
    return out if v.get("outcome") == "done" else None


# the zoned control board is the input of every allowance case, so a cut-off pad is new
z0 = acase("allow_control", AZ)
if z0:
    acase("allow_none", AZ + cut("G2"), chain_from=z0)
    acase("allow_at_max_1", AZ + cut("G2") + allow("unconnected_items", ["GND"], 1), chain_from=z0)
    acase("allow_at_max_2", AZ + cut("G2", "G3") + allow("unconnected_items", ["GND"], 2), chain_from=z0)
    acase("allow_above_max_2", AZ + cut("G2", "G3", "G4") + allow("unconnected_items", ["GND"], 2), chain_from=z0)
    acase("allow_any_nets_max_1", AZ + cut("G2", "A2") + allow("unconnected_items", None, 1), chain_from=z0)
    acase("allow_with_real_regression", AZ + cut("G2", "A2") + allow("unconnected_items", ["GND"], 1), chain_from=z0)
    acase("allow_kind_not_grown", AZ + allow("clearance", ["GND"], 3), chain_from=z0)
    acase("allow_wrong_net", AZ + cut("G2") + allow("unconnected_items", ["AGND"], 5), chain_from=z0)
    acase("allow_unknown_kind_typo", AZ + cut("G2") + allow("unconnected_item", ["GND"], 5), chain_from=z0)
    # each run may add up to max over its own input: two runs of max 1 leave two above the first input
    first = acase("ratchet_1", AZ + cut("G2") + allow("unconnected_items", ["GND"], 1), chain_from=z0)
    if first:
        acase("ratchet_2", AZ + cut("G2", "G3") + allow("unconnected_items", ["GND"], 1), chain_from=first)
