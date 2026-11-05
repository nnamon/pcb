"""Turns of parts matched by shape (review 19, closure 48): `pcb parts` and the release.

- The M4 board after its flow: no `polarity` finding (its two-pad parts match by number).
- D9, JLCPCB's C81598 (1N4148W), on a project footprint numbered A and K: a finding at offset 0 and at 180.
- R9, JLCPCB's C25905 (0402 resistor), on a project footprint numbered A and B: the same finding for a part with
  no polarity; can it be waived?
- Parts with more than two pads matched by shape whose pad centres repeat under a half or quarter turn: an SOIC-8
  with its exposed pad numbered EP (JLCPCB numbers it 9), and a 12-pad QFN-like part, each drawn turned from
  JLCPCB's (the usual KiCad and JLCPCB difference). The shape match cannot tell the turns apart.

Usage: python3 polarity20.py workdir
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r20lib import FX4, U, copy_base, eda, emit, fresh, jlc, netlist, pcb, slim  # noqa: E402

work = sys.argv[1]
fresh(work)


def parts(d, name, refs):
    r = pcb("parts", "--project", d, "--work", os.path.join(work, name + "_p"))
    return {"outcome": r["outcome"], "findings": [f["item"] for f in r["data"].get("findings", [])],
            "solved": {s["reference"]: [s["rotation_offset_deg"], s["by_number"], s["residual_mm"]] for s in r["data"].get("solved", []) if s["reference"] in refs}}


HEAD = ('(footprint "{n}" (version 20260206) (generator "r20") (layer "F.Cu")\n  (attr smd)\n'
        '  (property "Reference" "REF**" (at 0 0 0) (layer "F.SilkS") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
        '  (property "Value" "x" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 0.6 0.6) (thickness 0.1))))\n'
        '  (fp_rect (start -{c} -{c}) (end {c} {c}) (stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))\n')


def modfile(name, pads, court=2.4):
    """pads: [(number, x, y, w, h)] in the footprint's frame (mm, y down)."""
    t = HEAD.format(n=name, c=court)
    for n, x, y, w, h in pads:
        t += f'  (pad "{n}" smd rect (at {x:.4f} {y:.4f}) (size {w:.4f} {h:.4f}) (layers "F.Cu" "F.Paste" "F.Mask"))\n'
    return t + ")\n"


def mkproj(d, comps, nets, eda_parts, mods, place, extra=""):
    fresh(d)
    os.makedirs(os.path.join(d, "parts"))
    os.makedirs(os.path.join(d, "footprints"))
    for code, comp in eda_parts.items():
        json.dump(comp, open(os.path.join(d, "parts", f"{code}.easyeda.json"), "w"))
        json.dump(jlc(code), open(os.path.join(d, "parts", f"{code}.jlc.json"), "w"))
    for n, t in mods.items():
        open(os.path.join(d, "footprints", n + ".kicad_mod"), "w").write(t)
    open(os.path.join(d, "n.net"), "w").write(netlist(comps, nets))
    s = ('schema = 1\n[project]\nname = "r20"\nversion = "0.1.0"\nboard = "board.kicad_pcb"\nlayers = 2\nfab = "jlcpcb-2layer-1.6mm"\n'
         'netlist = "n.net"\n[outline]\nrect_mm = [40, 40]\n[assembly]\nmachine_sides = ["top"]\n')
    for ref, x, y, rot in place:
        s += f'[[place]]\nref = "{ref}"\nat = [{x}, {y}]\nrot_deg = {rot}\nside = "top"\n'
    open(os.path.join(d, "pcb.toml"), "w").write(s + extra)
    sy = pcb("sync", "--project", d, "--work", os.path.join(d, "ws"))
    pl = pcb("place", "--project", d, "--work", os.path.join(d, "wp"))
    return sy, pl


def release(d, name):
    r = pcb("release", "--project", d, "-o", os.path.join(work, name + "_out"), "--work", os.path.join(work, name + "_r"))
    return {"outcome": r["outcome"], "code": r["code"], "msg": r["msg"][:500]}


# 1. the M4 board after its flow: no polarity finding
d = copy_base(work, "m4")
emit("m4_no_polarity", parts=parts(d, "m4", ("D1", "LED1", "R1", "C2")))


def two_pad(code, names, ref, value):
    e = json.load(open(os.path.join(FX4, "parts", f"{code}.easyeda.json")))
    pk = e["result"]["packageDetail"]["dataStr"]
    ox, oy = float(pk["head"]["x"]), float(pk["head"]["y"])
    pads = []
    for s in pk["shape"]:
        f = s.split("~")
        if f[0] == "PAD":
            pads.append((names[f[8]], (float(f[2]) - ox) * U, (float(f[3]) - oy) * U, float(f[4]) * U, float(f[5]) * U))
    return e, pads


# 2. D9 on an A/K footprint, offsets 0 and 180; release refused?
e, pads = two_pad("C81598", {"1": "K", "2": "A"}, "D9", "1N4148W")
for off in (0, 180):
    d = os.path.join(work, f"d9_{off}")
    sy, pl = mkproj(d, [("D9", "1N4148W", "r20:DAK", "C81598"), ("TP1", "tp", "r20:DAK", "")],
                    {"N1": [("D9", "A", "A"), ("TP1", "A", "")], "N2": [("D9", "K", "K"), ("TP1", "K", "")]},
                    {"C81598": e}, {"DAK": modfile("DAK", pads)}, [("D9", 0, 0, 0), ("TP1", 8, 8, 0)],
                    f'[parts.C81598]\nrotation_offset_deg = {off}\nsource = "r20"\n' if off else "")
    emit(f"d9_by_shape_{off}", sync=slim(sy), place=slim(pl), parts=parts(d, f"d9_{off}", ("D9",)), release=release(d, f"d9_{off}"))

# 3. R9, a resistor on an A/B footprint: the same finding; a waiver for it
e, pads = two_pad("C25905", {"1": "A", "2": "B"}, "R9", "5.1k")
for wv in ("", '[[waiver]]\ncheck = "parts"\nitem = "R9 polarity"\nwhy = "a resistor has no polarity"\n'):
    name = "r9_waived" if wv else "r9"
    d = os.path.join(work, name)
    sy, pl = mkproj(d, [("R9", "5.1k", "r20:RAB", "C25905"), ("TP1", "tp", "r20:RAB", "")],
                    {"N1": [("R9", "A", ""), ("TP1", "A", "")], "N2": [("R9", "B", ""), ("TP1", "B", "")]},
                    {"C25905": e}, {"RAB": modfile("RAB", pads)}, [("R9", 0, 0, 0), ("TP1", 8, 8, 0)], wv)
    emit(f"{name}_by_shape", sync=slim(sy), place=slim(pl), parts=parts(d, name, ("R9",)))


# 4. symmetric pad patterns with more than two pads, matched by shape
def turn(x, y, deg):
    """A turn anticlockwise on screen (y down), as KiCad turns a footprint."""
    import math
    a = math.radians(deg)
    return (x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a))


def multi(name, jpads, ep_board, turn_deg, declare):
    """jpads: [(number, x, y, w, h)] in EasyEDA units about the origin (4000, 3000), y down. The project footprint is
    JLCPCB's turned by turn_deg (so the true rotation offset is turn_deg's inverse), its exposed pad renamed ep_board."""
    recs = [f"PAD~RECT~{4000 + x}~{3000 + y}~{w}~{h}~1~~{n}~0~~0~g{n}~0~~Y~0" for n, x, y, w, h in jpads]
    pins = [(n, n, "EP" if n == jpads[-1][0] else f"P{n}") for n, *_ in jpads]
    comp = eda(recs, pins, title=name.upper())
    mp = []
    for n, x, y, w, h in jpads:
        tx, ty = turn(x * U, y * U, turn_deg)
        tw, th = (w * U, h * U) if turn_deg % 180 == 0 else (h * U, w * U)
        mp.append((ep_board if n == jpads[-1][0] else n, tx, ty, tw, th))
    d = os.path.join(work, name)
    # one pad per net, so the unrouted board has no unconnected items and can go through check and release
    nets = {f"N{n}": [("U9", n, f"P{n}")] for n, *_ in jpads[:-1]}
    sy, pl = mkproj(d, [("U9", "x", f"r20:{name.upper()}", "C9300001")], nets,
                    {"C9300001": comp}, {name.upper(): modfile(name.upper(), mp, court=4)}, [("U9", 0, 0, 0)],
                    f'[parts.C9300001]\nrotation_offset_deg = {declare}\nsource = "r20"\n' if declare else "")
    p = parts(d, name, ("U9",))
    res = {"sync": slim(sy), "place": slim(pl), "parts": p, "true_offset": (-turn_deg) % 360, "declared": declare}
    if p["outcome"] == "done":
        c = pcb("check", "--project", d, "--work", os.path.join(d, "wc"))
        res["check"] = {"outcome": c["outcome"], "unwaived": sorted(f"{x['check']} {x['item']}" for x in c["data"].get("findings", []) if not x.get("waived"))}
        res["gate"] = slim(pcb("gate", "pass", "layout", "--project", d, "--work", os.path.join(d, "wg")))
        out = os.path.join(work, name + "_out")
        res["release"] = release(d, name)
        import csv
        import glob
        cpl = glob.glob(os.path.join(out, "*_CPL.csv"))
        res["cpl_U9"] = [r for r in csv.DictReader(open(cpl[0])) if r["Designator"] == "U9"] if cpl else None
    emit(name, **res)


# SOIC-8 with exposed pad: pins 1-4 down the left (pin 1 at the top), 5-8 up the right, EP 9. Units of 0.254 mm
soic = [(str(i + 1), -10.6, -7.5 + 5 * i, 6, 2.4) for i in range(4)] + [(str(8 - i), 10.6, -7.5 + 5 * i, 6, 2.4) for i in range(4)] + [("9", 0, 0, 9, 12)]
multi("soic_ep_turned180", soic, "EP", 180, 0)
multi("soic_ep_turned90_declared0", soic, "EP", 90, 0)
# control: the same footprint not turned
multi("soic_ep_not_turned", soic, "EP", 0, 0)
# QFN-like: 3 pads a side, EP 13
q = []
for i in range(3):
    q.append((str(1 + i), -10, -4 + 4 * i, 4, 1.6))
    q.append((str(4 + i), -4 + 4 * i, 10, 1.6, 4))
    q.append((str(7 + i), 10, 4 - 4 * i, 4, 1.6))
    q.append((str(10 + i), 4 - 4 * i, -10, 1.6, 4))
q.sort(key=lambda p: int(p[0]))
q.append(("13", 0, 0, 10, 10))
multi("qfn_ep_turned90", q, "EP", 90, 0)
