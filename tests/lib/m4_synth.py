"""Builders for the M4 cases (tests/cases/m4_cases.py): synthetic EasyEDA parts, KiCad netlists and pcb projects for
`pcb sync`, `pcb place` and `pcb parts`; small pcbnew boards for `pcb check`'s fab DRC; pcbnew queries and edits;
EasyEDA pad geometry and Gerber areas read with shapely. Adapted from the review 18, 19 and 20 reviewers' helpers
(tests/regressions@e17bfac/r18/r18lib.py, r19/r19lib.py, r20/r20lib.py and their probes).
"""
import json
import math
import os
import shutil
import subprocess
import sys

U = 0.254  # mm per EasyEDA unit


def fresh(d):
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)


# ---- EasyEDA parts

def eda(pads, pins, title="SYNPKG", origin=(4000, 3000)):
    """An EasyEDA component. pads: PAD records; pins: [(number, name)] or [(spice, shown, name)]."""
    sym = []
    for p in pins:
        sp, num, nm = (p[0], p[0], p[1]) if len(p) == 2 else p
        sym.append(f"P~show~0~{sp}~0~0~180~gge{sp}~0^^0~0^^M 0 0 h 10~#880000^^1~0~0~0~{nm}~start~~~#0000FF^^1~0~0~0~{num}~end~~~#0000FF^^0~0~0~0~M 0 0^^0~M 0 0")
    return {"result": {"title": title, "dataStr": {"head": {}, "shape": sym},
                       "packageDetail": {"title": title, "dataStr": {"head": {"x": str(origin[0]), "y": str(origin[1])}, "shape": list(pads)}}}}


def smd(num, x, y, w=4, h=6, rot=0):
    return f"PAD~RECT~{x}~{y}~{w}~{h}~1~~{num}~0~~{rot}~g{num}x{x}~0~~Y~0"


def pad(shape, x, y, w, h, layer, num, hole_r=0, pts="", rot=0, hlen="", hpts="", plated="Y"):
    """Any EasyEDA PAD record (review 18's easyeda18.py)."""
    return f"PAD~{shape}~{x}~{y}~{w}~{h}~{layer}~~{num}~{hole_r}~{pts}~{rot}~g{num}~{hlen}~{hpts}~{plated}~0"


def rect_pts(cx, cy, w, h, rot):
    """A rectangle's outline as EasyEDA stores it (field 10): turned clockwise on screen, y down."""
    a = math.radians(rot)
    c = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return " ".join(f"{cx + px * math.cos(a) - py * math.sin(a):.4f} {cy + px * math.sin(a) + py * math.cos(a):.4f}" for px, py in c)


def tht(num, x, y, w, h, rot, hole_r, slot, hp, shape="RECT"):
    """An EasyEDA plated pad, rot clockwise on screen (y down); field 10 its outline, turned. Returns (record, outline)."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts += [x + dx * c - dy * s, y + dx * s + dy * c]
    hps = " ".join(f"{v:.4f}" for v in hp) if hp else ""
    return f"PAD~{shape}~{x}~{y}~{w}~{h}~11~~{num}~{hole_r}~{' '.join(f'{v:.4f}' for v in pts)}~{rot}~g{num}~{slot}~{hps}~Y~0", pts


def holepts(x, y, rot_dir, length):
    """Hole points: the slot's centre line, `length` units long, at angle rot_dir clockwise on screen."""
    c, s = math.cos(math.radians(rot_dir)), math.sin(math.radians(rot_dir))
    return [x - c * length / 2, y - s * length / 2, x + c * length / 2, y + s * length / 2]


def jlc(code, ptype=0, stock=100000, lib="base", fetched="2026-11-04"):
    return {"fetched": fetched, "part": {"componentCode": code, "componentModelEn": "SYN-" + code, "componentLibraryType": lib,
                                         "componentProductType": ptype, "stockCount": stock}}


def eda_pad_list(comp):
    """JLCPCB's pads of a component: [(number, x, y, w, h)] in mm about its origin, y down."""
    pk = comp["result"]["packageDetail"]["dataStr"]
    ox, oy = float(pk["head"]["x"]), float(pk["head"]["y"])
    out = []
    for s in pk["shape"]:
        f = s.split("~")
        if f[0] == "PAD":
            out.append((f[8], (float(f[2]) - ox) * U, (float(f[3]) - oy) * U, float(f[4]) * U, float(f[5]) * U))
    return out


# ---- KiCad footprints and netlists

MOD_HEAD = ('(footprint "{n}" (version 20260206) (generator "m4cases") (layer "F.Cu")\n  (attr smd)\n'
            '  (property "Reference" "REF**" (at 0 0 0) (layer "F.SilkS") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
            '  (property "Value" "x" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
            '  (fp_rect (start -{c} -{c}) (end {c} {c}) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))\n')


def modfile(name, pads, court=2.4):
    """A project footprint. pads: [(number, x, y, w, h)] SMD rectangles, mm, y down."""
    t = MOD_HEAD.format(n=name, c=court)
    for n, x, y, w, h in pads:
        t += f'  (pad "{n}" smd rect (at {x:.4f} {y:.4f}) (size {w:.4f} {h:.4f}) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
    return t + ")\n"


def netlist(comps, nets):
    """comps: [(ref, value, footprint, lcsc[, extra s-expressions])]; nets: {name: [(ref, pin, function)]}."""
    q = lambda v: json.dumps(v, ensure_ascii=False)
    o = ['(export (version "E")', "  (components"]
    for c in comps:
        ref, value, fpn, lcsc = c[:4]
        props = c[4] if len(c) > 4 else ""
        f = f'(field (name "LCSC") {q(lcsc)})' if lcsc else ""
        o.append(f"    (comp (ref {q(ref)}) (value {q(value)}) (footprint {q(fpn)}) (fields {f}) {props})")
    o.append("  )\n  (nets")
    for i, (name, nodes) in enumerate(nets.items()):
        ns = " ".join(f'(node (ref {q(r)}) (pin {q(p)}) (pinfunction {q(fn)}) (pintype "passive"))' for r, p, fn in nodes)
        o.append(f'    (net (code "{i + 1}") (name {q(name)}) {ns})')
    o.append("  )\n)\n")
    return "\n".join(o)


def project(d, comps, nets, parts, place=(), extra="", rect=(30, 30), footprints=None, sides=("top",), records=None):
    """A pcb project from a netlist. parts: {code: EasyEDA json} (each with a JLCPCB record, or records[code]);
    place: [(ref, x, y, rot, side)]; footprints: {name: kicad_mod text} in footprints/."""
    fresh(d)
    os.makedirs(os.path.join(d, "parts"))
    for code, comp in parts.items():
        json.dump(comp, open(os.path.join(d, "parts", f"{code}.easyeda.json"), "w"))
        json.dump((records or {}).get(code) or jlc(code), open(os.path.join(d, "parts", f"{code}.jlc.json"), "w"))
    if footprints:
        os.makedirs(os.path.join(d, "footprints"))
        for n, t in footprints.items():
            open(os.path.join(d, "footprints", n + ".kicad_mod"), "w").write(t)
    open(os.path.join(d, "n.net"), "w", encoding="utf-8").write(netlist(comps, nets))
    t = ["schema = 1", "[project]", 'name = "syn"', 'version = "0.1.0"', 'board = "board.kicad_pcb"', "layers = 2",
         'fab = "jlcpcb-2layer-1.6mm"', 'netlist = "n.net"', "[outline]", f"rect_mm = [{rect[0]}, {rect[1]}]",
         "[assembly]", "machine_sides = [" + ", ".join(json.dumps(s) for s in sides) + "]"]
    for ref, x, y, rot, side in place:
        t += ["[[place]]", f'ref = "{ref}"', f"at = [{x}, {y}]", f"rot_deg = {rot}", f'side = "{side}"']
    open(os.path.join(d, "pcb.toml"), "w").write("\n".join(t) + "\n" + extra)
    return d


# ---- pcbnew

PRE = ("import sys, json, math, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1])\nFM = pcbnew.FromMM\nTM = pcbnew.ToMM\nmm = pcbnew.ToMM\n"
       "V = lambda x, y: pcbnew.VECTOR2I(FM(x), FM(y))\nfp = lambda r: b.FindFootprintByReference(r)\n")


def pcbnew_run(path, code, *args, save=True):
    """pcbnew code on a board (b), then a pcbnew save unless save=False; returns stdout's last line as JSON, if any."""
    o = subprocess.run([sys.executable, "-c", PRE + code + ("\npcbnew.SaveBoard(sys.argv[1], b)\n" if save else ""), path, *[str(a) for a in args]],
                       capture_output=True, text=True)
    if o.returncode:
        raise RuntimeError(f"pcbnew on {path}: {o.stderr[-1500:]}")
    lines = [x for x in o.stdout.splitlines() if x.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


# ---- EasyEDA geometry against the board (review 18's easyeda18.py)

READ_PADS = r'''
def lc(f):
    try:
        return f.GetFieldText("LCSC")
    except KeyError:
        return ""
out = {}
for f in b.GetFootprints():
    pos = f.GetPosition()
    pads = []
    for p in f.Pads():
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            pads.append({"n": "", "npth": True})
            continue
        lay = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        ps = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
        polys = []
        for k in range(ps.OutlineCount()):
            o = ps.Outline(k)
            polys.append([[mm(o.CPoint(i).x - pos.x), mm(o.CPoint(i).y - pos.y)] for i in range(o.PointCount())])
        d = None
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            d = {"size": [mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())], "ang": p.GetOrientationDegrees()}
        pads.append({"n": p.GetNumber(), "polys": polys, "drill": d})
    out[f.GetReference()] = {"lcsc": lc(f), "pads": pads}
print(json.dumps(out))
'''


def _eda_pads(comp):
    from shapely import affinity
    from shapely.geometry import LineString, Point, Polygon
    ds = comp["result"]["packageDetail"]["dataStr"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    L = lambda x, y: ((float(x) - ox) * U, (float(y) - oy) * U)
    out = []
    for s in ds["shape"]:
        f = s.split("~")
        if f[0] != "PAD":
            continue
        shape, cx, cy, w, h, layer, num = f[1], f[2], f[3], float(f[4]) * U, float(f[5]) * U, f[6], f[8]
        rot = float(f[11] or 0)
        c = L(cx, cy)
        pts = [float(v) for v in f[10].replace(",", " ").split()] if f[10].strip() else []
        pts = [L(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
        if shape in ("RECT", "POLYGON") and len(pts) >= 3:
            g = Polygon(pts)
        elif shape == "OVAL" and len(pts) == 2:
            g = LineString(pts).buffer(min(w, h) / 2, 64)
        elif shape in ("OVAL", "ELLIPSE"):
            r = min(w, h) / 2
            hl = max(w, h) / 2 - r
            base = LineString([(-hl, 0), (hl, 0)] if w >= h else [(0, -hl), (0, hl)]).buffer(r, 64) if hl > 1e-9 else Point(0, 0).buffer(r, 64)
            g = affinity.translate(affinity.rotate(base, rot, origin=(0, 0)), *c)
        else:
            g = affinity.translate(affinity.rotate(Polygon([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]), rot, origin=(0, 0)), *c)
        hole = None
        if f[9].strip() and float(f[9]) > 0:
            hr = float(f[9]) * U
            hlen = float(f[13]) * U if len(f) > 13 and f[13].strip() else 0
            hp = [float(v) for v in f[14].replace(",", " ").split()] if len(f) > 14 and f[14].strip() else []
            direction = math.degrees(math.atan2(hp[3] - hp[1], hp[2] - hp[0])) % 180 if hlen > 0 and len(hp) >= 4 else None
            hole = {"d": 2 * hr, "len": hlen, "dir": direction}
        out.append((num, g, hole, layer, shape, rot))
    return out


def _kicad_slot_dir(d):
    sx, sy = d["size"]
    if abs(sx - sy) < 1e-6:
        return None
    return ((0 if sx > sy else 90) - d["ang"]) % 180


def eda_misses(ref, comp, kpads):
    """Where a footprint on the board (READ_PADS's pads, at angle 0 on top) differs from EasyEDA's own pad outlines,
    holes and slot directions."""
    from shapely.geometry import Polygon
    misses = []
    ep = _eda_pads(comp)
    kp = [p for p in kpads if not p.get("npth")]
    if len(ep) != len(kp):
        misses.append(f"{ref}: {len(ep)} EasyEDA pads, {len(kp)} on the board")
    used = set()
    for num, g, hole, layer, shape, rot in ep:
        best = None
        for i, p in enumerate(kp):
            if i in used or p["n"] != num or not p["polys"]:
                continue
            diff = g.symmetric_difference(Polygon(p["polys"][0])).area
            if best is None or diff < best[0]:
                best = (diff, i)
        if best is None:
            misses.append(f"{ref}.{num}: no board pad")
            continue
        used.add(best[1])
        diff, i = best
        if diff > max(0.002, 0.01 * g.area):
            misses.append(f"{ref}.{num} {shape} rot {rot}: outline differs by {diff:.4f} mm2 (pad {g.area:.4f} mm2)")
        if (layer == "11") != (kp[i]["drill"] is not None):
            misses.append(f"{ref}.{num}: plated hole {'missing' if layer == '11' else 'extra'}")
        if hole and kp[i]["drill"]:
            d = kp[i]["drill"]
            want = sorted([hole["d"], hole["len"] if hole["len"] > 0 else hole["d"]])
            if max(abs(a - b) for a, b in zip(sorted(d["size"]), want)) > 2e-3:
                misses.append(f"{ref}.{num}: drill {d['size']} not {want}")
            if hole["dir"] is not None:
                kd = _kicad_slot_dir(d)
                if kd is None or min(abs(kd - hole["dir"]), 180 - abs(kd - hole["dir"])) > 1:
                    misses.append(f"{ref}.{num}: slot runs at {kd} degrees, EasyEDA's hole points at {hole['dir']:.1f}")
    return misses


# ---- small pcbnew boards for check's fab DRC (review 19's fab19.py)

FAB_BOARD = '''
import sys, pcbnew
out = sys.argv[1]
FM = pcbnew.FromMM
b = pcbnew.NewBoard(out)
b.SetCopperLayerCount(LAYERS)
ds = b.GetDesignSettings()
ds.m_MinClearance = 0; ds.m_TrackMinWidth = 0; ds.m_ViasMinSize = FM(0.1); ds.m_MinThroughDrill = FM(0.1)
ds.m_HoleClearance = 0; ds.m_HoleToHoleMin = 0; ds.m_CopperEdgeClearance = 0; ds.m_ViasMinAnnularWidth = 0
ds.m_NetSettings.GetDefaultNetclass().SetClearance(FM(0.1))
nets = {}
def net(n):
    if n not in nets:
        ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
    return nets[n]
def P(x, y):
    return pcbnew.VECTOR2I(FM(100 + x), FM(100 + y))
corners = [(0, 0), (40, 0), (40, 30), (0, 30)]
for i in range(4):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(FM(0.05))
    s.SetStart(P(*corners[i])); s.SetEnd(P(*corners[(i + 1) % 4])); b.Add(s)
def fp(ref, x, y, pads):
    """pads: (num, dx, dy, net, w, h) SMD, or (num, dx, dy, net, size, drill, 'pth')."""
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.SetValue(ref); f.SetPosition(P(x, y))
    f.Reference().SetVisible(False); f.Value().SetVisible(False)
    b.Add(f)
    for q in pads:
        p = pcbnew.PAD(f); p.SetNumber(q[0])
        if len(q) > 6:
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH); p.SetLayerSet(p.PTHMask()); p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            p.SetSize(pcbnew.VECTOR2I(FM(q[4]), FM(q[4]))); p.SetDrillSize(pcbnew.VECTOR2I(FM(q[5]), FM(q[5])))
        else:
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetLayerSet(p.SMDMask())
            p.SetSize(pcbnew.VECTOR2I(FM(q[4]), FM(q[5])))
        f.Add(p); p.SetPosition(P(x + q[1], y + q[2]))
        if q[3]:
            p.SetNet(net(q[3]))
    return f
def track(n, x0, y0, x1, y1, w, layer=pcbnew.F_Cu):
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1)); t.SetWidth(FM(w)); t.SetLayer(layer); t.SetNet(net(n)); b.Add(t)
def zone(n, layer, x0, y0, x1, y1, clearance):
    z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(net(n))
    o = z.Outline(); o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(FM(100 + x), FM(100 + y))
    z.SetLocalClearance(FM(clearance)); z.SetMinThickness(FM(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.Add(z)
'''


def fab_board(d, code, layers=2, dru=None):
    """A project with a pcbnew-built 40 x 30 mm board (zones unfilled) and a minimal pcb.toml."""
    fresh(d)
    r = subprocess.run([sys.executable, "-c", FAB_BOARD.replace("LAYERS", str(layers)) + code + "\npcbnew.SaveBoard(out, b)\n", os.path.join(d, "board.kicad_pcb")],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"fab_board {d}: {r.stderr[-1500:]}")
    if dru:
        open(os.path.join(d, "board.kicad_dru"), "w").write(dru)
    fab = {2: "jlcpcb-2layer-1.6mm", 4: "jlcpcb-4layer-1.6mm"}[layers]
    open(os.path.join(d, "pcb.toml"), "w").write(f'schema = 1\n\n[project]\nname = "s"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = {layers}\nfab = "{fab}"\n')
    return d


def gerber_dark(path):
    """A Gerber layer's dark area, as one shapely geometry (mm)."""
    from gerbonara import GerberFile
    from gerbonara.graphic_primitives import Arc, ArcPoly, Circle, Line, Rectangle
    from shapely.affinity import rotate
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    dark, clear = [], []
    for o in GerberFile.open(path).objects:
        for p in o.to_primitives(unit="mm"):
            g = None
            if isinstance(p, Line):
                g = LineString([(p.x1, p.y1), (p.x2, p.y2)]).buffer(p.width / 2, 32) if (p.x1, p.y1) != (p.x2, p.y2) else Point(p.x1, p.y1).buffer(p.width / 2, 32)
            elif isinstance(p, Circle):
                g = Point(p.x, p.y).buffer(p.r, 64)
            elif isinstance(p, Rectangle):
                g = box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
                g = rotate(g, p.rotation, origin=(p.x, p.y), use_radians=True) if p.rotation else g
            else:
                if isinstance(p, Arc):
                    p = p.to_arc_poly()
                if isinstance(p, ArcPoly):
                    pts = [tuple(q) for q in p.outline]
                    g = Polygon(pts).buffer(0) if len(pts) >= 3 else None
            if g is not None:
                (dark if getattr(p, "polarity_dark", True) else clear).append(g)
    u = unary_union(dark)
    return u.difference(unary_union(clear)) if clear else u
