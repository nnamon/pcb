"""`pcb sync`'s pin check after review 18's closures 1 and 2: the pin number read from the number a symbol shows,
pcb.toml pin maps applied pin by pin, and the new canonical names. Real swaps must be refused; correct schematics
should pass.

Usage: python3 pins19.py workdir
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r19lib import FX4, add, eda, emit, export_netlist, fresh, pcb, project, slim, smd, use_netlist  # noqa: E402

work = sys.argv[1]
fresh(work)


def fixture(name):
    d = os.path.join(work, name)
    shutil.copytree(FX4, d, ignore=shutil.ignore_patterns("make_fixture.py"))
    return d


# 0. the designer's edit in regressions/r18/pins18.py removes [parts.C5446] pins only if present. The fixture must have no
# C5446 table at all, or the probe would run with an override in place
t = open(os.path.join(FX4, "pcb.toml")).read()
emit("fixture_has_no_c5446_override", c5446_table="[parts.C5446]" in t, any_pins_key=bool(re.search(r"^\s*pins\s*=", t, re.M)))

# 1. the fixture's schematic (numbered as the Torex datasheet: 1 VSS, 2 VOUT, 3 VIN) syncs with no override
d = fixture("datasheet")
emit("datasheet_numbered", sync=slim(pcb("sync", "--project", d, "--work", os.path.join(d, "w"))))

# 2. U3 renumbered as the spice field would (VBUS on pad 2, V3V3 on pad 3), names following: refused
P = '(ref "U3")\n\t\t\t\t(pin "{}")\n\t\t\t\t(pinfunction "{}")'


def spice_numbered(d, names=("Vin", "Vout")):
    net = open(export_netlist(d)).read()
    vin = re.search(r'\(pin "3"\)\s*\(pinfunction "([^"]*)"\)', net[net.index('(ref "U3")\n\t\t\t\t(pin "3")') - 10:])[1]
    vout = re.search(r'\(pin "2"\)\s*\(pinfunction "([^"]*)"\)', net[net.index('(ref "U3")\n\t\t\t\t(pin "2")') - 10:])[1]
    net = net.replace(P.format(3, vin), P.format("@2", names[0])).replace(P.format(2, vout), P.format(3, names[1])).replace('(pin "@2")', '(pin "2")')
    use_netlist(d, net)
    return vin, vout


d = fixture("spice_numbered")
names = spice_numbered(d)
emit("spice_numbered", fixture_names=names, sync=slim(pcb("sync", "--project", d, "--work", os.path.join(d, "w"))))

# 3. a partial pcb.toml pin map (pin by pin over JLCPCB's) must not hide the swap on the pins it leaves out
d = fixture("spice_numbered_partial_map")
spice_numbered(d)
add(os.path.join(d, "pcb.toml"), '[parts.C5446]\npins = { "1" = "VSS" }\nsource = "r19"')
emit("partial_map", sync=slim(pcb("sync", "--project", d, "--work", os.path.join(d, "w"))))

# 4. synthetic parts: pin 1 and pin 2 of one part, named (a, b) in JLCPCB's symbol; the schematic names them
# (b, a) on pins 1 and 2 (a swap: must be refused), or (a2, b2) (another spelling of the same pins: should pass)
PADS = [smd("1", 4000, 3000), smd("2", 4010, 3000)]


N = [0]


def two_pin(name, jlc_names, sch_names, shown=("1", "2"), spice=("1", "2")):
    N[0] += 1
    name = f"{name}{N[0]}"
    code = f"C9{N[0]:06d}"
    comp = eda(PADS, [(spice[0], shown[0], jlc_names[0]), (spice[1], shown[1], jlc_names[1])])
    filler = eda(PADS, [("1", "1", "1"), ("2", "2", "2")])
    d = project(os.path.join(work, name), [("U1", "x", "", code), ("R1", "r", "", "C11"), ("R2", "r", "", "C11")],
                {"N1": [("U1", "1", sch_names[0]), ("R1", "1", "")], "N2": [("U1", "2", sch_names[1]), ("R2", "1", "")]},
                {code: comp, "C11": filler})
    r = pcb("sync", "--project", d, "--work", os.path.join(d, "w"))
    return {"outcome": r["outcome"], "code": r["code"], "msg": r["msg"][:200], "pins_checked": r["data"].get("pins_checked"), "contract": r["contract"]}


# (JLCPCB's name for pin 1, for pin 2, the schematic's name for pin 1, for pin 2). EasyEDA separates fields with
# '~', so JLCPCB-side active-low marks are '#'; the schematic side uses KiCad's spellings
SWAPS = [("D+", "D-", "D-", "D+"), ("IN+", "IN-", "IN-", "IN+"), ("Q", "Q#", "~{Q}", "Q"), ("CS", "CS#", "~{CS}", "CS"),
         ("VREF+", "VREF-", "VREF-", "VREF+"), ("WR#", "WR", "WR", "~{WR}"), ("V+", "V-", "V-", "V+"), ("+IN", "-IN", "-IN", "+IN"),
         ("RESET", "RESET#", "/RESET", "RESET"), ("OE", "OE#", "!OE", "OE"), ("D+", "D-", "D\u2212", "D+"), ("TX+", "TX-", "TX-", "TX+"),
         ("R/W#", "R#/W", "~{R}/W", "R/~{W}"),
         # pre-existing equalities: a synonym, and a number that tells repeated pins apart
         ("GND", "VSS", "VSS", "GND"), ("OUT", "OUT1", "OUT1", "OUT")]
for ja, jb, sa, sb in SWAPS:
    emit(f"swap {ja} {jb} as {sa} {sb}", **two_pin("swap", (ja, jb), (sa, sb)))

# correct schematics, other spellings of the same pins
SAME = [(("CS#", "CLK"), ("~{CS}", "CLK")), (("CS#", "CLK"), ("/CS", "CLK")), (("CS#", "CLK"), ("nCS", "CLK")),
        (("CS#", "CLK"), ("CS_N", "CLK")), (("IN-", "IN+"), ("-IN", "+IN")), (("IN-", "IN+"), ("-", "+")),
        (("D-", "D+"), ("D\u2212", "D+")), (("VDD-IO", "GND"), ("VDDIO", "GND")), (("DM", "DP"), ("D-", "D+")),
        (("WP#(IO2)", "CLK"), ("WP(IO2)", "CLK")), (("RESET#", "CLK"), ("RESET_B", "CLK")), (("DVDD1", "GND"), ("DVDD", "GND"))]
for jl, sc in SAME:
    emit(f"same {jl[0]} as {sc[0]}", **two_pin("same", jl, sc))

# 5. the shown number decides, the spice number is ignored: a symbol whose shown numbers are 1 and 2 and spice
# numbers 2 and 1. A schematic matching the shown numbers passes; one matching the spice numbers is refused
emit("shown_vs_spice_shown_order", **two_pin("svs_shown", ("VIN", "VOUT"), ("VIN", "VOUT"), shown=("1", "2"), spice=("2", "1")))
emit("shown_vs_spice_spice_order", **two_pin("svs_spice", ("VIN", "VOUT"), ("VOUT", "VIN"), shown=("1", "2"), spice=("2", "1")))
# a blank shown number falls back to the spice number
emit("blank_shown_falls_back", **two_pin("blank_shown", ("VIN", "VOUT"), ("VOUT", "VIN"), shown=("", ""), spice=("2", "1")))
