"""KiCad operations `pcb` delegates to KiCad 10's pcbnew module. Embedded in the pcb binary and written to its
work directory at run time; prints one JSON object.

  dsn  board.kicad_pcb out.dsn         Specctra DSN export (locked tracks go out as fixed wiring)
  drc  board.kicad_pcb report.json     kicad-cli DRC, zones refilled in memory (the file is not saved); items by type and position
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
    f.Add(p)
    p.SetFPRelativePosition(pcbnew.VECTOR2I(pcbnew.FromMM(2), 0))
    b.Add(f)
    f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(50), pcbnew.FromMM(50)))
    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
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
    # the DRC probe's nets have brackets and a space, as bus nets do (review 6, K3); the route probe's are plain
    # the layer probe adds a locked net B wall across F.Cu between P1 and P2, so net A can cross only on B.Cu
    for name, short in (("drc_probe", True), ("route_probe", False), ("layer_probe", False)):
        pb = pcbnew.NewBoard(os.path.join(work, name + ".kicad_pcb"))
        pb.SetCopperLayerCount(2)
        nets = {}
        for n, real in (("A", "D[0]" if short else "A"), ("B", "D[0]{slash} x" if short else "B")):
            ni = pcbnew.NETINFO_ITEM(pb, real)
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
        if name == "layer_probe":
            t = pcbnew.PCB_TRACK(pb)
            t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(0.5)))
            t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(19.5)))
            t.SetWidth(pcbnew.FromMM(0.5))
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(nets["B"])
            t.SetLocked(True)
            pb.Add(t)
        pb.Save(os.path.join(work, name + ".kicad_pcb"))
    # KiCad's DRC listing limits (review 6, K1): 600 tracks of alternating nets, 0.05 mm apart and under the minimum
    # width, give 600 track_width and 599 clearance violations; KiCad lists 199 and 499
    cb = pcbnew.NewBoard(os.path.join(work, "drc_cap_probe.kicad_pcb"))
    cb.SetCopperLayerCount(2)
    cn = []
    for n in ("A", "B"):
        ni = pcbnew.NETINFO_ITEM(cb, n)
        cb.Add(ni)
        cn.append(ni)
    for x0, y0, x1, y1 in ((0, 0, 60, 0), (60, 0, 60, 10), (60, 10, 0, 10), (0, 10, 0, 0)):
        sh = pcbnew.PCB_SHAPE(cb)
        sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
        sh.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
        sh.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
        sh.SetLayer(pcbnew.Edge_Cuts)
        cb.Add(sh)
    for i in range(600):
        t = pcbnew.PCB_TRACK(cb)
        x = pcbnew.FromMM(2 + i * 0.09)
        t.SetStart(pcbnew.VECTOR2I(x, pcbnew.FromMM(4)))
        t.SetEnd(pcbnew.VECTOR2I(x, pcbnew.FromMM(6)))
        t.SetWidth(pcbnew.FromMM(0.04))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(cn[i % 2])
        cb.Add(t)
    cb.GetDesignSettings().m_TrackMinWidth = pcbnew.FromMM(0.1)
    pcbnew.SaveBoard(os.path.join(work, "drc_cap_probe.kicad_pcb"), cb)
    print(json.dumps({"ok": True, **res}))


DRC_SCHEMA = "https://schemas.kicad.org/drc.v1.json"


# KiCad stops listing a violation type at these counts (199; 499 for clearance with --all-track-errors). A type at
# its limit is an incomplete list, and which violations it holds changes from run to run (review 6, K1); pcb doctor
# checks both numbers on a probe board.
REPORT_LIMITS = (199, 499)


# KiCad stores some characters of a net name escaped ("/TX{slash}RX") but shows them plain in DRC text (review 7, C1)
ESCAPES = {"{slash}": "/", "{backslash}": "\\", "{lt}": "<", "{gt}": ">", "{colon}": ":", "{dblquote}": '"',
           "{quote}": "'", "{space}": " ", "{tab}": "\t", "{return}": "\n", "{linefeed}": "\n", "{comma}": ","}


def unescape(name):
    for k, v in ESCAPES.items():
        name = name.replace(k, v)
    return name


def item_net(item, board, names):
    """The net of a DRC item, as the board file names it; "" for none. By the item's uuid in the loaded board when
    KiCad can resolve it (a connected item gives its net, anything else, such as text, none: review 7, C6). Items
    without a stored uuid get a new one on every load, so for those the description is matched against the board's
    net names, unescaped, longest first (review 6, K3)."""
    it = board.ResolveItem(pcbnew.KIID(item.get("uuid", "")), True) if item.get("uuid") else None
    if it is not None:
        try:
            it = it.Cast()
        except TypeError:
            return ""   # a class Cast does not know (a footprint field): not copper on a net
        return it.GetNetname() if hasattr(it, "GetNetname") else ""
    desc = item["description"]
    hits = [n for n in names if f"[{unescape(n)}]" in desc]
    return max(hits, key=lambda n: len(unescape(n))) if hits else ""


def drc(board, out, b):
    """KiCad's DRC through kicad-cli: in KiCad 10, WriteDRCReport asserts outside the KiCad application. The JSON
    schema is checked, and kicad-cli's own totals must equal what was read, or the format has changed (review 5, 4).
    Each item carries its net, matched against the board's net names. Types at KiCad's report limit are returned as
    `truncated`. PCB_KICAD_CLI names another kicad-cli (the adapter cases use it to change the format)."""
    import os
    import subprocess
    cli = os.environ.get("PCB_KICAD_CLI", "kicad-cli")
    r = subprocess.run([cli, "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "--all-track-errors",
                        "--refill-zones", "-o", out, board], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise SystemExit(f"kicad-cli DRC failed (exit {r.returncode}): {r.stderr[-500:]}{r.stdout[-500:]}")
    d = json.load(open(out))
    if d.get("$schema") != DRC_SCHEMA or d.get("coordinate_units") != "mm":
        raise SystemExit(f"DRC report not understood: schema {d.get('$schema')!r}, units {d.get('coordinate_units')!r}")
    names = sorted({str(n) for n in b.GetNetsByName().keys() if str(n)})
    items = []
    for key in ("violations", "unconnected_items"):
        for v in d.get(key) or []:
            if "type" not in v or not isinstance(v.get("items"), list):
                raise SystemExit(f"DRC report not understood: a {key} entry has no type or items")
            locs = [{"x": float(i["pos"]["x"]), "y": float(i["pos"]["y"]), "item": i["description"], "net": item_net(i, b, names)} for i in v["items"]]
            items.append({"type": v["type"], "message": v.get("description", ""), "severity": v.get("severity", ""), "at": locs})
    found = sum(int(n) for n in re.findall(r"^Found (\d+) ", r.stdout, re.M))
    if found != len(items):
        raise SystemExit(f"DRC report not understood: kicad-cli counts {found}, {len(items)} read")
    import collections
    per_type = collections.Counter(it["type"] for it in items)
    truncated = {t: n for t, n in per_type.items() if n in REPORT_LIMITS}
    return {"ok": True, "items": items, "found": found, "truncated": truncated}


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == "selftest":
        return selftest(path)
    b = pcbnew.LoadBoard(path)
    if cmd == "dsn":
        ok = pcbnew.ExportSpecctraDSN(b, sys.argv[3])
        print(json.dumps({"ok": bool(ok), "dsn": sys.argv[3]}))
    elif cmd == "drc":
        print(json.dumps(drc(path, sys.argv[3], b)))
    elif cmd == "fill":
        # connectivity first: the filler uses it to find and remove unconnected islands
        b.BuildConnectivity()
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        b.Save(path)
        print(json.dumps({"ok": True, "zones": len(b.Zones())}))
    else:
        raise SystemExit(f"unknown command {cmd}")


main()
