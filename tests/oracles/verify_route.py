"""Independent check of a `pcb route` result against the board it started from.

It reads both boards with KiCad's own pcbnew (not pcb's parser) and fails unless:
  A. everything that is not a track or via is byte-identical;
  B. every track and via not wholly inside the region is byte-identical, except a track split where new copper
     joins it, whose pieces must rebuild it exactly with every cut inside the region;
  C. every added or removed item lies inside the region (0.01 mm slack) and is on an allowed net;
  D. by KiCad's connectivity engine, no net has more separate pad groups than before, and each target net is
     whole;
  E. no net has more dangling track ends than before (KiCad's own dangling test);
  F. KiCad DRC (zones refilled) finds no more violations of any type, for any set of nets, than before;
  G. no locked track or via was removed or changed;
  H. no two tracks or vias share an id (tstamp or uuid);
  I. every added track is at least as wide as its net's most common width before.

Usage: python3 verify_route.py original.kicad_pcb routed.kicad_pcb x0,y0,x1,y1 TARGET_NETS ALLOWED_NETS
       (comma-separated; ALLOWED_NETS "all" allows any net)
"""
import collections
import json
import math
import os
import re
import sys
import tempfile

import pcbnew

TOL = 0.01


def items(path):
    """Tracks and vias as (kind, key, text line), keyed by geometry."""
    text = open(path).read()
    lines = text.split("\n")
    out = []
    for ln in lines:
        s = ln.strip()
        # "(via " with the space: KiCad-saved boards also carry a "(viasonmask ...)" line (review 4, R1)
        if s.startswith("(segment ") or s.startswith("(via "):
            out.append(s)
    rest = [ln for ln in lines if not (ln.strip().startswith("(segment ") or ln.strip().startswith("(via "))]
    # zone fills are recomputed by KiCad after a route, across the whole board (review 4, R2): compare the zone
    # definitions, not their filled polygons
    out_rest, skip = [], None
    for ln in rest:
        if skip is not None:
            if ln.startswith(skip + ")"):
                skip = None
            continue
        st = ln.lstrip()
        if st.startswith("(filled_polygon"):
            skip = ln[: len(ln) - len(st)]
            if st.rstrip().endswith(")") and st.count("(") == st.count(")"):
                skip = None
            continue
        out_rest.append(ln)
    rest = out_rest
    return out, rest


def geom(line, nets):
    num = lambda k: [float(v) for v in re.search(r"\(" + k + r" ([-\d.]+) ([-\d.]+)\)", line).groups()]
    net = nets[int(re.search(r"\(net (\d+)\)", line).group(1))]
    if line.startswith("(segment"):
        a, c = num("start"), num("end")
        layer = re.search(r'\(layer "([^"]+)"\)', line).group(1)
        width = float(re.search(r"\(width ([\d.]+)\)", line).group(1))
        return {"kind": "segment", "a": a, "c": c, "layer": layer, "width": width, "net": net, "locked": " locked" in line[:16]}
    p = num("at")
    return {"kind": "via", "a": p, "c": p, "net": net}


def net_table(path):
    return {int(m.group(1)): m.group(2) for m in re.finditer(r'^  \(net (\d+) "([^"]*)"\)', open(path).read(), re.M)}


def inside(r, p):
    return r[0] - TOL <= p[0] <= r[2] + TOL and r[1] - TOL <= p[1] <= r[3] + TOL


def wholly_inside(r, g):
    return inside(r, g["a"]) and inside(r, g["c"])


def collinear_rebuild(orig, pieces, r):
    """pieces (list of geoms) chain from orig's start to its end along it, cuts inside the region."""
    if not pieces:
        return False
    for p in pieces:
        if (p["layer"], p["width"], p["net"]) != (orig["layer"], orig["width"], orig["net"]):
            return False
    a, c = orig["a"], orig["c"]
    L = math.dist(a, c)
    if L == 0:
        return False

    def u(p):
        return ((p[0] - a[0]) * (c[0] - a[0]) + (p[1] - a[1]) * (c[1] - a[1])) / (L * L)

    def off(p):
        return abs((c[0] - a[0]) * (p[1] - a[1]) - (c[1] - a[1]) * (p[0] - a[0])) / L

    spans = []
    for p in pieces:
        if off(p["a"]) > 1e-3 or off(p["c"]) > 1e-3:
            return False
        spans.append(tuple(sorted((u(p["a"]), u(p["c"])))))
    spans.sort()
    if abs(spans[0][0]) > 1e-4 or abs(spans[-1][1] - 1) > 1e-4:
        return False
    for s, t in zip(spans, spans[1:]):
        if abs(s[1] - t[0]) > 1e-4:
            return False
    for s in spans[1:]:
        cut = (a[0] + s[0] * (c[0] - a[0]), a[1] + s[0] * (c[1] - a[1]))
        if not inside(r, cut):
            return False
    return True


def pad_groups(board):
    """{net: number of separate groups of its pads}, by KiCad's connectivity engine."""
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    pads = collections.defaultdict(list)
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.GetNetname():
                pads[p.GetNetname()].append(p)
    groups = {}
    for net, ps in pads.items():
        seen_pads = set()
        n = 0
        for p in ps:
            if p.m_Uuid.AsString() in seen_pads:
                continue
            n += 1
            # flood from this pad through tracks and vias
            stack = [p]
            seen = set()
            while stack:
                it = stack.pop()
                key = (it.GetClass(), it.m_Uuid.AsString())
                if key in seen:
                    continue
                seen.add(key)
                if it.GetClass() == "PAD":
                    seen_pads.add(it.m_Uuid.AsString())
                for t in conn.GetConnectedTracks(it):
                    stack.append(t)
                for q in conn.GetConnectedPads(it):
                    stack.append(q)
        groups[net] = n
    return groups


def dangling(board):
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    d = collections.Counter()
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK" and conn.TestTrackEndpointDangling(t, False):
            d[t.GetNetname()] += 1
    return d


def drc(board, path):
    """Violations counted by type and the nets involved, after refilling zones in memory."""
    if len(board.Zones()):
        board.BuildConnectivity()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    rpt = tempfile.mktemp(suffix=".rpt")
    pcbnew.WriteDRCReport(board, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
    c = collections.Counter()
    for m in re.finditer(r"^\[(\w+)\]:[^\n]*\n((?:    [^\n]*\n)+)", open(rpt).read(), re.M):
        nets = sorted(set(re.findall(r"\[([^\]]*)\]", m.group(2))))
        c[m.group(1) + " " + " ".join(nets)] += 1
    os.unlink(rpt)
    return c


def measure_in_child(path):
    import subprocess
    out = subprocess.run([sys.executable, os.path.abspath(__file__), "--measure", path], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"measuring {path} failed: {out.stderr[-2000:]}")
    return json.loads([ln for ln in out.stdout.splitlines() if ln.startswith("{")][-1])


def measure(path):
    b = pcbnew.LoadBoard(path)
    print(json.dumps({"groups": pad_groups(b), "dangling": dangling(b), "drc": drc(b, path)}))


def main():
    orig_p, routed_p, region, targets, allowed = sys.argv[1:6]
    r = [float(v) for v in region.split(",")]
    r = (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
    targets = [t for t in targets.split(",") if t]
    allow_all = allowed == "all"
    allowed = set(a for a in allowed.split(",") if a) | set(targets)
    fails = []

    o_items, o_rest = items(orig_p)
    n_items, n_rest = items(routed_p)
    # A
    if [ln for ln in o_rest if ln.strip()] != [ln for ln in n_rest if ln.strip()]:
        fails.append("A: something other than tracks and vias changed")
    # B, C
    o_nets, n_nets = net_table(orig_p), net_table(routed_p)
    o_set, n_set = collections.Counter(o_items), collections.Counter(n_items)
    removed = list((o_set - n_set).elements())
    added = list((n_set - o_set).elements())
    added_g = [geom(x, n_nets) for x in added]
    used = set()
    for line in removed:
        g = geom(line, o_nets)
        if not (allow_all or g["net"] in allowed):
            fails.append(f"C: removed item on a net not allowed: {line[:90]}")
        if wholly_inside(r, g):
            continue
        # a split: pieces among the added items
        if g["kind"] == "segment":
            cand = [i for i, h in enumerate(added_g) if h["kind"] == "segment" and i not in used and h["net"] == g["net"] and h["layer"] == g["layer"]]
            # pick pieces lying on this track
            on = [i for i in cand if _on_line(g, added_g[i])]
            if collinear_rebuild(g, [added_g[i] for i in on], r):
                used.update(on)
                continue
        fails.append(f"B: item not wholly inside the region changed or was removed: {line[:90]}")
    for i, g in enumerate(added_g):
        if i in used:
            continue
        if not wholly_inside(r, g):
            fails.append(f"C: added item outside the region: {added[i][:90]}")
        if not (allow_all or g["net"] in allowed):
            fails.append(f"C: added item on a net not allowed: {added[i][:90]}")

    # D, E, F with KiCad, each board in its own process: within one process the first DRC run was seen to
    # skip the clearance tests, and pcbnew holds one project (design rules) at a time
    mo, mn = measure_in_child(orig_p), measure_in_child(routed_p)
    go, do, co = mo["groups"], collections.Counter(mo["dangling"]), collections.Counter(mo["drc"])
    gn, dn, cn = mn["groups"], collections.Counter(mn["dangling"]), collections.Counter(mn["drc"])
    for net in sorted(set(go) | set(gn)):
        if gn.get(net, 0) > go.get(net, 0):
            fails.append(f"D: {net} split into {gn[net]} pad groups (was {go.get(net, 0)})")
    for t in targets:
        if gn.get(t, 0) != 1:
            fails.append(f"D: target {t} has {gn.get(t, 0)} pad groups, not 1")
    for net in sorted(set(do) | set(dn)):
        if dn[net] > do[net]:
            fails.append(f"E: {net} dangling track ends {do[net]} -> {dn[net]}")
    for k in sorted(set(co) | set(cn)):
        if cn[k] > co[k]:
            fails.append(f"F: DRC {k} {co[k]} -> {cn[k]}")

    # G
    for line in removed:
        if " locked" in line[:16]:
            fails.append(f"G: locked item removed or changed: {line[:90]}")
    # H
    ids = collections.Counter(m.group(1) for x in n_items for m in [re.search(r"\((?:tstamp|uuid) ([^)\s]+)\)", x)] if m)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        fails.append(f"H: {len(dup)} ids shared by several tracks or vias, e.g. {dup[0]}")
    # I
    widths = collections.defaultdict(collections.Counter)
    for x in o_items:
        g = geom(x, o_nets)
        if g["kind"] == "segment":
            widths[g["net"]][g["width"]] += 1
    for i, g in enumerate(added_g):
        if g["kind"] == "segment" and widths[g["net"]]:
            want = max(widths[g["net"]].items(), key=lambda kv: (kv[1], kv[0]))[0]
            if g["width"] < want - 1e-3:
                fails.append(f"I: {g['net']} track added at {g['width']} mm, its tracks are {want} mm: {added[i][:80]}")

    res = {
        "ok": not fails,
        "fails": fails,
        "removed": len(removed),
        "added": len(added),
        "split_pieces": len(used),
        "targets": {t: {"before": go.get(t), "after": gn.get(t)} for t in targets},
        "drc_before": sum(co.values()),
        "drc_after": sum(cn.values()),
    }
    print(json.dumps(res, indent=1))
    sys.exit(0 if res["ok"] else 1)


def _on_line(g, h):
    a, c = g["a"], g["c"]
    L = math.dist(a, c)
    if L == 0:
        return False
    for p in (h["a"], h["c"]):
        off = abs((c[0] - a[0]) * (p[1] - a[1]) - (c[1] - a[1]) * (p[0] - a[0])) / L
        u = ((p[0] - a[0]) * (c[0] - a[0]) + (p[1] - a[1]) * (c[1] - a[1])) / (L * L)
        if off > 1e-3 or u < -1e-4 or u > 1 + 1e-4:
            return False
    return True


if sys.argv[1] == "--measure":
    measure(sys.argv[2])
else:
    main()
