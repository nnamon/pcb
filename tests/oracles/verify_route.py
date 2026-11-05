"""Independent check of a `pcb route` result against the board it started from.

It reads both boards with KiCad's own pcbnew and kicad-cli, and the files with tests/lib/kisexp.py (not pcb's parser),
and fails unless:
  A. every top-level item that is not a track or via is byte-identical (zone fills aside);
  B. every track and via not wholly inside the region is byte-identical, except a track split where new copper
     joins it, whose pieces must rebuild it exactly with every cut inside the region;
  C. every added or removed item lies inside the region (0.01 mm slack) and is on an allowed net;
  D. by KiCad's connectivity engine, no net has more separate pad groups than before, and each target net is
     whole;
  E. no net has more dangling track ends than before (KiCad's own dangling test), and no added track that is not a
     piece of a split one dangles (review 6, K7: a count per net let one new stub hide behind one fixed);
  F. KiCad DRC (zones refilled) finds no more violations of any type, for any set of nets, than before;
  G. no locked track or via was removed or changed;
  H. no two tracks or vias share an id (tstamp or uuid);
  I. every added track is at least as wide as its net's most common width before, or exactly the width given for
     its net in WIDTHS (pcb route --width, an owner's choice for one link).

Usage: python3 verify_route.py original.kicad_pcb routed.kicad_pcb x0,y0,x1,y1 TARGET_NETS ALLOWED_NETS [WIDTHS]
       (comma-separated; ALLOWED_NETS "all" allows any net; WIDTHS is NET=MM,...)
"""
import collections
import json
import math
import os
import re
import sys

import pcbnew

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import kisexp  # noqa: E402

TOL = 0.01


def items(path):
    """(tracks and vias, everything else): each a list of top-level item texts, exactly as in the file. Zone fills
    are recomputed by KiCad after a route, across the whole board (review 4, R2), so a zone's text leaves out its
    filled polygons and whether it is filled."""
    src = open(path).read()
    root = kisexp.parse(src)
    copper, rest = [], []
    for n in root.items[1:]:
        if not isinstance(n, kisexp.Node):
            rest.append(n)
            continue
        t = n.text(src)
        if n.head in ("segment", "via"):
            copper.append(t)
            continue
        if n.head == "zone":
            for f in sorted(n.find_all("filled_polygon"), key=lambda f: -f.span[0]):
                t = t[: f.span[0] - n.span[0]] + t[f.span[1] - n.span[0]:]
            t = re.sub(r"\(fill\s+yes\b", "(fill", t)
            t = re.sub(r"\s+", " ", t)
        rest.append(t)
    return copper, rest


def geom(text):
    n = kisexp.parse(text)
    net = n.find("net").arg(1) if n.find("net") else ""
    locked = bool(n.find("locked") and n.find("locked").arg(1) == "yes") or "locked" in n.items[1:]
    if n.head == "segment":
        return {"kind": "segment", "a": n.nums("start"), "c": n.nums("end"), "layer": n.find("layer").arg(1), "width": n.nums("width")[0], "net": net, "locked": locked}
    p = n.nums("at")
    return {"kind": "via", "a": p, "c": p, "net": net, "locked": locked}


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
    """({net: dangling tracks}, [geometry keys of the dangling tracks])."""
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    d = collections.Counter()
    where = []
    for t in board.GetTracks():
        # an end KiCad calls dangling, or a track joined to nothing at all, which that test passes (review 5, 6)
        if t.GetClass() == "PCB_TRACK" and (conn.TestTrackEndpointDangling(t, False) or (not conn.GetConnectedTracks(t) and not conn.GetConnectedPads(t))):
            d[t.GetNetname()] += 1
            where.append(track_key(t.GetNetname(), (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))))
    return d, where


def mm(v):
    return v / 1e6


def track_key(net, a, c):
    """A track by net and its two ends, to 1 um, either way round."""
    ends = sorted([(round(a[0], 3), round(a[1], 3)), (round(c[0], 3), round(c[1], 3))])
    return f"{net}|{ends[0][0]},{ends[0][1]}|{ends[1][0]},{ends[1][1]}"


def drc(path):
    """Violations counted by type and the nets involved, zones refilled in memory (kicad-cli)."""
    return kisexp.drc_counts(path)


def measure_in_child(path):
    import subprocess
    out = subprocess.run([sys.executable, os.path.abspath(__file__), "--measure", path], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"measuring {path} failed: {out.stderr[-2000:]}")
    return json.loads([ln for ln in out.stdout.splitlines() if ln.startswith("{")][-1])


def measure(path):
    b = pcbnew.LoadBoard(path)
    dn, where = dangling(b)
    print(json.dumps({"groups": pad_groups(b), "dangling": dn, "dangling_tracks": where, "drc": drc(path)}))


def main():
    orig_p, routed_p, region, targets, allowed = sys.argv[1:6]
    given = {k: float(v) for k, v in (w.split("=") for w in (sys.argv[6] if len(sys.argv) > 6 else "").split(",") if w)}
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
    o_set, n_set = collections.Counter(o_items), collections.Counter(n_items)
    removed = list((o_set - n_set).elements())
    added = list((n_set - o_set).elements())
    added_g = [geom(x) for x in added]
    used = set()
    for line in removed:
        g = geom(line)
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
    new_dangling = set(mn["dangling_tracks"])
    for i, g in enumerate(added_g):
        if g["kind"] == "segment" and i not in used and track_key(g["net"], g["a"], g["c"]) in new_dangling:
            fails.append(f"E: added track dangles: {added[i][:90]}")
    for k in sorted(set(co) | set(cn)):
        if cn[k] > co[k]:
            fails.append(f"F: DRC {k} {co[k]} -> {cn[k]}")

    # G
    for line in removed:
        if geom(line)["locked"]:
            fails.append(f"G: locked item removed or changed: {line[:90]}")
    # H
    ids = collections.Counter(u.arg(1) for x in n_items for u in [kisexp.parse(x).find("uuid") or kisexp.parse(x).find("tstamp")] if u)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        fails.append(f"H: {len(dup)} ids shared by several tracks or vias, e.g. {dup[0]}")
    # I
    widths = collections.defaultdict(collections.Counter)
    for x in o_items:
        g = geom(x)
        if g["kind"] == "segment":
            widths[g["net"]][g["width"]] += 1
    for i, g in enumerate(added_g):
        if g["kind"] == "segment" and g["net"] in given:
            if abs(g["width"] - given[g["net"]]) > 1e-3:
                fails.append(f"I: {g['net']} track added at {g['width']} mm, --width gave {given[g['net']]} mm: {added[i][:80]}")
        elif g["kind"] == "segment" and widths[g["net"]]:
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
