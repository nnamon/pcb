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
        try:
            pts = [tuple(q) for q, _, _ in p.approximate_arcs().segments]
        except ZeroDivisionError:
            # an arc of no radius (KiCad writes one for a zero-length arc): its end points are the shape
            pts = [tuple(q) for q in p.outline]
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


def slot(x1, y1, x2, y2, d, pl):
    """A slot as (centre x, y, width, plated, length between its end centres, direction x, y)."""
    ln = math.hypot(x2 - x1, y2 - y1)
    ux, uy = ((x2 - x1) / ln, (y2 - y1) / ln) if ln else (1.0, 0.0)
    return ((x1 + x2) / 2, (y1 + y2) / 2, d, pl, round(ln, 4), ux, uy)


def hole_shape(h):
    """A hole as a stadium (a slot) or a circle."""
    from shapely.geometry import LineString, Point
    x, y, d, _, ln, ux, uy = h
    if ln <= 0:
        return Point(x, y).buffer(d / 2, 32)
    return LineString([(x - ux * ln / 2, y - uy * ln / 2), (x + ux * ln / 2, y + uy * ln / 2)]).buffer(d / 2, 32)


def holes(paths):
    """(x, y, diameter, plated, length, direction x, y) of every hole in the set's Excellon files: a slot at its centre with its length.
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
                    out.append(slot(x1, y1, x2, y2, d, pl))
                else:
                    out.append((x1, y1, d, pl, 0.0, 1.0, 0.0))
            elif re.match(r"G85X([-\d.]+)Y([-\d.]+)$", line) and out and out[-1][4] == 0.0:
                # a slot whose end is written on the next line: the hole before it is its start
                m2 = re.match(r"G85X([-\d.]+)Y([-\d.]+)$", line)
                x1, y1, d, pl = out.pop()[:4]
                x2, y2 = float(m2.group(1)) * k, float(m2.group(2)) * k
                out.append(slot(x1, y1, x2, y2, d, pl))
            elif re.match(r"[XY]", line):
                raise SystemExit(f"{p}: drill line {line!r} not understood")
    return out


def pieces(g):
    from shapely.geometry import GeometryCollection
    if g.is_empty:
        return []
    return [q for q in getattr(g, "geoms", [g]) if q.area >= NOISE_MM2 and not q.buffer(-NOISE_WIDTH / 2).is_empty]


def board_centre(b):
    """The centre of a pcbnew board's outline bounding box, in KiCad's frame (mm, y down)."""
    import pcbnew
    xs, ys = [], []
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            bb = d.GetBoundingBox()
            xs += [pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())]
            ys += [pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def zone_fills(board_path):
    """Each copper layer's zone fills on the board set A was made from, per net, about the outline's centre, y up:
    the frame pcb release plots in."""
    import pcbnew
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    b = pcbnew.LoadBoard(board_path)
    cx, cy = board_centre(b)
    dx, dy = -cx, cy
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


EXPLAIN_KEYS = {"layer", "side", "rect", "whole", "thinner_than_mm", "zone_net", "why"}


def check_explain(ex):
    """Problems in explain entries: unknown keys, no reason, no place, a bad side or rect."""
    out = []
    for i, e in enumerate(ex):
        tag = f"explain {i + 1} ({e.get('layer', '?')})"
        if set(e) - EXPLAIN_KEYS:
            out.append(f"{tag}: unknown keys {sorted(set(e) - EXPLAIN_KEYS)}")
        if not str(e.get("why", "")).strip() or not e.get("layer"):
            out.append(f"{tag}: needs a layer and a why")
        if e.get("side", "both") not in ("a", "b", "both"):
            out.append(f"{tag}: side is a, b or both")
        if not (e.get("whole") or "rect" in e or "zone_net" in e or ("thinner_than_mm" in e and e.get("layer") != "drill")):
            out.append(f"{tag}: needs rect, whole, zone_net or thinner_than_mm")
        if "rect" in e and not (isinstance(e["rect"], list) and len(e["rect"]) == 4 and e["rect"][2] > e["rect"][0] and e["rect"][3] > e["rect"][1]):
            out.append(f"{tag}: rect is [x0, y0, x1, y1]")
    return out


def outline_centre(edge):
    b = edge.bounds
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def same_way(g, h):
    """Two slots run the same way, up to sign (review 16, 31); round holes always do."""
    if g[4] <= HOLE_TOL and h[4] <= HOLE_TOL:
        return True
    return abs(g[5] * h[6] - g[6] * h[5]) <= 0.02


def unread(paths, found):
    """Gerber files a set holds that no layer was read from, and layers two files claim (review 16, 34)."""
    used = set(found.values())
    out = []
    for p in paths:
        if re.search(r"\.(gbr|g[a-z0-9]{2}|gm1)$", p, re.I) and p not in used and not re.search(r"\.(gbrjob)$", p, re.I):
            out.append(f"{os.path.basename(p)} (function {file_function(p) or 'none'}) is not a layer compare-gerbers reads")
    return out


def compare(a_src, b_src, explain_path=None, board=None, align=False):
    from shapely.affinity import translate
    from shapely.geometry import box
    ex = tomllib.load(open(explain_path, "rb")).get("explain", []) if explain_path else []
    bad = check_explain(ex)
    if bad:
        return {"ok": False, "error": "; ".join(bad)}
    fa, fb = files_of(a_src), files_of(b_src)
    la, lb = find_layers(fa), find_layers(fb)
    if "Edge.Cuts" not in la or "Edge.Cuts" not in lb:
        return {"ok": False, "error": "both sets need a board outline (Edge.Cuts)", "found_a": la, "found_b": lb}
    if len(set(la) & set(lb) - {"Edge.Cuts"}) == 0:
        return {"ok": False, "error": "the two sets share no layer besides the outline", "found_a": la, "found_b": lb}
    for nm, fl, lay in (("A", fa, la), ("B", fb, lb)):
        extra = unread(fl, lay)
        if extra:
            return {"ok": False, "error": f"set {nm}: " + "; ".join(extra)}
    res = {"layers": {}, "missing": [], "ok": True}
    ea, eb = layer_shape(la["Edge.Cuts"]), layer_shape(lb["Edge.Cuts"])
    (cax, cay), (cbx, cby) = outline_centre(ea), outline_centre(eb)
    ea, eb = ea.bounds, eb.bounds
    # the sets must share a frame, as the fab and the assembler read them together; --align moves A onto B instead
    dx, dy = (cbx - cax, cby - cay) if align else (0.0, 0.0)
    res["outline"] = {"a_size": [round(ea[2] - ea[0], 3), round(ea[3] - ea[1], 3)], "b_size": [round(eb[2] - eb[0], 3), round(eb[3] - eb[1], 3)], "shift": [round(cbx - cax, 4), round(cby - cay, 4)], "aligned": align}
    if max(abs((ea[2] - ea[0]) - (eb[2] - eb[0])), abs((ea[3] - ea[1]) - (eb[3] - eb[1]))) > 0.2:
        res["ok"] = False
        res["error"] = "the board outlines differ in size by more than 0.2 mm"
    elif not align and max(abs(cbx - cax), abs(cby - cay)) > 0.05:
        res["ok"] = False
        res["error"] = f"the sets use different origins: the outline's centre is at ({cax:.3f}, {cay:.3f}) in A and ({cbx:.3f}, {cby:.3f}) in B"
    if any(e.get("zone_net") for e in ex) and not board:
        return {"ok": False, "error": "an explanation names a zone_net; give the board set A was made from"}
    fills = {k: translate(v, cax + dx, cay + dy) for k, v in zone_fills(board).items()} if board else {}

    def explains(e, key, side, q):
        if e.get("layer") not in (key, "*") or e.get("side", "both") not in (side, "both"):
            return False
        if e.get("zone_net"):
            # A's own copper that is wholly a zone fill of that net (B, the older set, lacks it)
            f = fills.get((key, e["zone_net"]))
            return side == "a" and f is not None and q.difference(f.buffer(0.01)).area < 1e-4
        where = bool(e.get("whole")) or ("rect" in e and box(*e["rect"]).buffer(0.05).contains(q)) or ("rect" not in e and "thinner_than_mm" in e)
        # thinner_than_mm: only a piece no wider than that anywhere (an outline drawn a little differently)
        thin = "thinner_than_mm" not in e or q.buffer(-e["thinner_than_mm"] / 2).is_empty
        return where and thin
    # a layer with something on it in one set only: the whole layer differs, unless explained
    for key in sorted(set(la) ^ set(lb)):
        side, path = ("a", la[key]) if key in la else ("b", lb[key])
        g = layer_shape(path)
        if g.area <= 0:
            continue
        why = next((e["why"] for e in ex if e.get("layer") == key and e.get("side", "both") in (side, "both") and e.get("whole")), None)
        res["missing"].append(key)
        item = {"side": side, "mm2": round(g.area, 4), "bbox": [round(v, 3) for v in g.bounds], "layer_only_here": True}
        res["layers"][key] = {"a_mm2": round(g.area, 3) if side == "a" else 0.0, "b_mm2": round(g.area, 3) if side == "b" else 0.0, "explained": [dict(item, why=why)] if why else [], "unexplained": [] if why else [item]}
        if not why:
            res["ok"] = False
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
    ha = [(h[0] + dx, h[1] + dy) + tuple(h[2:]) for h in holes(fa)]
    hb = holes(fb)
    used, only_a = set(), []
    for h in ha:
        k = next((i for i, g in enumerate(hb) if i not in used and abs(g[0] - h[0]) <= HOLE_TOL and abs(g[1] - h[1]) <= HOLE_TOL and abs(g[2] - h[2]) <= HOLE_TOL and g[3] == h[3] and abs(g[4] - h[4]) <= HOLE_TOL and same_way(g, h)), None)
        if k is None:
            only_a.append(h)
        else:
            used.add(k)
    only_b = [g for i, g in enumerate(hb) if i not in used]

    def hole_why(h, side):
        return next((e["why"] for e in ex if e.get("layer") == "drill" and e.get("side", "both") in (side, "both") and (e.get("whole") or ("rect" in e and box(*e["rect"]).contains(hole_shape(h))))), None)
    fmt = lambda h, s: {"side": s, "at": [round(h[0], 3), round(h[1], 3)], "d": round(h[2], 3), "plated": h[3], "slot": h[4], **({"why": hole_why(h, s)} if hole_why(h, s) else {})}
    drill = {"a": len(ha), "b": len(hb), "matched": len(used), "differ": [fmt(h, "a") for h in only_a] + [fmt(h, "b") for h in only_b]}
    if any("why" not in h for h in drill["differ"]):
        res["ok"] = False
    res["drill"] = drill
    return res


# DFM limits from GUIDELINES.md's JLCPCB table (mm)
DFM = dict(trace=0.15, gap=0.15, cu_edge=0.3, hole_hole=0.5, silk_line=0.15, npth_copper=0.1, inner_hole_comp=0.3, inner_hole_via=0.2)
# a feature counts as narrow when an opening this much under half the limit removes it: rounding in the plot. Copper
# 0.0005 (review 16, 32: 0.005 let 0.14 mm through); silkscreen 0.005, as the art grown for print on the ordered
# paddle-keyer has pieces of 0.14 to 0.15 mm, which printed
SLACK = 0.0005
SILK_SLACK = 0.005


def narrow_parts(g, width, slack=None):
    """What an opening (shrink by half the width, grow back) removes from a shape, past corner trimmings: the parts
    narrower than `width`."""
    from shapely.geometry import Polygon
    if g.is_empty:
        return []
    r = width / 2 - (SLACK if slack is None else slack)
    thin = g.difference(g.buffer(-r, quad_segs=8).buffer(r + 0.002, quad_segs=8))
    # a square corner loses about r²(1 - π/4); a narrow strip is longer than it is wide
    return [q for q in getattr(thin, "geoms", [thin]) if isinstance(q, Polygon) and q.area > max(0.01, 4 * r * r) and not q.buffer(-0.005).is_empty]


def verify(folder, board_path):
    """Connectivity rebuilt from the Gerbers and drill files alone, named by the board's pads, and DFM on the files.

    The files are in pcb release's frame: the board outline's centre at the origin, y up. Each copper layer's islands
    are joined through plated holes and slots. Each pad of the board is found by its place in an island of a layer it
    is on. A net in two or more groups of islands is open; a group holding two nets is a short, unless every net in it
    belongs to one net-tie footprint's pads."""
    import pcbnew
    from shapely.geometry import LineString, Point, box
    from shapely.ops import polygonize, unary_union
    from shapely.prepared import prep
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
    preps = [prep(q) for _, q in islands]
    parent = list(range(len(islands)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    tree = STRtree([q for _, q in islands])

    def islands_at(pt, layer=None):
        probe = pt.buffer(1e-3, 4)
        return [int(i) for i in tree.query(probe) if (layer is None or islands[int(i)][0] == layer) and preps[int(i)].intersects(probe)]
    hl = holes(paths)
    for h in hl:
        if not h[3]:
            continue
        hit = islands_at(Point(h[0], h[1]))
        for a, b in zip(hit, hit[1:]):
            parent[find(a)] = find(b)
    b = pcbnew.LoadBoard(board_path)
    cx, cy = board_centre(b)
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
            pt = Point(pcbnew.ToMM(p.GetPosition().x) - cx, cy - pcbnew.ToMM(p.GetPosition().y))
            g = None
            for lid in p.GetLayerSet().CuStack():
                k = names.get(lid)
                if k not in shapes:
                    continue
                hit = islands_at(pt, k)
                if hit:
                    g = find(hit[0])
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
    findings = []
    at = lambda q: [round(v, 3) for v in q.representative_point().coords[0]]
    # the outline: the drawn band's half width, every ring (cut-outs too), and the board's outer shape
    edge = layer_shape(lay["Edge.Cuts"]) if "Edge.Cuts" in lay else None
    board_shape, half = None, 0.0
    if edge is not None and not edge.is_empty:
        regions = list(polygonize(edge.boundary))
        inner = [r for r in regions if not r.buffer(-1e-3).intersects(edge.buffer(-1e-4))]
        if inner:
            perim = sum(r.exterior.length for r in inner)
            half = edge.area / (2 * perim) if perim else 0.0
            outer = max(inner, key=lambda r: r.area)
            cutouts = [r for r in inner if r is not outer and outer.contains(r.representative_point())]
            board_shape = outer.buffer(half, join_style=2)
            for c in cutouts:
                board_shape = board_shape.difference(c.buffer(-half, join_style=2) if c.area > 4 * half * half else c)
    net_of = dict(groups)
    for idx, (k, q) in enumerate(islands):
        for t in narrow_parts(q, DFM["trace"]):
            findings.append({"rule": "trace", "layer": k, "at": at(t), "detail": f"{t.area:.3f} mm² of copper under {DFM['trace']} mm wide"})
        if edge is not None:
            if board_shape is not None and not board_shape.buffer(1e-3).contains(q):
                findings.append({"rule": "off_board", "layer": k, "at": at(q), "detail": "copper outside the board outline"})
            dist = q.distance(edge) + half if not q.intersects(edge) else 0.0
            if dist < DFM["cu_edge"] - 1e-3:
                findings.append({"rule": "cu_edge", "layer": k, "at": at(q), "detail": f"copper {dist:.3f} mm from the board edge"})
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
                    findings.append({"rule": "gap", "layer": k, "at": at(islands[a][1]), "detail": f"{dist:.3f} mm between {sorted(net_of.get(find(a), {'?'}))} and {sorted(net_of.get(find(c), {'?'}))}"})
    # holes, slots as stadiums; holes in one copper group may sit closer
    hs = [hole_shape(h) for h in hl]
    hg = []
    for h in hl:
        hit = islands_at(Point(h[0], h[1]))
        hg.append(find(hit[0]) if hit else None)
    ht = STRtree(hs)
    for i in range(len(hl)):
        for jj in ht.query(hs[i].buffer(DFM["hole_hole"])):
            j = int(jj)
            if j <= i or (hg[i] is not None and hg[i] == hg[j]):
                continue
            gap = hs[i].distance(hs[j])
            if gap < DFM["hole_hole"] - 1e-3:
                findings.append({"rule": "hole_hole", "layer": "drill", "at": [round(hl[i][0], 3), round(hl[i][1], 3)], "detail": f"{gap:.3f} mm edge to edge from the hole at ({hl[j][0]:.3f}, {hl[j][1]:.3f})"})
    # copper over or beside an unplated hole: a fill made before the hole, or plotted stale (review 16, 30)
    for i, h in enumerate(hl):
        if h[3]:
            continue
        near = hs[i].buffer(DFM["npth_copper"])
        for k in cu:
            if shapes[k].intersects(near):
                gap = shapes[k].distance(hs[i])
                findings.append({"rule": "npth_copper", "layer": k, "at": [round(h[0], 3), round(h[1], 3)], "detail": f"copper {gap:.3f} mm from an unplated hole of {h[2]:.3f} mm"})
    # inner copper of another net beside a plated hole: JLCPCB's multilayer limit, 0.3 mm from a component hole and
    # 0.2 mm from a via (GUIDELINES.md; review 17, 40). A hole at a plated pad of the board is a component hole
    pth = [(pcbnew.ToMM(p.GetPosition().x) - cx, cy - pcbnew.ToMM(p.GetPosition().y)) for f in b.GetFootprints() for p in f.Pads() if p.GetDrillSize().x > 0]
    inner_cu = [k for k in cu if k.startswith("In")]
    for i, h in enumerate(hl):
        if not h[3] or not inner_cu:
            continue
        comp = any(abs(h[0] - px) < 0.02 and abs(h[1] - py) < 0.02 for px, py in pth)
        lim = DFM["inner_hole_comp"] if comp else DFM["inner_hole_via"]
        for jj in tree.query(hs[i].buffer(lim)):
            j = int(jj)
            k, q = islands[j]
            if k not in inner_cu or (hg[i] is not None and find(j) == hg[i]) or q.intersects(Point(h[0], h[1])):
                continue
            gap = q.distance(hs[i])
            if gap < lim - 1e-3:
                findings.append({"rule": "inner_hole", "layer": k, "at": [round(h[0], 3), round(h[1], 3)], "detail": f"{sorted(net_of.get(find(j), {'?'}))} copper {gap:.3f} mm from a {'component hole' if comp else 'via'} of {h[2]:.3f} mm (limit {lim} mm)"})
    for side in ("F", "B"):
        sk, mk, ck = f"{side}.Silk", f"{side}.Mask", f"{side}.Cu"
        if sk in lay:
            silk = layer_shape(lay[sk])
            for q in narrow_parts(silk, DFM["silk_line"], SILK_SLACK):
                findings.append({"rule": "silk_line", "layer": sk, "at": at(q), "detail": f"{q.area:.3f} mm² of silkscreen under {DFM['silk_line']} mm wide"})
            if mk in lay and ck in shapes:
                bare = layer_shape(lay[mk]).intersection(shapes[ck])
                over = silk.intersection(bare)
                for q in getattr(over, "geoms", [over]):
                    if not q.is_empty and q.area > 0.005:
                        findings.append({"rule": "silk_on_copper", "layer": sk, "at": at(q), "detail": f"{q.area:.3f} mm² of silkscreen on exposed copper"})
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
        print(json.dumps(compare(sys.argv[2], sys.argv[3], arg(4), arg(5), arg(6) == "align")))
    else:
        raise SystemExit(f"unknown command {cmd}")
