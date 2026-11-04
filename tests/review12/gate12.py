"""Review 12 gate probes: zone markers against colliding ids, duplicate uuids, groups, rule areas, footprint zones.
usage: PCB_BIN=... python3 gate12.py WORKDIR [case ...]
One JSON line per case: outcomes, distinct output files over 3 runs, fill mismatches against a pcbnew refill,
zone uuids in vs out, and lines removed / added outside filled_polygon blocks."""
import difflib
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review10"))
import pcbnew  # noqa: E402
from lib import B, edit, fill_check, blocks, strip_zone_uuids  # noqa: E402

work = os.path.abspath(sys.argv[1])
os.makedirs(work, exist_ok=True)
only = sys.argv[2:]
ADD_S = [{"op": "add_track", "net": "S", "layer": "F.Cu", "width": 0.2, "points": [[5, 45], [30, 45]]}]
M = lambda i: f"00000000-0000-4000-8000-{i:012}"


def no_fills(t):
    out, i = [], 0
    for s, e in blocks(t, "filled_polygon"):
        if s < i:
            continue
        out.append(t[i:s])
        i = e
    out.append(t[i:])
    # the zone's filled flag is part of its fill state, which the gate takes from pcbnew (M2)
    return re.sub(r"\n[ \t]*\n", "\n", "".join(out)).replace("(fill yes", "(fill")


def zone_uuids(t):
    r = []
    for s, e in blocks(t, "zone"):
        m = re.search(r'\(uuid "([^"]*)"\)', t[s:e])
        r.append(m.group(1) if m else None)
    return r


def run(name, board, ops=ADD_S, runs=3, identity=True):
    if only and name not in only:
        return
    src = open(board).read()
    shas, res = set(), {"case": name}
    for k in range(runs):
        out = os.path.join(work, f"{name}_{k}.out.kicad_pcb")
        if os.path.exists(out):
            os.remove(out)
        d = edit(board, ops, out, os.path.join(work, f"{name}_{k}_w"))
        err = d.get("error")
        res.setdefault("outcomes", []).append((d.get("outcome"), err.get("message") if isinstance(err, dict) else err, (d.get("data") or {}).get("regressions")))
        if d.get("outcome") == "done" and os.path.exists(out):
            t = open(out).read()
            shas.add(hashlib.sha256(t.encode()).hexdigest())
            if k == 0:
                res["fill_mismatch"] = fill_check(out)
                res["zone_uuids_kept"] = zone_uuids(t) == zone_uuids(src)
                res["markers_leaked"] = "00000000-0000-4000-8000-" in t and "00000000-0000-4000-8000-" not in src
                dl = [l for l in difflib.unified_diff(no_fills(src).splitlines(), no_fills(t).splitlines(), lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
                if identity:
                    res["removed"] = [l for l in dl if l.startswith("-")]
                    res["added"] = [l for l in dl if l.startswith("+")]
                res["filled_zones"] = t.count("(filled_polygon")
    res["distinct_files"] = len(shas)
    print(json.dumps(res, default=str))


def base(name, fill=True, fz=False):
    g = B()
    g.fp("S1", 5, 45, "S"); g.fp("S2", 30, 45, "S")
    g.fp("G1", 10, 10, "GND", tht=True)
    g.fp("V1", 20, 10, "VCC", tht=True)
    g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=0.3, priority=0)
    g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=2.0, priority=1)
    g.zone("VCC", [pcbnew.B_Cu], (2, 2, 38, 20), clearance=0.5)
    g.zone(None, [pcbnew.F_Cu], (50, 5, 70, 20), keepout=True)
    if fz:
        f = g.fp("FZ", 60, 30, "GND", tht=True, extra_pads=[(63, 30, "VCC")])
        g.zone("GND", [pcbnew.B_Cu], (52, 24, 68, 36), parent=f, clearance=0.3)
    p = g.save(os.path.join(work, name + ".kicad_pcb"), fill=fill)
    return p


def set_uuid(t, head, idx, new):
    """Give the idx-th block starting with '(head' the uuid `new` (its own first uuid line)."""
    s, e = blocks(t, head)[idx]
    blk = re.sub(r'\(uuid "[^"]*"\)', f'(uuid "{new}")', t[s:e], count=1)
    return t[:s] + blk + t[e:]


# C1: other items already use the marker ids: a footprint gets M(0), the edge line M(1), a zone M(2)'s neighbour
p = base("collide")
t = open(p).read()
t = set_uuid(t, "footprint", 0, M(0))
t = set_uuid(t, "gr_line", 0, M(1))
t = set_uuid(t, "gr_line", 1, M(2))
t = set_uuid(t, "gr_line", 2, M(3))
open(p, "w").write(t)
run("collide_marker_ids", p)

# C2: the same, never filled and zone uuids stripped
p = base("collide_unfilled", fill=False)
strip_zone_uuids(p)
t = open(p).read()
for i in range(4):
    t = set_uuid(t, "gr_line", i, M(i))
open(p, "w").write(t)
run("collide_marker_ids_unfilled", p)

# C3: every zone shares one uuid (pasted text), footprint zone included
p = base("dupuuid", fz=True)
t = open(p).read()
for i in range(len(blocks(t, "zone"))):
    t = set_uuid(t, "zone", i, "abcdefab-1111-4222-8333-444455556666")
open(p, "w").write(t)
run("dup_uuid_all_zones", p)

# C4: zones as members of a group
p = base("group")
t = open(p).read()
zs = zone_uuids(t)
grp = '\t(group "" (uuid "99999999-1111-4222-8333-444455556666") (members ' + " ".join(f'"{u}"' for u in zs[:3]) + "))\n"
t = t.rstrip()[:-1] + grp + ")\n"
open(p, "w").write(t)
run("zones_in_group", p)

# C5: footprint zone, the footprint moved by the edit, zone uuids kept
p = base("fpmove", fz=True)
run("fp_zone_moved", p, ops=[{"op": "move_footprint", "ref": "FZ", "from": [60, 30], "to": [58.5, 31.25]}] + ADD_S, identity=False)

# C6: a zone given a uuid equal to a marker of another index (M(0) on the last zone)
p = base("zone_has_marker", fz=True)
t = open(p).read()
n = len(blocks(t, "zone"))
t = set_uuid(t, "zone", n - 1, M(0))
t = set_uuid(t, "zone", 0, M(n - 1))
open(p, "w").write(t)
run("zone_uuid_is_marker", p)

# C7: a zone with no polygon at all (pcbnew may drop it on load)
p = base("emptyzone")
t = open(p).read()
t = t.rstrip()[:-1] + '\t(zone (net "GND") (layer "F.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)))\n)\n'
open(p, "w").write(t)
run("zone_without_polygon", p)

# C8: a footprint pasted as identical text twice (same footprint uuid, same zone uuid), then one copy's zone
# clearance changed by text
p = base("pasted_fp", fz=True)
t = open(p).read()
s, e = [b for b in blocks(t, "footprint") if '"FZ"' in t[b[0]:b[1]]][0]
fpt = t[s:e]
fpt2 = re.sub(r"\(clearance 0\.3\)", "(clearance 1.5)", fpt, count=1)
t = t[:e] + "\n\t" + fpt2 + t[e:]
open(p, "w").write(t)
run("pasted_fp_same_uuids", p)
