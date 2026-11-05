"""Review 14: fill closures (review 13, findings 1, 6 and 17) and the new `fill-overlap` warning, on synthetic boards.
Every result is compared with a KiCad refill of itself. One JSON line per case; check.py holds the verdicts.

Usage: PCB_BIN=pcb python3 fill14.py workdir
"""
import ast
import os
import re
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import r14lib as L  # noqa: E402
from shapely.geometry import box  # noqa: E402

work = sys.argv[1]
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def zone_uuid(name):
    """pcb's zone uuid for a name (FNV-1a, two seeds), as review 13's feature13 derives it."""
    def h(seed):
        x = 0xcbf29ce484222325 ^ seed
        for c in name.encode():
            x ^= c
            x = (x * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        return x
    a, b = h(1), h(2)
    return "%08x-%04x-4%03x-8%03x-%012x" % (a >> 32, (a >> 16) & 0xffff, a & 0xfff, (b >> 48) & 0xfff, b & 0xffffffffffff)


def cross(n1, n2):
    """Two nets crossing at (30, 22): n1 along y = 20, n2 down x = 30."""
    return {"layers": 2, "fps": [
        {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
        {"ref": "U1", "at": (20, 20), "pads": [{"num": "1", "at": (20, 20), "net": n1}]},
        {"ref": "U2", "at": (40, 20), "pads": [{"num": "1", "at": (40, 20), "net": n1}]},
        {"ref": "U3", "at": (30, 23), "pads": [{"num": "1", "at": (30, 23), "net": n2}]},
        {"ref": "U4", "at": (30, 35), "pads": [{"num": "1", "at": (30, 35), "net": n2}]}],
        "tracks": [(20, 20, 40, 20, n1, 0.3, "F.Cu"), (30, 23, 30, 35, n2, 0.3, "F.Cu")]}


def run_and_refill(name, spec, toml, code=None, edit=None):
    """Runs pcb zone; returns (reply, contract problems, written path, fill differences against a KiCad refill)."""
    d = L.build(os.path.join(work, name), spec, toml, code)
    if edit:
        p = os.path.join(d, "board.kicad_pcb")
        text = edit(open(p).read())
        open(p, "w").write(text)
    v, code_, prob, out = L.zone(d)
    diff = None
    if v.get("outcome") in ("done", "rejected"):
        w = v["data"]["written"]
        diff = L.fill_diff(w, L.refill(w, os.path.join(d, "refilled.kicad_pcb")))
    return v, prob, d, diff


# 1a. same-priority overlapping fills, net names picked so the name-derived uuids sort with and against file order
pairs = {"against": None, "with": None}
for i in range(80):
    n1, n2 = f"NA{i}", f"NB{i}"
    k = "against" if zone_uuid(f"pcb:fill:{n1}:F.Cu:0") > zone_uuid(f"pcb:fill:{n2}:F.Cu:0") else "with"
    pairs[k] = pairs[k] or (n1, n2)
for k, (n1, n2) in pairs.items():
    v, prob, d, diff = run_and_refill(f"same_prio_{k}", cross(n1, n2), f'[fill]\nlayers = ["F.Cu"]\n\n[nets.{n1}]\nfill_grow_mm = 3.0\n\n[nets.{n2}]\nfill_grow_mm = 3.0\n')
    L.emit(f"same_prio_{k}", contract=prob, **L.summary(v), refill_diff=diff)

# 1b. a hand-made copper zone of net H (priority 2, overlapping the P fill at priority 2) with uuids in odd forms:
#     upper case sorting high, lower case sorting low, legacy 8-digit, and none at all
HAND = {"layers": 2, "fps": [
    {"ref": "G1", "at": (5, 5), "pads": [{"num": "1", "at": (5, 5), "net": "GND"}]},
    {"ref": "P1", "at": (10, 20), "pads": [{"num": "1", "at": (10, 20), "net": "P"}]},
    {"ref": "P2", "at": (50, 20), "pads": [{"num": "1", "at": (50, 20), "net": "P"}]},
    {"ref": "H1", "at": (30, 24), "pads": [{"num": "1", "at": (30, 24), "net": "H"}]}],
    "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu")]}
HZ = """
z = pcbnew.ZONE(b); z.SetLayer(pcbnew.F_Cu); z.SetNet(net("H")); z.SetAssignedPriority(2); z.SetZoneName("handH")
z.SetLocalClearance(mm(0.3)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
o = z.Outline(); o.NewOutline()
for x, y in [(22, 17), (38, 17), (38, 30), (22, 30)]:
    o.Append(mm(x), mm(y))
b.Add(z)
"""


def set_hand_uuid(u):
    def ed(t):
        i = t.index('(name "handH")')
        s = t.rfind("(zone", 0, i)
        seg = t[s:i]
        if u is None:
            seg2 = re.sub(r'\s*\(uuid "[^"]*"\)', "", seg, count=1)
        else:
            seg2 = re.sub(r'\(uuid "[^"]*"\)', f'(uuid "{u}")', seg, count=1)
        return t[:s] + seg2 + t[i:]
    return ed


PT = '[fill]\nlayers = ["F.Cu"]\n\n[nets.P]\nfill_grow_mm = 3.0\n'
for name, u in [("hand_upper_high", "FFFFFFFF-FFFF-4FFF-8FFF-FFFFFFFFFFFF"), ("hand_upper_mid", "ABCDEF01-2345-4678-89AB-CDEF01234567"),
                ("hand_lower_low", "00000000-0000-4000-8000-000000000001"), ("hand_legacy", "ffffffff"), ("hand_no_uuid", None)]:
    v, prob, d, diff = run_and_refill(name, HAND, PT, HZ, set_hand_uuid(u))
    res = {}
    if diff is not None and u is None:
        # a zone with no uuid gets a random one at every load: refill twice more to see whether the result moves
        w = v["data"]["written"]
        res["refill_runs_differ"] = [bool(L.fill_diff(w, L.refill(w, os.path.join(d, f"refilled{i}.kicad_pcb")))) for i in range(3)]
    L.emit(name, contract=prob, **L.summary(v), refill_diff=diff, **res)

# 1c. a copper zone inside a footprint (net F, priority 2) overlapping the P fill at priority 2, both uuid orders
FZ = """
f = pcbnew.FOOTPRINT(b); f.SetReference("F1"); f.SetValue("F1"); f.SetPosition(V(30, 24)); b.Add(f)
p = pcbnew.PAD(f); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetLayerSet(p.SMDMask())
p.SetSize(V(1, 1)); f.Add(p); p.SetPosition(V(30, 24)); p.SetNet(net("F"))
z = pcbnew.ZONE(f); z.SetLayer(pcbnew.F_Cu); z.SetAssignedPriority(2); z.SetZoneName("fpzone")
z.SetLocalClearance(mm(0.3)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
o = z.Outline(); o.NewOutline()
for x, y in [(22, 17), (38, 17), (38, 30), (22, 30)]:
    o.Append(mm(x), mm(y))
f.Add(z)
z.SetNet(net("F"))
"""
HAND_F = dict(HAND, fps=[x for x in HAND["fps"] if x["ref"] != "H1"])
for name, u in [("fp_zone_high", "ffffffff-ffff-4fff-8fff-ffffffffffff"), ("fp_zone_low", "00000000-0000-4000-8000-000000000001")]:
    def ed(t, u=u):
        i = t.index('(name "fpzone")')
        s = t.rfind("(zone", 0, i)
        return t[:s] + re.sub(r'\(uuid "[^"]*"\)', f'(uuid "{u}")', t[s:i], count=1) + t[i:]
    v, prob, d, diff = run_and_refill(name, HAND_F, PT, FZ, ed)
    res = {}
    if diff is not None:
        fz = [z for z in L.shapes(v["data"]["written"])["zones"] if z["name"] == "fpzone"]
        res = dict(fp_zone_net=fz[0]["net"] if fz else None, fp_zone_area=round(L.mp(fz[0]["fills"].get("F.Cu", [])).area, 2) if fz else None)
    L.emit(name, contract=prob, **L.summary(v), refill_diff=diff, **res)

# 6. pour keep-outs cut fills on their own layers only, as written and after a KiCad refill
P2 = {"layers": 4, "fps": HAND["fps"][:3], "tracks": [(10, 20, 50, 20, "P", 0.3, "F.Cu"), (12, 20, 48, 20, "P", 0.3, "B.Cu")], "vias": [(12, 20, "P"), (48, 20, "P")]}
for name, layers in [("ko_inner_only", '["In2.Cu"]'), ("ko_front_only", '["F.Cu"]'), ("ko_all", '"all"')]:
    v, prob, d, diff = run_and_refill(name, P2, f'[fill]\nlayers = ["F.Cu", "B.Cu"]\n\n[nets.P]\nfill_grow_mm = 1.0\n\n[[keepout]]\nname = "k"\nrect = [25, 15, 35, 25]\nlayers = {layers}\nforbid = ["pour"]\n')
    res = {}
    if diff is not None:
        f = L.zone_fills(v["data"]["written"])
        for lay in ("F.Cu", "B.Cu"):
            g = [geo for (nm, ly), geo in f.items() if ly == lay and nm.startswith("pcb:fill:P:")]
            from shapely.ops import unary_union
            res[lay] = round(unary_union(g).intersection(box(25, 15, 35, 25)).area, 2) if g else 0.0
    L.emit(name, contract=prob, **L.summary(v), inside=res, refill_diff=diff)

# new: fill-overlap. Same priority (warned), distinct priorities (not), apart (not), three nets (three pairs), a plane at
# the fills' priority, a hand zone at it, and a second run for determinism
THREE = cross("A", "B")
THREE["fps"] = THREE["fps"] + [{"ref": "U5", "at": (34, 23), "pads": [{"num": "1", "at": (34, 23), "net": "C"}]},
                               {"ref": "U6", "at": (34, 35), "pads": [{"num": "1", "at": (34, 35), "net": "C"}]}]
THREE["tracks"] = THREE["tracks"] + [(34, 23, 34, 35, "C", 0.3, "F.Cu")]
ov = [
    ("ov_same", cross("A", "B"), '[fill]\nlayers = ["F.Cu"]\n\n[nets.A]\nfill_grow_mm = 3.0\n\n[nets.B]\nfill_grow_mm = 3.0\n', None),
    ("ov_distinct", cross("A", "B"), '[fill]\nlayers = ["F.Cu"]\n\n[nets.A]\nfill_grow_mm = 3.0\nfill_priority = 3\n\n[nets.B]\nfill_grow_mm = 3.0\n', None),
    ("ov_apart", cross("A", "B"), '[fill]\nlayers = ["F.Cu"]\n\n[nets.A]\nfill_grow_mm = 1.0\n\n[nets.B]\nfill_grow_mm = 1.0\n', None),
    ("ov_three", THREE, '[fill]\nlayers = ["F.Cu"]\npriority = 4\n\n[nets.A]\nfill_grow_mm = 3.0\n\n[nets.B]\nfill_grow_mm = 3.0\n\n[nets.C]\nfill_grow_mm = 3.0\n', None),
    ("ov_plane", cross("A", "B"), '[fill]\nlayers = ["F.Cu"]\n\n[nets.A]\nfill_grow_mm = 3.0\nfill_priority = 3\n\n[[zone]]\nnet = "GND"\nlayers = ["F.Cu"]\nclearance_mm = 0.3\npriority = 3\n', None),
    ("ov_hand_zone", HAND, PT, HZ),
    ("ov_two_planes", cross("A", "B"), '[[zone]]\nnet = "GND"\nlayers = ["B.Cu"]\nclearance_mm = 0.3\n\n[[zone]]\nnet = "A"\nlayers = ["B.Cu"]\nclearance_mm = 0.3\n', None),
]
for name, spec, toml, code in ov:
    v, prob, d, diff = run_and_refill(name, spec, toml, code)
    msgs = [w.get("message", "") for w in v.get("warnings", []) if w.get("code") == "fill-overlap"]
    res = dict(overlaps=(v.get("data") or {}).get("fill_overlaps"), messages=msgs)
    if name in ("ov_same", "ov_three"):
        v2, c2, prob2, out2 = L.zone(d, out=os.path.join(d, "out2.kicad_pcb"), work=os.path.join(d, "work2"))
        res["second_same_warnings"] = [w.get("message") for w in v2.get("warnings", [])] == [w.get("message") for w in v.get("warnings", [])]
        res["second_same_bytes"] = open(out2, "rb").read() == open(v["data"]["written"], "rb").read() if v.get("outcome") == "done" else None
        prob = prob + prob2
    L.emit(name, contract=prob, **L.summary(v), refill_diff=diff, **res)

# 17. the oracle edits: a filled graphic shape's flag must survive both scripts' masking, a zone's flag must not
SHAPE = """
s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_RECT); s.SetStart(V(40, 30)); s.SetEnd(V(44, 34)); s.SetLayer(pcbnew.F_Cu)
s.SetWidth(mm(0.1)); s.SetFilled(True); s.SetNet(net("GND")); b.Add(s)
s2 = pcbnew.PCB_SHAPE(b); s2.SetShape(pcbnew.SHAPE_T_POLY); s2.SetLayer(pcbnew.B_Cu); s2.SetWidth(mm(0)); s2.SetFilled(True)
pts = pcbnew.VECTOR_VECTOR2I()
for x, y in [(45, 30), (49, 30), (49, 34)]:
    pts.append(V(x, y))
s2.SetPolyPoints(pts); b.Add(s2)
"""
d = L.build(os.path.join(work, "oracle_regex"), cross("A", "B"), '[[zone]]\nnet = "GND"\nlayers = ["F.Cu", "B.Cu"]\nclearance_mm = 0.3\n', SHAPE)
v, code_, prob, out = L.zone(d)
res = {}
if v.get("outcome") in ("done", "rejected"):
    t = open(v["data"]["written"]).read()
    unfilled = t.replace("(fill yes)", "(fill no)")
    zone_off = re.sub(r"\(fill yes(?=\s)", "(fill", t)
    for script, fn in [(os.path.join(here, "..", "r09", "check_splice.py"), "strip_fills"), (os.path.join(here, "..", "r12", "gate12.py"), "no_fills")]:
        src = open(script).read()
        mod = ast.parse(src)
        g = {"re": re}
        if fn == "no_fills":
            # gate12's helper uses review 10's `blocks`
            sys.path.insert(0, os.path.join(here, "..", "r10"))
            from lib import blocks  # noqa: E402
            g["blocks"] = blocks
        exec(compile(ast.Module([n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name == fn], []), script, "exec"), g)
        f = g[fn]
        res[os.path.basename(script)] = dict(shape_flags_in_file=t.count("(fill yes)"), zone_flags_in_file=len(re.findall(r"\(fill yes(?=\s)", t)),
                                             shape_change_seen=f(t) != f(unfilled), zone_flag_masked=f(t) == f(zone_off))
L.emit("oracle_regex", contract=prob, **L.summary(v), **res)
