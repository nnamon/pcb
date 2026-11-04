"""Gerber and Excellon operations `pcb` delegates to gerbonara and shapely. Embedded in the pcb binary and written to
its work directory at run time; prints one JSON object.

  zip FOLDER DEST         zip a folder's files, sorted, with a fixed date
  compare A B [EXPLAIN [BOARD]]   compare two fabrication sets (folders or zips), layer by layer as shapes and hole by hole

Layers are found by their X2 file function when the file has one, else by file name. The two sets are aligned on
the centres of their board outlines. A difference is a connected piece of copper, mask, paste or silk present in
one set and not the other; pieces under NOISE_MM2, or thinner than NOISE_WIDTH everywhere, are rounding and are
dropped. Each remaining piece must lie inside a region of the explain file (TOML, `[[explain]]` with `layer`,
`side` = "a", "b" or "both", `rect` = [x0, y0, x1, y1] in B's frame or `whole = true`, optionally
`thinner_than_mm` (only pieces no wider than that; on its own it covers the whole layer), or `zone_net` (A's copper
that is wholly a zone fill of that net on the board A was made from), and `why`), or it is listed as unexplained. Holes match within HOLE_TOL in place and size, and on plating.
"""
import json
import math
import os
import re
import sys
import tempfile
import tomllib
import zipfile

NOISE_MM2 = 0.01
NOISE_WIDTH = 0.02
HOLE_TOL = 0.01

LAYERS = {
    # key: (X2 file functions, file-name patterns)
    "F.Cu": (("Copper,L1,Top",), (r"f[._-]?cu", r"\.gtl$")),
    "B.Cu": (("Copper,L2,Bot", "Copper,L4,Bot", "Copper,L6,Bot"), (r"b[._-]?cu", r"\.gbl$")),
    "F.Mask": (("Soldermask,Top",), (r"f[._-]?mask", r"\.gts$")),
    "B.Mask": (("Soldermask,Bot",), (r"b[._-]?mask", r"\.gbs$")),
    "F.Paste": (("Paste,Top",), (r"f[._-]?paste", r"\.gtp$")),
    "B.Paste": (("Paste,Bot",), (r"b[._-]?paste", r"\.gbp$")),
    "F.Silk": (("Legend,Top",), (r"f[._-]?silk", r"\.gto$")),
    "B.Silk": (("Legend,Bot",), (r"b[._-]?silk", r"\.gbo$")),
    "Edge.Cuts": (("Profile",), (r"edge[._-]?cuts", r"\.gko$", r"\.gm1$")),
}


def files_of(src):
    """The fabrication files of a folder or a zip, unpacked to a temporary folder if zipped."""
    if os.path.isfile(src) and zipfile.is_zipfile(src):
        d = tempfile.mkdtemp(prefix="pcb_gerb_")
        with zipfile.ZipFile(src) as z:
            z.extractall(d)
        src = d
    out = []
    for root, _, names in os.walk(src):
        out += [os.path.join(root, n) for n in names]
    return sorted(out)


def file_function(path):
    try:
        head = open(path, errors="replace").read(4000)
    except OSError:
        return None
    m = re.search(r"%TF\.FileFunction,([^*]*)\*%", head) or re.search(r"G04 #@! TF\.FileFunction,([^*]*)\*", head)
    return m.group(1) if m else None


def find_layers(paths):
    found = {}
    # inner copper by its X2 function (Copper,L<n>,Inr), named In<n-1>.Cu
    for p in paths:
        ff = file_function(p) or ""
        m = re.match(r"Copper,L(\d+),Inr", ff)
        if m:
            found[f"In{int(m.group(1)) - 1}.Cu"] = p
    for key, (funcs, pats) in LAYERS.items():
        for p in paths:
            if not re.search(r"\.(gbr|g[a-z0-9]{2}|gm1)$", p, re.I):
                continue
            ff = file_function(p)
            if ff is not None:
                if any(ff.startswith(f) for f in funcs):
                    found[key] = p
                    break
            elif any(re.search(pt, os.path.basename(p), re.I) for pt in pats):
                found[key] = p
                break
    return found


def prim_shape(p):
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
    from shapely.affinity import rotate
    from shapely.geometry import LineString, Point, Polygon, box
    if isinstance(p, Line):
        if (p.x1, p.y1) == (p.x2, p.y2):
            return Point(p.x1, p.y1).buffer(p.width / 2)
        return LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2)
    if isinstance(p, Circle):
        return Point(p.x, p.y).buffer(p.r)
    if isinstance(p, Rectangle):
        g = box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
        return rotate(g, p.rotation, origin=(p.x, p.y), use_radians=True) if p.rotation else g
    if isinstance(p, Arc):
        p = p.to_arc_poly()
    if isinstance(p, ArcPoly):
        pts = [tuple(q) for q, _, _ in p.approximate_arcs().segments]
        return Polygon(pts).buffer(0) if len(pts) >= 3 else None
    raise TypeError(f"gerber primitive {type(p).__name__}")


def layer_shape(path):
    """Dark minus clear, in file order."""
    from gerbonara import GerberFile
    from gerbonara.utils import MM
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    acc, batch, dark = Polygon(), [], True
    for o in GerberFile.open(path).objects:
        for p in o.to_primitives(MM):
            s = prim_shape(p)
            if s is None or s.is_empty:
                continue
            if p.polarity_dark != dark and batch:
                acc = acc.union(unary_union(batch)) if dark else acc.difference(unary_union(batch))
                batch = []
            dark = p.polarity_dark
            batch.append(s)
    if batch:
        acc = acc.union(unary_union(batch)) if dark else acc.difference(unary_union(batch))
    return acc


def holes(paths):
    """(x, y, diameter, plated, length) of every hole in the set's Excellon files: a slot at its centre with its length.
    Read here rather than with gerbonara, which also reports a slot's start as a separate hole. Plating comes from
    each tool's X2 aperture function, else the file's, else the file name."""
    out = []
    for p in paths:
        if not re.search(r"\.(drl|xln|exc)$", p, re.I):
            continue
        text = open(p, errors="replace").read()
        inch = bool(re.search(r"^INCH", text, re.M))
        k = 25.4 if inch else 1.0
        ff = re.search(r"TF\.FileFunction,(\w+)", text)
        name = os.path.basename(p).lower()
        file_plated = {"Plated": True, "NonPlated": False}.get(ff.group(1) if ff else "", None)
        if file_plated is None:
            file_plated = not ("npth" in name or "nonplated" in name)
        tools, pend, cur = {}, None, None
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"; #@! TA\.AperFunction,(\w+)", line)
            if m:
                pend = {"Plated": True, "NonPlated": False}.get(m.group(1))
                continue
            m = re.match(r"T(\d+)C([\d.]+)", line)
            if m:
                tools[int(m.group(1))] = (float(m.group(2)) * k, file_plated if pend is None else pend)
                pend = None
                continue
            m = re.match(r"T(\d+)$", line)
            if m:
                cur = int(m.group(1))
                continue
            m = re.match(r"X([-\d.]+)Y([-\d.]+)(?:G85X([-\d.]+)Y([-\d.]+))?$", line)
            if m and cur in tools:
                d, pl = tools[cur]
                x1, y1 = float(m.group(1)) * k, float(m.group(2)) * k
                if m.group(3):
                    x2, y2 = float(m.group(3)) * k, float(m.group(4)) * k
                    out.append(((x1 + x2) / 2, (y1 + y2) / 2, d, pl, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 4)))
                else:
                    out.append((x1, y1, d, pl, 0.0))
            elif re.match(r"G85X([-\d.]+)Y([-\d.]+)$", line) and out and out[-1][4] == 0.0:
                # a slot whose end is written on the next line: the hole before it is its start
                m2 = re.match(r"G85X([-\d.]+)Y([-\d.]+)$", line)
                x1, y1, d, pl, _ = out.pop()
                x2, y2 = float(m2.group(1)) * k, float(m2.group(2)) * k
                out.append(((x1 + x2) / 2, (y1 + y2) / 2, d, pl, round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 4)))
            elif re.match(r"[XY]", line):
                raise SystemExit(f"{p}: drill line {line!r} not understood")
    return out


def pieces(g):
    from shapely.geometry import GeometryCollection
    if g.is_empty:
        return []
    return [q for q in getattr(g, "geoms", [g]) if q.area >= NOISE_MM2 and not q.buffer(-NOISE_WIDTH / 2).is_empty]


def zone_fills(board_path, dx, dy):
    """Each copper layer's zone fills on the board set A was made from, per net, in A's Gerber frame moved onto B's
    (KiCad plots y up from the board's origin)."""
    import pcbnew
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    b = pcbnew.LoadBoard(board_path)
    names = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    out = {}
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        for key, lid in names.items():
            if not z.IsOnLayer(lid):
                continue
            sps = z.GetFilledPolysList(lid)
            for i in range(sps.OutlineCount()):
                o = sps.Outline(i)
                pts = [(pcbnew.ToMM(o.CPoint(j).x) + dx, -pcbnew.ToMM(o.CPoint(j).y) + dy) for j in range(o.PointCount())]
                holes = []
                for h in range(sps.HoleCount(i)):
                    hh = sps.Hole(i, h)
                    holes.append([(pcbnew.ToMM(hh.CPoint(j).x) + dx, -pcbnew.ToMM(hh.CPoint(j).y) + dy) for j in range(hh.PointCount())])
                out.setdefault((key, z.GetNetname()), []).append(Polygon(pts, holes).buffer(0))
    return {k: unary_union(v) for k, v in out.items()}


def compare(a_src, b_src, explain_path=None, board=None):
    from shapely.affinity import translate
    from shapely.geometry import box
    ex = tomllib.load(open(explain_path, "rb")).get("explain", []) if explain_path else []
    fa, fb = files_of(a_src), files_of(b_src)
    la, lb = find_layers(fa), find_layers(fb)
    # a layer in one set only counts when it has something on it
    res = {"layers": {}, "missing": sorted(k for k in set(la) ^ set(lb) if layer_shape((la.get(k) or lb.get(k))).area > 0), "ok": True}
    if "Edge.Cuts" not in la or "Edge.Cuts" not in lb:
        return {"ok": False, "error": "both sets need a board outline (Edge.Cuts)", "found_a": la, "found_b": lb}
    ea, eb = layer_shape(la["Edge.Cuts"]).bounds, layer_shape(lb["Edge.Cuts"]).bounds
    dx, dy = (eb[0] + eb[2] - ea[0] - ea[2]) / 2, (eb[1] + eb[3] - ea[1] - ea[3]) / 2
    res["outline"] = {"a_size": [round(ea[2] - ea[0], 3), round(ea[3] - ea[1], 3)], "b_size": [round(eb[2] - eb[0], 3), round(eb[3] - eb[1], 3)], "shift": [round(dx, 4), round(dy, 4)]}
    if max(abs((ea[2] - ea[0]) - (eb[2] - eb[0])), abs((ea[3] - ea[1]) - (eb[3] - eb[1]))) > 0.2:
        res["ok"] = False
        res["error"] = "the board outlines differ in size by more than 0.2 mm"
    fills = zone_fills(board, dx, dy) if board else {}
    if any(e.get("zone_net") for e in ex) and not board:
        return {"ok": False, "error": "an explanation names a zone_net; give the board set A was made from"}

    def explains(e, key, side, q):
        if e.get("layer") not in (key, "*") or e.get("side", "both") not in (side, "both"):
            return False
        if e.get("zone_net"):
            # A's own copper that is wholly a zone fill of that net (B, the older set, lacks it)
            f = fills.get((key, e["zone_net"]))
            return side == "a" and f is not None and f.buffer(0.01).contains(q)
        where = bool(e.get("whole")) or ("rect" in e and box(*e["rect"]).buffer(0.05).contains(q)) or ("rect" not in e and "thinner_than_mm" in e)
        # thinner_than_mm: only a piece no wider than that anywhere (an outline drawn a little differently)
        thin = "thinner_than_mm" not in e or q.buffer(-e["thinner_than_mm"] / 2).is_empty
        return where and thin
    for key in sorted(set(la) & set(lb)):
        if key == "Edge.Cuts":
            continue
        A, B = translate(layer_shape(la[key]), dx, dy), layer_shape(lb[key])
        out = {"a_mm2": round(A.area, 3), "b_mm2": round(B.area, 3), "explained": [], "unexplained": []}
        for side, diff in (("a", A.difference(B)), ("b", B.difference(A))):
            for q in pieces(diff):
                why = next((e["why"] for e in ex if explains(e, key, side, q)), None)
                item = {"side": side, "mm2": round(q.area, 4), "bbox": [round(v, 3) for v in q.bounds]}
                if why:
                    item["why"] = why
                    out["explained"].append(item)
                else:
                    out["unexplained"].append(item)
        out["unexplained"].sort(key=lambda i: -i["mm2"])
        if out["unexplained"]:
            res["ok"] = False
        res["layers"][key] = out
    ha = [(x + dx, y + dy, d, p, ln) for x, y, d, p, ln in holes(fa)]
    hb = holes(fb)
    used, only_a = set(), []
    for h in ha:
        k = next((i for i, g in enumerate(hb) if i not in used and abs(g[0] - h[0]) <= HOLE_TOL and abs(g[1] - h[1]) <= HOLE_TOL and abs(g[2] - h[2]) <= HOLE_TOL and g[3] == h[3] and abs(g[4] - h[4]) <= HOLE_TOL), None)
        if k is None:
            only_a.append(h)
        else:
            used.add(k)
    only_b = [g for i, g in enumerate(hb) if i not in used]

    def hole_why(h, side):
        return next((e["why"] for e in ex if e.get("layer") == "drill" and e.get("side", "both") in (side, "both") and (e.get("whole") or box(*e["rect"]).contains(box(h[0] - h[2] / 2, h[1] - h[2] / 2, h[0] + h[2] / 2, h[1] + h[2] / 2)))), None)
    fmt = lambda h, s: {"side": s, "at": [round(h[0], 3), round(h[1], 3)], "d": round(h[2], 3), "plated": h[3], "slot": h[4], **({"why": hole_why(h, s)} if hole_why(h, s) else {})}
    drill = {"a": len(ha), "b": len(hb), "matched": len(used), "differ": [fmt(h, "a") for h in only_a] + [fmt(h, "b") for h in only_b]}
    if any("why" not in h for h in drill["differ"]):
        res["ok"] = False
    res["drill"] = drill
    return res


# DFM limits from GUIDELINES.md's JLCPCB table (mm)
DFM = dict(trace=0.15, gap=0.15, cu_edge=0.3, hole_hole=0.5, silk_line=0.15)


def verify(folder, board_path):
    """Connectivity rebuilt from the Gerbers and drill files alone, named by the board's pads, and DFM on the files.

    Each copper layer's islands are joined through plated holes and slots. Each pad of the board is found by its
    place in an island of a layer it is on. A net in two or more groups of islands is open; a group holding two nets
    is a short, unless every net in it belongs to one net-tie footprint's pads."""
    import pcbnew
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    paths = files_of(folder)
    lay = find_layers(paths)
    cu = sorted((k for k in lay if k.endswith(".Cu")), key=lambda k: (k != "F.Cu", k == "B.Cu", k))
    shapes = {k: layer_shape(lay[k]) for k in cu}
    islands = []   # (layer, polygon)
    for k in cu:
        for q in getattr(shapes[k], "geoms", [shapes[k]]):
            if not q.is_empty:
                islands.append((k, q))
    parent = list(range(len(islands)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    tree = STRtree([q for _, q in islands])
    hl = holes(paths)
    for x, y, d, plated, ln in hl:
        if not plated:
            continue
        pt = Point(x, y)
        hit = [int(i) for i in tree.query(pt) if islands[int(i)][1].buffer(1e-3).contains(pt)]
        for a, b in zip(hit, hit[1:]):
            parent[find(a)] = find(b)
    b = pcbnew.LoadBoard(board_path)
    ties = []
    for f in b.GetFootprints():
        if f.IsNetTie():
            ties.append({p.GetNetname() for p in f.Pads() if p.GetNetname()})
    names = {pcbnew.F_Cu: "F.Cu", pcbnew.B_Cu: "B.Cu"}
    for i in range(1, 31):
        lid = getattr(pcbnew, f"In{i}_Cu", None)
        if lid is not None:
            names[lid] = f"In{i}.Cu"
    groups, unplaced = {}, []
    for f in b.GetFootprints():
        for p in f.Pads():
            net = p.GetNetname()
            if not net:
                continue
            pt = Point(pcbnew.ToMM(p.GetPosition().x), -pcbnew.ToMM(p.GetPosition().y))
            g = None
            for lid in p.GetLayerSet().CuStack():
                k = names.get(lid)
                if k not in shapes:
                    continue
                for i in tree.query(pt):
                    if islands[int(i)][0] == k and islands[int(i)][1].buffer(1e-3).contains(pt):
                        g = find(int(i))
                        break
                if g is not None:
                    break
            if g is None:
                unplaced.append(f"{f.GetReference()}.{p.GetNumber()} ({net})")
            else:
                groups.setdefault(g, set()).add(net)
    by_net = {}
    for g, nets in groups.items():
        for n in nets:
            by_net.setdefault(n, set()).add(g)
    opens = sorted(n for n, gs in by_net.items() if len(gs) > 1)
    shorts = sorted(" / ".join(sorted(ns)) for ns in groups.values() if len(ns) > 1 and not any(ns <= t for t in ties))
    # DFM
    findings = []
    edge = layer_shape(lay["Edge.Cuts"]) if "Edge.Cuts" in lay else None
    outline = None
    if edge is not None and not edge.is_empty:
        from shapely.ops import polygonize
        rings = list(polygonize(edge.boundary)) if hasattr(edge, "boundary") else []
        # the drawn outline is a band; its inside ring grown by half the band's width is the cut line
        inner = max((r for r in rings if not r.buffer(-1e-3).intersects(edge.buffer(-1e-4))), key=lambda r: r.area, default=None)
        if inner is not None:
            half = edge.area / (2 * inner.exterior.length) if inner.exterior.length else 0
            outline = inner.buffer(half, join_style=2)
    net_of = {}
    for g, ns in groups.items():
        net_of[g] = ns
    for idx, (k, q) in enumerate(islands):
        if q.buffer(-DFM["trace"] / 2 + 1e-4).is_empty:
            findings.append({"rule": "trace", "layer": k, "at": [round(v, 3) for v in q.centroid.coords[0]], "detail": f"copper narrower than {DFM['trace']} mm everywhere"})
        if outline is not None:
            dist = outline.exterior.distance(q)
            if dist < DFM["cu_edge"] - 1e-3:
                findings.append({"rule": "cu_edge", "layer": k, "at": [round(v, 3) for v in q.centroid.coords[0]], "detail": f"copper {dist:.3f} mm from the board edge"})
    for k in cu:
        idx = [i for i, (kk, _) in enumerate(islands) if kk == k]
        t = STRtree([islands[i][1] for i in idx])
        for a in idx:
            for jj in t.query(islands[a][1].buffer(DFM["gap"])):
                c = idx[int(jj)]
                if c <= a or find(a) == find(c):
                    continue
                dist = islands[a][1].distance(islands[c][1])
                if dist < DFM["gap"] - 1e-3:
                    pa, pb = islands[a][1].centroid, islands[c][1].centroid
                    findings.append({"rule": "gap", "layer": k, "at": [round(pa.x, 3), round(pa.y, 3)], "detail": f"{dist:.3f} mm between {sorted(net_of.get(find(a), {'?'}))} and {sorted(net_of.get(find(c), {'?'}))}"})
    # each hole's copper group (None for a hole in no copper): holes of one group may sit closer
    def hole_group(x, y):
        pt = Point(x, y)
        for i in tree.query(pt):
            if islands[int(i)][1].buffer(1e-3).contains(pt):
                return find(int(i))
        return None
    hg = [hole_group(x, y) for x, y, *_ in hl]
    for i in range(len(hl)):
        for j in range(i + 1, len(hl)):
            (x1, y1, d1, p1, l1), (x2, y2, d2, p2, l2) = hl[i], hl[j]
            gap = math.hypot(x1 - x2, y1 - y2) - (d1 + l1) / 2 - (d2 + l2) / 2
            if gap < DFM["hole_hole"] - 1e-3 and not (hg[i] is not None and hg[i] == hg[j]):
                findings.append({"rule": "hole_hole", "layer": "drill", "at": [round(x1, 3), round(y1, 3)], "detail": f"{gap:.3f} mm edge to edge from the hole at ({x2:.3f}, {y2:.3f})"})
    for side in ("F", "B"):
        sk, mk, ck = f"{side}.Silk", f"{side}.Mask", f"{side}.Cu"
        if sk in lay:
            silk = layer_shape(lay[sk])
            # thin parts, alone or joined to wider ink: what an opening (shrink, then grow back) removes
            r = DFM["silk_line"] / 2 - 0.03
            thin = silk.difference(silk.buffer(-r, join_style=2).buffer(r + 0.005, join_style=2))
            for q in getattr(thin, "geoms", [thin]):
                if not q.is_empty and q.area > 0.01 and not q.buffer(-0.01).is_empty:
                    findings.append({"rule": "silk_line", "layer": sk, "at": [round(v, 3) for v in q.centroid.coords[0]], "detail": f"{q.area:.3f} mm² of silkscreen under {2 * r:.2f} mm wide"})
            if mk in lay and ck in shapes:
                bare = layer_shape(lay[mk]).intersection(shapes[ck])
                over = silk.intersection(bare)
                for q in getattr(over, "geoms", [over]):
                    if not q.is_empty and q.area > 0.005:
                        findings.append({"rule": "silk_on_copper", "layer": sk, "at": [round(v, 3) for v in q.centroid.coords[0]], "detail": f"{q.area:.3f} mm² of silkscreen on exposed copper"})
    return {"layers": cu, "islands": len(islands), "plated_holes": sum(1 for h in hl if h[3]), "nets": len(by_net), "opens": opens, "shorts": shorts, "unplaced_pads": unplaced, "dfm": findings}


def make_zip(folder, dest):
    """Every file of a folder in a zip, sorted, with one fixed date, so the same files give the same bytes."""
    names = sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            zi = zipfile.ZipInfo(n, date_time=(2020, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, open(os.path.join(folder, n), "rb").read())
    return {"zip": dest, "files": names}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "verify":
        print(json.dumps(verify(sys.argv[2], sys.argv[3])))
    elif cmd == "zip":
        print(json.dumps(make_zip(sys.argv[2], sys.argv[3])))
    elif cmd == "compare":
        arg = lambda i: sys.argv[i] if len(sys.argv) > i and sys.argv[i] else None
        print(json.dumps(compare(sys.argv[2], sys.argv[3], arg(4), arg(5))))
    else:
        raise SystemExit(f"unknown command {cmd}")
