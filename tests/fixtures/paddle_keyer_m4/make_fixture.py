"""Builds the paddle_keyer_m4 fixture's inputs once, from paddle-keyer v1.0.0's own records. Kept for provenance;
the suite reads the files it wrote, never this script.

Writes:
- schematic/paddle-keyer.kicad_sch: a KiCad schematic of the circuit in paddle-keyer/source/netlist.csv (one
  symbol per part with the netlist's pin names, a global label on every connected pin, so nets keep their
  names without a sheet path), with each part's LCSC code from
  the order's BOM. tscircuit's own KiCad export (paddle-keyer/source/kicad/) loses most connections (14 of 45 nets),
  so it is not used. J1's pads are numbered as JLCPCB's footprint numbers them (A5 for CC1 and so on); tscircuit
  had renumbered them 13 to 26.
- outline.json: the board outline from the v1.0.0 circuit JSON, in the board's centred frame (mm, y up).
- place.toml: a [[place]] entry per part (pasted into pcb.toml): the order's CPL for the assembled parts (JLCPCB's footprint origin and
  rotation, the frame pcb place uses), the circuit JSON for the bottom-side test pads.

Usage: python3 make_fixture.py REPO_ROOT
"""
import csv
import json
import os
import sys
import uuid

repo = os.path.abspath(sys.argv[1])
here = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(repo, "paddle-keyer")
NS = uuid.UUID("6a1f0c52-8d7e-4c55-9b0e-2f7f3d0c9a11")


def uid(*k):
    return str(uuid.uuid5(NS, "/".join(map(str, k))))


bom = {}
for r in csv.DictReader(open(os.path.join(src, "order", "paddle-keyer_v1.0.0_BOM.csv"))):
    for d in r["Designator"].split(","):
        bom[d.strip()] = (r["LCSC Part #"], r["Comment"])
J1 = {"13": "13", "14": "14", "15": "A1B12", "16": "A4B9", "17": "B8", "18": "A5", "19": "B7", "20": "A6", "21": "A7",
      "22": "B6", "23": "A8", "24": "B5", "25": "B4A9", "26": "B1A12"}
# netlist.csv has tscircuit's names, with '#' turned to '_'; the flash's active-low pins are named as its datasheet does
NAMES = {("U2", "3"): "WP#(IO2)", ("U2", "7"): "HOLD# or RESET#(IO3)"}
parts = {}
for r in csv.DictReader(open(os.path.join(src, "source", "netlist.csv"))):
    if not r["pad"]:
        continue  # tscircuit's internal joins of J1's shell pads, which JLCPCB's footprint numbers alike
    pad = J1[r["pad"]] if r["ref"] == "J1" else r["pad"]
    net = None if r["net"] == "(not connected)" else r["net"]
    parts.setdefault(r["ref"], {"part": r["part"], "pins": {}})["pins"][pad] = (NAMES.get((r["ref"], pad), r["pin"]), net)

TP_FP = {"TP_FISH": "pk:TestPad_D1.0mm"}


def esc(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def key(ref):
    i = next((k for k, c in enumerate(ref) if c.isdigit()), len(ref))
    return (ref[:i], int(ref[i:] or 0), ref)


root = uid("root")
lib, inst, labels = [], [], []
refs = sorted(parts, key=key)
for k, ref in enumerate(refs):
    p = parts[ref]
    pins = sorted(p["pins"].items(), key=lambda kv: (len(kv[0]), kv[0]))
    name = f"pk:{ref}"
    h = 2.54 * (len(pins) + 1)
    body = [f'    (symbol {esc(name)} (pin_names (offset 0.5)) (exclude_from_sim no) (in_bom yes) (on_board yes)',
            f'      (property "Reference" {esc(ref.rstrip("0123456789") or "U")} (at 0 2.54 0) (effects (font (size 1.27 1.27))))',
            f'      (property "Value" {esc(p["part"])} (at 0 5.08 0) (effects (font (size 1.27 1.27))))',
            f'      (symbol {esc(ref + "_0_1")} (rectangle (start 0 0) (end 12.7 {-h:.2f}) (stroke (width 0.254) (type default)) (fill (type background))))',
            f'      (symbol {esc(ref + "_1_1")}']
    for i, (num, (pin, _)) in enumerate(pins):
        y = -2.54 * (i + 1)
        body.append(f'        (pin passive line (at -2.54 {y:.2f} 0) (length 2.54) (name {esc(pin)} (effects (font (size 1.27 1.27)))) (number {esc(num)} (effects (font (size 1.27 1.27)))))')
    body.append("      )\n    )")
    lib.append("\n".join(body))
    # parts in a grid of columns, each symbol's pins down its left side
    col, row = k % 8, k // 8
    x, y = 25.4 + col * 45.72, 25.4 + row * 165.1
    lcsc, comment = bom.get(ref, ("", ""))
    value = comment or p["part"]
    fp = f"pcb:{lcsc}" if lcsc else TP_FP.get(ref, "pk:TestPad_2.8x1.2mm")
    props = [f'    (property "Reference" {esc(ref)} (at {x + 6:.2f} {y - 2.54:.2f} 0) (effects (font (size 1.27 1.27))))',
             f'    (property "Value" {esc(value)} (at {x + 6:.2f} {y - 5.08:.2f} 0) (effects (font (size 1.27 1.27))))',
             f'    (property "Footprint" {esc(fp)} (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) (hide yes)))']
    if lcsc:
        props.append(f'    (property "LCSC" {esc(lcsc)} (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    pin_uuids = "\n".join(f'    (pin {esc(num)} (uuid {uid(ref, "pin", num)}))' for num, _ in pins)
    inst.append(f'  (symbol (lib_id {esc(name)}) (at {x:.2f} {y:.2f} 0) (unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
                f'    (uuid {uid(ref)})\n' + "\n".join(props) + "\n" + pin_uuids + "\n"
                f'    (instances (project "paddle-keyer" (path "/{root}" (reference {esc(ref)}) (unit 1))))\n  )')
    for i, (num, (pin, net)) in enumerate(pins):
        # a pin's end is at the symbol's (at) plus the pin's (at), with the library's y up turned to the sheet's y down
        px, py = x - 2.54, y + 2.54 * (i + 1)
        if net:
            labels.append(f'  (global_label {esc(net)} (shape passive) (at {px:.2f} {py:.2f} 180) (effects (font (size 1.27 1.27)) (justify right)) (uuid {uid(ref, num, "label")}))')
        else:
            labels.append(f'  (no_connect (at {px:.2f} {py:.2f}) (uuid {uid(ref, num, "nc")}))')

os.makedirs(os.path.join(here, "schematic"), exist_ok=True)
with open(os.path.join(here, "schematic", "paddle-keyer.kicad_sch"), "w") as f:
    f.write(f'(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") (uuid {root}) (paper "A0")\n')
    f.write("  (lib_symbols\n" + "\n".join(lib) + "\n  )\n")
    f.write("\n".join(labels) + "\n")
    f.write("\n".join(inst) + "\n")
    f.write(f'  (sheet_instances (path "/" (page "1")))\n)\n')

# outline, centred frame
cj = json.load(open(os.path.join(repo, "tools", "pcb", "tests", "fixtures", "paddle_keyer_v1", "circuit.json")))
board = next(e for e in cj if e["type"] == "pcb_board")
pts = [(p["x"], p["y"]) for p in board["outline"]]
xs, ys = [p[0] for p in pts], [p[1] for p in pts]
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
ring = [[round(x - cx, 6), round(y - cy, 6)] for x, y in pts]
if ring[0] != ring[-1]:
    ring.append(ring[0])
json.dump({"type": "Feature", "properties": {"name": "outline"}, "geometry": {"type": "Polygon", "coordinates": [ring]}},
          open(os.path.join(here, "outline.json"), "w"), indent=1)

# places
rows = []
for r in csv.DictReader(open(os.path.join(src, "order", "paddle-keyer_v1.0.0_CPL.csv"))):
    rows.append((r["Designator"], float(r["Mid X"][:-2]), float(r["Mid Y"][:-2]), float(r["Rotation"]), "top"))
srcc = {e["source_component_id"]: e for e in cj if e["type"] == "source_component"}
for e in cj:
    if e["type"] == "pcb_component" and e.get("layer") == "bottom":
        n = srcc[e["source_component_id"]]["name"]
        rows.append((n, e["center"]["x"] - cx, e["center"]["y"] - cy, float(e.get("rotation", 0)), "bottom"))
with open(os.path.join(here, "place.toml"), "w") as f:
    for ref, x, y, rot, side in sorted(rows, key=lambda r: key(r[0])):
        f.write(f'[[place]]\nref = "{ref}"\nat = [{round(x, 4)}, {round(y, 4)}]\nrot_deg = {rot:g}\nside = "{side}"\n\n')
print(len(refs), "parts;", len(rows), "places")
