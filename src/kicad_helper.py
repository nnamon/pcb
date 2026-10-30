"""KiCad operations `pcb` delegates to KiCad 7's pcbnew module. Embedded in the pcb binary and written to its
work directory at run time; prints one JSON object.

  dsn  board.kicad_pcb out.dsn         Specctra DSN export (locked tracks go out as fixed wiring)
  drc  board.kicad_pcb report.rpt      zones refilled in memory, then DRC report plus a JSON summary by type and position
  fill board.kicad_pcb                 fill every zone and save the board
  selftest workdir                     KiCad version and the behaviours pcb relies on (pcb doctor)
"""
import json
import re
import sys

import pcbnew


def selftest(work):
    """Each check names a KiCad behaviour pcb depends on; a change after an upgrade shows here first."""
    import os
    res = {"version": pcbnew.Version()}
    # flip convention (review 1, B2): a pad at local (2, 0), footprint at (50, 50), flipped, turned 90 degrees
    b = pcbnew.BOARD()
    f = pcbnew.FOOTPRINT(b)
    p = pcbnew.PAD(f)
    p.SetNumber("1")
    p.SetPos0(pcbnew.VECTOR2I(pcbnew.FromMM(2), 0))
    p.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(2), 0))
    f.Add(p)
    b.Add(f)
    f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50), pcbnew.FromMM(50)))
    f.Flip(f.GetPosition(), False)
    f.SetOrientationDegrees(90)
    q = p.GetPosition()
    res["flip_pad_at"] = [round(pcbnew.ToMM(q.x), 4), round(pcbnew.ToMM(q.y), 4)]
    # a zone given two outlines from Python (spike 3 saw only the first saved)
    z = pcbnew.ZONE(b)
    z.SetLayer(pcbnew.F_Cu)
    o = z.Outline()
    for k in range(2):
        o.NewOutline()
        for x, y in ((0, 0), (1, 0), (1, 1)):
            o.Append(pcbnew.FromMM(x + 3 * k), pcbnew.FromMM(y))
    b.Add(z)
    path = os.path.join(work, "selftest.kicad_pcb")
    b.Save(path)
    b2 = pcbnew.LoadBoard(path)
    res["zone_outlines_after_save"] = max((zz.Outline().OutlineCount() for zz in b2.Zones()), default=0)
    # probe boards for doctor's own DRC and Freerouting runs, each in a fresh process (see kicad.rs)
    for name, short in (("drc_probe", True), ("route_probe", False)):
        pb = pcbnew.BOARD()
        pb.SetCopperLayerCount(2)
        nets = {}
        for n in ("A", "B"):
            ni = pcbnew.NETINFO_ITEM(pb, n)
            pb.Add(ni)
            nets[n] = ni
        for i, (x0, y0, x1, y1) in enumerate(((0, 0, 30, 0), (30, 0, 30, 20), (30, 20, 0, 20), (0, 20, 0, 0))):
            sh = pcbnew.PCB_SHAPE(pb)
            sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
            sh.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
            sh.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
            sh.SetLayer(pcbnew.Edge_Cuts)
            pb.Add(sh)
        for ref, x, y, n in (("P1", 5, 10, "A"), ("P2", 25, 10, "A"), ("P3", 15, 5, "B")):
            fp = pcbnew.FOOTPRINT(pb)
            fp.SetReference(ref)
            fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
            pd = pcbnew.PAD(fp)
            pd.SetNumber("1")
            pd.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pd.SetShape(pcbnew.PAD_SHAPE_RECT)
            pd.SetLayerSet(pd.SMDMask())
            pd.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1), pcbnew.FromMM(1)))
            pd.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
            pd.SetNet(nets[n])
            fp.Add(pd)
            pb.Add(fp)
        if short:
            # a net B track across pad P1 (net A): a short; P1 and P2 unconnected
            t = pcbnew.PCB_TRACK(pb)
            t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(15), pcbnew.FromMM(5)))
            t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(5), pcbnew.FromMM(10)))
            t.SetWidth(pcbnew.FromMM(0.25))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(nets["B"])
            pb.Add(t)
        pb.Save(os.path.join(work, name + ".kicad_pcb"))
    print(json.dumps({"ok": True, **res}))


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == "selftest":
        return selftest(path)
    b = pcbnew.LoadBoard(path)
    if cmd == "dsn":
        ok = pcbnew.ExportSpecctraDSN(b, sys.argv[3])
        print(json.dumps({"ok": bool(ok), "dsn": sys.argv[3]}))
    elif cmd == "drc":
        rpt = sys.argv[3]
        # fills as they would be now, in memory only: a stale fill gives false clearance and connection results
        if len(b.Zones()):
            b.BuildConnectivity()
            pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        ok = pcbnew.WriteDRCReport(b, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
        text = open(rpt).read()
        items = []
        for m in re.finditer(r"^\[(\w+)\]: ([^\n]*)\n((?:    [^\n]*\n)+)", text, re.M):
            body = m.group(3)
            sev = re.search(r"Severity: (\w+)", body)
            locs = [{"x": float(a), "y": float(b_), "item": it.strip()} for a, b_, it in re.findall(r"@\((-?[\d.]+) mm, (-?[\d.]+) mm\): ([^\n]*)", body)]
            items.append({"type": m.group(1), "message": m.group(2), "severity": sev.group(1) if sev else "", "at": locs})
        # the report's own totals must equal what was parsed, or the format has changed (review 5, 4)
        found = sum(int(n) for n in re.findall(r"^\*\* Found (\d+) ", text, re.M))
        if not ok or found != len(items):
            raise SystemExit(f"DRC report not understood: ok={ok}, the report counts {found}, {len(items)} parsed")
        print(json.dumps({"ok": bool(ok), "items": items, "found": found}))
    elif cmd == "fill":
        # connectivity first: the filler uses it to find and remove unconnected islands
        b.BuildConnectivity()
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        b.Save(path)
        print(json.dumps({"ok": True, "zones": len(b.Zones())}))
    else:
        raise SystemExit(f"unknown command {cmd}")


main()
