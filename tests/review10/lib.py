"""Shared helpers for review 10 probes: board building with pcbnew, running pcb, checking fills."""
import json
import os
import re
import subprocess
import sys

import pcbnew

PCB = os.environ.get("PCB_BIN", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "target", "release", "pcb"))
mm = pcbnew.FromMM


class B:
    def __init__(self, w=80, h=50, nets=("GND", "VCC", "N", "S")):
        # NewBoard writes a project beside the name it is given: keep it out of the working folder (review 11, N9)
        import tempfile
        self.b = pcbnew.NewBoard(os.path.join(tempfile.mkdtemp(prefix="pcb_r10_"), "x.kicad_pcb"))
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
        ds = self.b.GetDesignSettings()
        nc = ds.m_NetSettings.GetDefaultNetclass()
        nc.SetTrackWidth(mm(0.2))
        nc.SetClearance(mm(0.2))

    def fp(self, ref, x, y, net, sz=1.0, tht=False, extra_pads=()):
        b = self.b
        f = pcbnew.FOOTPRINT(b)
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
        b.Add(f)
        return f

    def trk(self, x0, y0, x1, y1, net, w=0.2, layer=pcbnew.F_Cu):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
        t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        t.SetWidth(mm(w))
        t.SetLayer(layer)
        t.SetNet(self.nets[net])
        self.b.Add(t)

    def via(self, x, y, net):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(0.6))
        v.SetDrill(mm(0.3))
        v.SetNet(self.nets[net])
        self.b.Add(v)

    def zone(self, net, layers, polys, keepout=False, parent=None, clearance=0.3, priority=0, islands=0, minw=0.25):
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
        for rect in polys:
            o.NewOutline()
            x0, y0, x1, y1 = rect
            for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
                o.Append(mm(x), mm(y))
        z.SetLocalClearance(mm(clearance))
        z.SetAssignedPriority(priority)
        z.SetIslandRemovalMode(islands)
        z.SetMinThickness(mm(minw))
        (parent or self.b).Add(z)
        return z

    def save(self, path, fill=False):
        if fill:
            zs = list(self.b.Zones())
            for f in self.b.GetFootprints():
                zs += list(f.Zones())
            self.b.BuildConnectivity()
            pcbnew.ZONE_FILLER(self.b).Fill(zs)
        pcbnew.SaveBoard(path, self.b)
        return path


def blocks(t, head):
    """(start, end) of every top-level-or-nested block starting with '(head'."""
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


def strip_zone_uuids(path):
    t = open(path).read()
    out, i = [], 0
    for s, e in blocks(t, "zone"):
        if s < i:
            continue
        out.append(t[i:s])
        out.append(re.sub(r"\n[ \t]*\(uuid \"[^\"]*\"\)", "", t[s:e]))
        i = e
    out.append(t[i:])
    open(path, "w").write("".join(out))


def edit(board, ops, out, work):
    opsf = out + ".ops.json"
    json.dump(ops, open(opsf, "w"))
    r = subprocess.run([PCB, "--json", "edit", board, "--ops", opsf, "--work", work, "-o", out], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        d = {"outcome": "nojson", "stdout": r.stdout, "stderr": r.stderr}
    d["_exit"] = r.returncode
    return d


def fill_check(path):
    """Per zone in file order (board, then each footprint): fill area per layer as on file vs pcbnew's refill.
    Returns list of mismatches."""
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
            r.append((owner, z.GetNetname(), z.GetLocalClearance().value_or(0) if hasattr(z.GetLocalClearance(), "value_or") else None, per))
        return r
    got = areas()
    bd.BuildConnectivity()
    pcbnew.ZONE_FILLER(bd).Fill([z for _, z in zs])
    want = areas()
    return [(g, w) for g, w in zip(got, want) if g != w]
