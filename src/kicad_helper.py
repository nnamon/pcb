"""KiCad operations `pcb` delegates to KiCad 7's pcbnew module. Embedded in the pcb binary and written to its
work directory at run time; prints one JSON object.

  dsn  board.kicad_pcb out.dsn         Specctra DSN export (locked tracks go out as fixed wiring)
  drc  board.kicad_pcb report.rpt      zones refilled in memory, then DRC report plus a JSON summary by type and position
  fill board.kicad_pcb                 fill every zone and save the board
"""
import json
import re
import sys

import pcbnew


def main():
    cmd, path = sys.argv[1], sys.argv[2]
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
        print(json.dumps({"ok": bool(ok), "items": items}))
    elif cmd == "fill":
        # connectivity first: the filler uses it to find and remove unconnected islands
        b.BuildConnectivity()
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        b.Save(path)
        print(json.dumps({"ok": True, "zones": len(b.Zones())}))
    else:
        raise SystemExit(f"unknown command {cmd}")


main()
