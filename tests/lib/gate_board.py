"""Boards built with pcbnew for the write gate's zone pairing and markers, the join rule on fills, and diff (reviews 8
and 10 to 12, adapted from the review 10 reviewer's library). 80 x 50 mm, 2 layers, nets GND, VCC, N, S, default
netclass 0.2 mm track and clearance; S pads S1 (5,45) and S2 (30,45) unrouted on most boards, so the usual edit is
an S track (5,45)-(30,45).

Usage:
  python3 gate_board.py VARIANT OUT      build one board (variants: VARIANTS below)
  python3 gate_board.py fills BOARD      JSON list of zones whose fill on file differs from pcbnew's refill
  python3 gate_board.py fpinfo BOARD REF [X Y]   JSON of the footprint's pads, graphics and zones, moved by pcbnew
                                                 to X,Y first when given
  python3 gate_board.py resave A B       load A with pcbnew and save it as B
The text helpers (blocks, no_fills, zone_uuids) import without pcbnew.
"""
import json
import os
import re
import sys
import tempfile


def blocks(t, head):
    """(start, end) of every block starting with '(head', nested ones included."""
    out = []
    for m in re.finditer(r"\(" + head + r"\b", t):
        depth, j = 0, m.start()
        while True:
            c = t[j]
            if c == '"':
                j = t.index('"', j + 1)
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((m.start(), j + 1))
    return out


def no_fills(t):
    """The text without filled_polygon blocks, blank lines, or a zone's filled flag (the gate's fill state)."""
    out, i = [], 0
    for s, e in blocks(t, "filled_polygon"):
        if s < i:
            continue
        out.append(t[i:s])
        i = e
    out.append(t[i:])
    return re.sub(r"\(fill yes(?=\s)", "(fill", re.sub(r"\n[ \t]*\n", "\n", "".join(out)))


def zone_uuids(t):
    r = []
    for s, e in blocks(t, "zone"):
        m = re.search(r'\(uuid "([^"]*)"\)', t[s:e])
        r.append(m.group(1) if m else None)
    return r


def strip_zone_uuids(t):
    out, i = [], 0
    for s, e in blocks(t, "zone"):
        if s < i:
            continue
        out.append(t[i:s])
        out.append(re.sub(r"\n[ \t]*\(uuid \"[^\"]*\"\)", "", t[s:e]))
        i = e
    out.append(t[i:])
    return "".join(out)


def set_uuid(t, head, idx, new):
    """Give the idx-th block starting with '(head' the uuid `new` (its own first uuid)."""
    s, e = blocks(t, head)[idx]
    return t[:s] + re.sub(r'\(uuid "[^"]*"\)', f'(uuid "{new}")', t[s:e], count=1) + t[e:]


M = lambda i: f"00000000-0000-4000-8000-{i:012}"  # the gate's marker uuids (review 12)


class B:
    def __init__(self, w=80, h=50, nets=("GND", "VCC", "N", "S")):
        import pcbnew
        self.pcbnew = pcbnew
        mm = pcbnew.FromMM
        # NewBoard writes a project beside the name it is given: keep it out of the working folder (review 11, N9)
        self.b = pcbnew.NewBoard(os.path.join(tempfile.mkdtemp(prefix="pcb_gate_board_"), "x.kicad_pcb"))
        self.b.SetCopperLayerCount(2)
        self.nets = {}
        for name in nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        pts = [(0, 0), (w, 0), (w, h), (0, h)]
        for i in range(4):
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(pcbnew.VECTOR2I(mm(pts[i][0]), mm(pts[i][1])))
            s.SetEnd(pcbnew.VECTOR2I(mm(pts[(i + 1) % 4][0]), mm(pts[(i + 1) % 4][1])))
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(mm(0.1))
            self.b.Add(s)
        nc = self.b.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
        nc.SetTrackWidth(mm(0.2))
        nc.SetClearance(mm(0.2))

    def fp(self, ref, x, y, net, sz=1.0, tht=False, extra_pads=()):
        pcbnew, mm = self.pcbnew, self.pcbnew.FromMM
        f = pcbnew.FOOTPRINT(self.b)
        f.SetReference(ref)
        f.SetValue("R")
        f.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        for num, (px, py, pnet) in enumerate([(x, y, net)] + list(extra_pads), 1):
            p = pcbnew.PAD(f)
            p.SetNumber(str(num))
            p.SetShape(pcbnew.PAD_SHAPE_RECT)
            if tht:
                p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
                p.SetLayerSet(p.PTHMask())
                p.SetDrillSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
            else:
                p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                p.SetLayerSet(p.SMDMask())
            p.SetSize(pcbnew.VECTOR2I(mm(sz), mm(sz)))
            p.SetPosition(pcbnew.VECTOR2I(mm(px), mm(py)))
            if pnet:
                p.SetNet(self.nets[pnet])
            f.Add(p)
        self.b.Add(f)
        return f

    def trk(self, x0, y0, x1, y1, net, w=0.2, layer=None):
        pcbnew, mm = self.pcbnew, self.pcbnew.FromMM
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
        t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        t.SetWidth(mm(w))
        t.SetLayer(pcbnew.F_Cu if layer is None else layer)
        t.SetNet(self.nets[net])
        self.b.Add(t)

    def via(self, x, y, net):
        pcbnew, mm = self.pcbnew, self.pcbnew.FromMM
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(0.6))
        v.SetDrill(mm(0.3))
        v.SetNet(self.nets[net])
        self.b.Add(v)

    def zone(self, net, layers, polys, keepout=False, parent=None, clearance=0.3, priority=0, islands=0, minw=0.25):
        pcbnew, mm = self.pcbnew, self.pcbnew.FromMM
        z = pcbnew.ZONE(parent or self.b)
        if keepout:
            z.SetIsRuleArea(True)
            z.SetDoNotAllowZoneFills(True)
            z.SetDoNotAllowTracks(False)
            z.SetDoNotAllowVias(False)
        else:
            z.SetNet(self.nets[net])
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(l)
        z.SetLayerSet(ls)
        o = z.Outline()
        if isinstance(polys[0], (int, float)):
            polys = [polys]
        for x0, y0, x1, y1 in polys:
            o.NewOutline()
            for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
                o.Append(mm(x), mm(y))
        z.SetLocalClearance(mm(clearance))
        z.SetAssignedPriority(priority)
        z.SetIslandRemovalMode(islands)
        z.SetMinThickness(mm(minw))
        (parent or self.b).Add(z)
        return z

    def save(self, path, fill=False):
        pcbnew = self.pcbnew
        if fill:
            zs = list(self.b.Zones())
            for f in self.b.GetFootprints():
                zs += list(f.Zones())
            self.b.BuildConnectivity()
            pcbnew.ZONE_FILLER(self.b).Fill(zs)
        pcbnew.SaveBoard(path, self.b)
        return open(path).read()


def S(g):
    g.fp("S1", 5, 45, "S")
    g.fp("S2", 30, 45, "S")


def dup_zones(g, clear=(0.3, 2.0), prio=(0, 1)):
    """Review 10, 1: two GND zones, same net, layer and outline, different clearance and priority; a VCC pad inside."""
    import pcbnew
    S(g)
    g.fp("G1", 10, 10, "GND", tht=True)
    g.fp("V1", 20, 10, "VCC", tht=True)
    g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=clear[0], priority=prio[0])
    g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20), clearance=clear[1], priority=prio[1])


def r12_base(g, fz=False):
    """Review 12's board: review 10's duplicate pair, a VCC zone on B.Cu, a rule area, and with fz a GND zone in FZ."""
    import pcbnew
    dup_zones(g)
    g.zone("VCC", [pcbnew.B_Cu], (2, 2, 38, 20), clearance=0.5)
    g.zone(None, [pcbnew.F_Cu], (50, 5, 70, 20), keepout=True)
    if fz:
        f = g.fp("FZ", 60, 30, "GND", tht=True, extra_pads=[(63, 30, "VCC")])
        g.zone("GND", [pcbnew.B_Cu], (52, 24, 68, 36), parent=f, clearance=0.3)


def build(variant, out):
    import pcbnew
    g = B()
    fill = True
    post = []  # text changes applied after saving, in order
    if variant in ("dup_no_uuid", "dup_uuid", "dup_unfilled", "dup_handtext"):
        dup_zones(g)
        fill = variant != "dup_unfilled"
        if variant != "dup_uuid":
            post.append(strip_zone_uuids)
        if variant == "dup_handtext":
            post.append(lambda t: t.replace("(hatch edge 0.5)", "(hatch edge 0.5)\n\t\t(filled_areas_thickness no)"))
    elif variant == "second_poly_no_uuid":
        S(g)
        g.fp("G1", 10, 10, "GND", tht=True)
        g.fp("G2", 50, 10, "GND", tht=True)
        g.zone("GND", [pcbnew.F_Cu], [(2, 2, 38, 20)])
        g.zone("GND", [pcbnew.F_Cu], [(2, 2, 38, 20), (42, 2, 78, 20)])
        post.append(strip_zone_uuids)
    elif variant in ("same_ref_no_uuid", "same_ref_dup_zone_uuid"):
        S(g)
        for x in (15, 55):
            f = g.fp("FZ", x, 25, "GND", tht=True, extra_pads=[(x + 3, 25, "VCC")])
            g.zone("GND", [pcbnew.B_Cu], (x - 8, 18, x + 8, 32), parent=f, clearance=0.3 if x == 15 else 1.0)
        if variant == "same_ref_no_uuid":
            post.append(strip_zone_uuids)
        else:
            def same_uuid(t):
                us = zone_uuids(t)
                return t.replace(us[1], us[0]) if len(us) >= 2 else t
            post.append(same_uuid)
    elif variant == "top_dup_uuid":
        S(g)
        g.fp("G1", 10, 10, "GND", tht=True)
        g.fp("G2", 50, 10, "GND", tht=True)
        g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
        g.zone("GND", [pcbnew.F_Cu], (42, 2, 78, 20))
        post.append(lambda t: t.replace(zone_uuids(t)[1], zone_uuids(t)[0]))
    elif variant == "move_fz":
        S(g)
        f = g.fp("FZ1", 20, 25, "GND", tht=True)
        g.zone("GND", [pcbnew.B_Cu], (12, 18, 28, 32), parent=f)
        g.zone(None, [pcbnew.F_Cu], (13, 19, 16, 22), keepout=True, parent=f)
        post.append(strip_zone_uuids)
    elif variant == "keepouts_no_uuid":
        S(g)
        g.fp("G1", 10, 10, "GND", tht=True)
        g.zone(None, [pcbnew.F_Cu], (25, 5, 30, 15), keepout=True)
        g.zone(None, [pcbnew.F_Cu], (25, 5, 30, 15), keepout=True)
        g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
        post.append(strip_zone_uuids)
    elif variant == "repeated_point_no_uuid":
        S(g)
        g.fp("G1", 10, 10, "GND", tht=True)
        g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
        post += [lambda t: t.replace("(xy 38 2)", "(xy 38 2) (xy 38 2)", 1), strip_zone_uuids]
    elif variant == "layers_reversed_no_uuid":
        S(g)
        g.fp("G1", 10, 10, "GND", tht=True)
        g.zone("GND", [pcbnew.F_Cu, pcbnew.B_Cu], (2, 2, 38, 20))
        post += [strip_zone_uuids, lambda t: t.replace('(layers "F.Cu" "B.Cu")', '(layers "B.Cu" "F.Cu")')]
    elif variant == "fpzone_islands":
        S(g)
        f = g.fp("FZ1", 20, 25, "GND", tht=True)
        g.zone("GND", [pcbnew.B_Cu], (12, 18, 28, 32), parent=f, islands=1)
    elif variant.startswith("join_"):
        # review 10 join probes: a GND F.Cu zone (10,10)-(40,30), never filled unless stated; GND pad G1 far away
        kind = variant[5:]
        g.fp("G1", 70, 45, "GND", tht=True)
        g.fp("S1", 5, 45, "S")
        fill = False
        if kind == "fpzone":
            f = g.fp("FZ1", 75, 5, "GND", tht=True)
            g.zone("GND", [pcbnew.F_Cu], (10, 10, 40, 30), parent=f)
        elif kind != "nozone":
            g.zone("GND", [pcbnew.F_Cu], (10, 10, 40, 30), islands=1 if kind == "islands" else 0)
        if kind == "stale":
            # a fill on file that pcbnew would not make now: the whole outline filled
            def stale(t):
                s, e = blocks(t, "zone")[0]
                fp_ = '\t\t(filled_polygon\n\t\t\t(layer "F.Cu")\n\t\t\t(pts\n\t\t\t\t(xy 10.2 10.2) (xy 39.8 10.2) (xy 39.8 29.8) (xy 10.2 29.8)\n\t\t\t)\n\t\t)\n'
                return t[:e - 1] + fp_ + t[e - 1:] if "filled_polygon" not in t[s:e] else t
            post.append(stale)
    elif variant == "stitch":
        # review 10 closures: a GND stitching via and a B.Cu track fed only through a filled B.Cu pour
        g.fp("G1", 10, 10, "GND", tht=True)
        g.fp("G2", 30, 10, "GND")
        g.trk(30, 10, 30, 14, "GND", w=0.3)
        g.via(30, 14, "GND")
        g.via(20, 25, "GND")
        g.trk(25, 30, 35, 30, "GND", w=0.3, layer=pcbnew.B_Cu)
        g.zone("GND", [pcbnew.B_Cu], (2, 2, 45, 40))
    elif variant == "same_ref_same_pos":
        S(g)
        for c in (0.3, 1.5):
            f = g.fp("FZ", 20, 25, "GND", tht=True, extra_pads=[(23, 25, "VCC")])
            g.zone("GND", [pcbnew.B_Cu], (12, 18, 28, 32), parent=f, clearance=c)
        post.append(strip_zone_uuids)
    elif variant == "two_fz_no_uuid":
        # FZ1 at (15,25) and FZ2 at (55,25) turned 90 degrees, each with a GND zone, zone uuids stripped (review 11, G5)
        S(g)
        f = g.fp("FZ1", 15, 25, "GND", tht=True, extra_pads=[(18, 25, "VCC")])
        g.zone("GND", [pcbnew.B_Cu], (7, 18, 23, 32), parent=f, clearance=0.3)
        f = g.fp("FZ2", 55, 25, "GND", tht=True, extra_pads=[(58, 25, "VCC")])
        g.zone("GND", [pcbnew.B_Cu], (47, 18, 63, 32), parent=f, clearance=1.0)
        f.SetOrientationDegrees(90)
        post.append(strip_zone_uuids)
    elif variant.startswith("r12_"):
        kind = variant[4:]
        fz = kind in ("dupuuid", "fpmove", "zone_has_marker", "pasted_fp")
        r12_base(g, fz=fz)
        fill = kind != "collide_unfilled"
        if kind == "collide":
            post.append(lambda t: set_uuid(set_uuid(set_uuid(set_uuid(t, "footprint", 0, M(0)), "gr_line", 0, M(1)), "gr_line", 1, M(2)), "gr_line", 2, M(3)))
        elif kind == "collide_unfilled":
            def collide(t):
                t = strip_zone_uuids(t)
                for i in range(4):
                    t = set_uuid(t, "gr_line", i, M(i))
                return t
            post.append(collide)
        elif kind == "dupuuid":
            def one_uuid(t):
                for i in range(len(blocks(t, "zone"))):
                    t = set_uuid(t, "zone", i, "abcdefab-1111-4222-8333-444455556666")
                return t
            post.append(one_uuid)
        elif kind == "group":
            post.append(lambda t: t.rstrip()[:-1] + '\t(group "" (uuid "99999999-1111-4222-8333-444455556666") (members ' + " ".join(f'"{u}"' for u in zone_uuids(t)[:3]) + "))\n)\n")
        elif kind == "zone_has_marker":
            def marker(t):
                n = len(blocks(t, "zone"))
                return set_uuid(set_uuid(t, "zone", n - 1, M(0)), "zone", 0, M(n - 1))
            post.append(marker)
        elif kind == "emptyzone":
            post.append(lambda t: t.rstrip()[:-1] + '\t(zone (net "GND") (layer "F.Cu") (hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)))\n)\n')
        elif kind == "pasted_fp":
            def paste(t):
                s, e = [b for b in blocks(t, "footprint") if '"FZ"' in t[b[0]:b[1]]][0]
                return t[:e] + "\n\t" + re.sub(r"\(clearance 0\.3\)", "(clearance 1.5)", t[s:e], count=1) + t[e:]
            post.append(paste)
        elif kind not in ("fpmove",):
            raise SystemExit(f"unknown variant {variant}")
    elif variant == "diff10":
        # review 10 diff base: a GND F.Cu zone and a footprint GND zone on B.Cu, never filled
        g.fp("G1", 10, 10, "GND", tht=True)
        S(g)
        g.trk(5, 45, 30, 45, "S")
        g.zone("GND", [pcbnew.F_Cu], (2, 2, 38, 20))
        f = g.fp("FZ1", 60, 28, "GND", tht=True)
        g.zone("GND", [pcbnew.B_Cu], (56, 24, 66, 32), parent=f)
        fill = False
    elif variant in ("diff11", "diff12"):
        # reviews 11 and 12 diff base: U1 (GND, VCC pads) in a never-filled B.Cu GND zone, an S track
        g.fp("U1", 20, 20, "GND", tht=True, extra_pads=[(23, 20, "VCC")])
        if variant == "diff11":
            S(g)
        g.trk(5, 45, 30, 45, "S")
        g.zone("GND", [pcbnew.B_Cu], (2, 2, 38, 38))
        fill = False
    elif variant == "fp_rotated":
        # review 8: R5 at (30,20), turned 30 degrees and flipped, two pads, a silkscreen line and a rule area of its own
        return build_fp_rotated(out)
    else:
        raise SystemExit(f"unknown variant {variant}")
    t = g.save(out, fill=fill)
    for p in post:
        t = p(t)
    open(out, "w").write(t)


def diff11_mutate(name, out):
    """Review 11's diff misses: the diff11 board with one change made through pcbnew."""
    import pcbnew
    mm = pcbnew.FromMM
    g = B()
    f = g.fp("U1", 20, 20, "GND", tht=True, extra_pads=[(23, 20, "VCC")])
    S(g)
    g.trk(5, 45, 30, 45, "S")
    g.zone("GND", [pcbnew.B_Cu], (2, 2, 38, 38))
    if name == "footprint_zone_connection_none":
        f.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)
    elif name == "footprint_local_clearance":
        f.SetLocalClearance(mm(1.0))
    elif name == "dimension_on_F_Cu":
        d = pcbnew.PCB_DIM_ALIGNED(g.b)
        d.SetLayer(pcbnew.F_Cu)
        d.SetStart(pcbnew.VECTOR2I(mm(5), mm(30)))
        d.SetEnd(pcbnew.VECTOR2I(mm(30), mm(30)))
        g.b.Add(d)
    elif name == "target_on_F_Cu":
        t = pcbnew.PCB_TARGET(g.b)
        t.SetLayer(pcbnew.F_Cu)
        t.SetPosition(pcbnew.VECTOR2I(mm(10), mm(30)))
        t.SetSize(mm(5))
        t.SetWidth(mm(0.2))
        g.b.Add(t)
    elif name == "reference_text_on_F_Cu":
        f.Reference().SetLayer(pcbnew.F_Cu)
    elif name == "gr_rect_on_F_Cu":
        s = pcbnew.PCB_SHAPE(g.b)
        s.SetShape(pcbnew.SHAPE_T_RECT)
        s.SetStart(pcbnew.VECTOR2I(mm(5), mm(30)))
        s.SetEnd(pcbnew.VECTOR2I(mm(8), mm(33)))
        s.SetLayer(pcbnew.F_Cu)
        s.SetFilled(True)
        g.b.Add(s)
    elif name == "pad_thermal_spoke_angle_90":
        for p in f.Pads():
            if p.GetNumber() == "1":
                p.SetThermalSpokeAngleDegrees(90)
    elif name != "none":
        raise SystemExit(f"unknown change {name}")
    g.save(out)


def build_fp_rotated(out):
    import pcbnew
    mm = pcbnew.FromMM
    b = pcbnew.NewBoard(os.path.join(tempfile.mkdtemp(prefix="pcb_gate_board_"), "x.kicad_pcb"))
    for x0, y0, x1, y1 in [(0, 0, 60, 0), (60, 0, 60, 40), (60, 40, 0, 40), (0, 40, 0, 0)]:
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
        s.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        s.SetLayer(pcbnew.Edge_Cuts)
        b.Add(s)
    net = pcbnew.NETINFO_ITEM(b, "A")
    b.Add(net)
    f = pcbnew.FOOTPRINT(b)
    f.SetReference("R5")
    f.SetValue("R")
    b.Add(f)
    for k, x in (("1", -1.0), ("2", 1.5)):
        p = pcbnew.PAD(f)
        p.SetNumber(k)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(p.SMDMask())
        p.SetSize(pcbnew.VECTOR2I(mm(0.8), mm(0.6)))
        f.Add(p)
        p.SetFPRelativePosition(pcbnew.VECTOR2I(mm(x), mm(0.3)))
        p.SetNet(net)
    gr = pcbnew.PCB_SHAPE(f)
    gr.SetShape(pcbnew.SHAPE_T_SEGMENT)
    gr.SetLayer(pcbnew.F_SilkS)
    f.Add(gr)
    gr.SetStart(pcbnew.VECTOR2I(mm(-2), mm(-1)))
    gr.SetEnd(pcbnew.VECTOR2I(mm(2), mm(-1)))
    z = pcbnew.ZONE(f)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True)
    z.SetLayer(pcbnew.F_Cu)
    o = z.Outline()
    o.NewOutline()
    for x, y in [(-1, 1), (1, 1), (1, 2), (-1, 2)]:
        o.Append(mm(x), mm(y))
    f.Add(z)
    f.SetPosition(pcbnew.VECTOR2I(mm(30), mm(20)))
    f.SetOrientationDegrees(30)
    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    pcbnew.SaveBoard(out, b)


def fpinfo(path, ref, to=None):
    import pcbnew
    b = pcbnew.LoadBoard(path)
    f = [f for f in b.GetFootprints() if f.GetReference() == ref][0]
    if to:
        f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(to[0])), pcbnew.FromMM(float(to[1]))))
    r = lambda v: [round(pcbnew.ToMM(v.x), 4), round(pcbnew.ToMM(v.y), 4)]
    return {"pos": r(f.GetPosition()), "rot": f.GetOrientationDegrees(), "side": f.GetLayerName(),
            "pads": {p.GetNumber(): r(p.GetPosition()) for p in f.Pads()},
            "graphics": [[r(g.GetStart()), r(g.GetEnd())] for g in f.GraphicalItems() if g.GetClass() == "PCB_SHAPE"],
            "zones": [[r(z.Outline().CVertex(i)) for i in range(z.Outline().TotalVertices())] for z in f.Zones()]}


def fill_check(path):
    """Per zone in file order (board, then each footprint): fill area per layer on file against pcbnew's refill."""
    import pcbnew
    bd = pcbnew.LoadBoard(path)
    zs = [("board", z) for z in bd.Zones()]
    for f in bd.GetFootprints():
        zs += [(f.GetReference() + "@" + str(f.GetPosition().x), z) for z in f.Zones()]

    def areas():
        r = []
        for owner, z in zs:
            per = {}
            for l in z.GetLayerSet().CuStack():
                fp = z.GetFilledPolysList(l)
                per[pcbnew.LayerName(l)] = round(fp.Area() / 1e12, 4) if fp is not None else 0
            lc = z.GetLocalClearance()
            r.append((owner, z.GetNetname(), lc.value_or(0) if hasattr(lc, "value_or") else None, per))
        return r
    got = areas()
    bd.BuildConnectivity()
    pcbnew.ZONE_FILLER(bd).Fill([z for _, z in zs])
    return [(g, w) for g, w in zip(got, areas()) if g != w]


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fills":
        print(json.dumps(fill_check(sys.argv[2]), default=str))
    elif cmd == "fpinfo":
        print(json.dumps(fpinfo(sys.argv[2], sys.argv[3], sys.argv[4:6] or None)))
    elif cmd == "resave":
        import pcbnew
        pcbnew.SaveBoard(sys.argv[3], pcbnew.LoadBoard(sys.argv[2]))
    elif cmd == "diff11":
        diff11_mutate(sys.argv[2], sys.argv[3])
    else:
        build(cmd, sys.argv[2])
