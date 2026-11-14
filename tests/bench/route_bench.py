"""Routing benchmark: rip a routed board's copper and let `pcb route` lay it again, then compare with the layout it
had. It measures how good the router's result is; the route cases and `verify_route` test only that it is safe.

Usage: python3 route_bench.py pcb-binary freerouting.jar workdir BOARD [BOARD ...]

Each BOARD is a routed board (the reference). The whole board is the region and every unlocked track and via in it
is ripped (`--rip all`); zone nets are left to their zones, as `pcb route` leaves them. Per board, one JSON row:
  outcome       done, or rejected (the result made DRC worse and nothing was written)
  open          nets the router left open, of `nets` it was given
  vias, mm      vias and track length laid, with the reference's
  seconds       wall time of the run
The table is printed, and the rows are written to workdir/route_bench.json. Freerouting 2.5 does not give the same
result twice, so compare runs by more than one.

Source: the comparison with Copper (14 Nov 2026), which scores its router on real boards with their tracks stripped;
pcb had no measure of routing quality.
"""
import json
import math
import os
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "lib"))
import kisexp  # noqa: E402


def copper(path):
    """(vias, track mm, nets with tracks) of a board, unlocked copper only."""
    root = kisexp.parse(open(path, encoding="utf-8").read())
    segs = [s for s in root.find_all("segment") if not s.find("locked")]
    vias = [v for v in root.find_all("via") if not v.find("locked")]
    length = sum(math.dist(s.nums("start")[:2], s.nums("end")[:2]) for s in segs)
    return len(vias), length, len({s.find("net").arg(1) for s in segs})


def main():
    pcb, jar, work = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3])
    os.makedirs(work, exist_ok=True)
    rows = []
    for board in sys.argv[4:]:
        name = os.path.basename(os.path.dirname(os.path.abspath(board))) + "/" + os.path.basename(board)
        info = json.loads(subprocess.run([pcb, "--json", "info", board], capture_output=True, text=True).stdout)["data"]
        (ox, oy), (w, h) = info["origin"], info["size_mm"]
        region = f"{ox - 1},{oy - 1},{ox + w + 1},{oy + h + 1}"
        tag = name.replace("/", "_").replace(".kicad_pcb", "")
        out = os.path.join(work, tag + ".kicad_pcb")
        for stale in (out, out.replace(".kicad_pcb", ".rejected.kicad_pcb")):
            if os.path.exists(stale):
                os.remove(stale)
        t0 = time.time()
        r = subprocess.run([pcb, "--json", "route", board, "--region", region, "--rip", "all", "--layers", ",".join(info["copper_layers"]),
                            "--freerouting", jar, "--work", os.path.join(work, tag + "_w"), "-o", out], capture_output=True, text=True)
        secs = time.time() - t0
        try:
            d = json.loads(r.stdout)
        except ValueError:
            rows.append({"board": name, "outcome": "no output", "error": r.stderr[-300:]})
            continue
        x = d.get("data") or {}
        ref_vias, ref_mm, ref_nets = copper(board)
        row = {"board": name, "outcome": d["outcome"], "nets": ref_nets, "open": len(x.get("still_open") or []), "open_nets": x.get("still_open") or [],
               "ref_vias": ref_vias, "ref_mm": round(ref_mm, 1), "seconds": round(secs), "regressions": x.get("regressions") or [],
               "dropped_nets": x.get("dropped_nets") or [], "error": (d.get("error") or {}).get("message", "")[:300]}
        written = x.get("written")
        if written and os.path.exists(written):
            row["vias"], mm, _ = copper(written)
            row["mm"] = round(mm, 1)
        rows.append(row)
    print(f'{"board":<44} {"outcome":<9} {"open/nets":>9} {"vias (ref)":>12} {"mm (ref)":>16} {"s":>5}')
    for q in rows:
        print(f'{q["board"]:<44} {q["outcome"]:<9} {str(q.get("open", "")) + "/" + str(q.get("nets", "")):>9} '
              f'{str(q.get("vias", "-")) + " (" + str(q.get("ref_vias", "")) + ")":>12} {str(q.get("mm", "-")) + " (" + str(q.get("ref_mm", "")) + ")":>16} {q.get("seconds", ""):>5}')
    json.dump(rows, open(os.path.join(work, "route_bench.json"), "w"), indent=1)


main()
