"""A board of awkward net names, from review 7 (the reviewer's generator, kept as a test): pairs of pads 0.15 mm
apart (a clearance violation at the 0.2 mm default), one pair per row, each pad on a chosen net, plus copper text
"[GND]" on no net beside a pad on TXT. Writes the board and <board>.truth.json: row y -> the two net names, "" for
no net. usage: names_board.py out.kicad_pcb"""
import json, sys, pcbnew
out = sys.argv[1]
mm = pcbnew.FromMM
PAIRS = [("D[0]", "D[0]x"), ("D[0]", "D[0] x"), ("0]", "D[0]"), ("A", "[A]"), ("B[A]", "A"), ('Q"1', "Q"),
         ("<no net>", "N1"), ("no net", "N2"), ("~{RST}", "RST"), ("A/B", "/sheet/X"), ("Ωmega", "back\\slash"),
         ("LONG_" + "X" * 80, "N3"), ("{slash}", "N4"), ("X] of R1 on F.Cu | Pad 1 [Y", "Y"), ("GND", "GND2"),
         ("N5", "N5 "), ("N6", " N6"),
         # KiCad stores "/" in a label as {slash} and shows it plain in DRC text (review 7, C1)
         ("/TX{slash}RX", "/SDA{slash}SCL"), ("/I2C/SDA{slash}SCL", "/I2C/SDA")]
names = sorted({n for p in PAIRS for n in p} | {"TXT"})
b = pcbnew.NewBoard(out); b.SetCopperLayerCount(2)
nets = {}
for n in names:
    ni = pcbnew.NETINFO_ITEM(b, n); b.Add(ni); nets[n] = ni
H = 10 + 3 * (len(PAIRS) + 3)
for x0, y0, x1, y1 in ((0, 0, 40, 0), (40, 0, 40, H), (40, H, 0, H), (0, H, 0, 0)):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0))); s.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1))); s.SetLayer(pcbnew.Edge_Cuts); b.Add(s)
def fp(ref, x, y, net):
    f = pcbnew.FOOTPRINT(b); f.SetReference(ref); f.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    p = pcbnew.PAD(f); p.SetNumber("1"); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetLayerSet(p.SMDMask()); p.SetSize(pcbnew.VECTOR2I(mm(1), mm(1))); p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y))); p.SetNet(nets[net]); f.Add(p); b.Add(f)
truth = {}
for i, (a, c) in enumerate(PAIRS):
    y = 5 + 3 * i
    fp(f"R{2*i}", 10, y, a); fp(f"R{2*i+1}", 11.15, y, c)   # 0.15 mm gap: clearance against 0.2 default
    truth[y] = [a, c]
# copper text "[GND]" (no net) beside a pad on net TXT
y = 5 + 3 * len(PAIRS)
t = pcbnew.PCB_TEXT(b); t.SetText("[GND]"); t.SetLayer(pcbnew.F_Cu); t.SetPosition(pcbnew.VECTOR2I(mm(20), mm(y))); t.SetTextSize(pcbnew.VECTOR2I(mm(1), mm(1))); b.Add(t)
fp("RT", 20, y + 0.9, "TXT")
truth[y] = ["", "TXT"]
pcbnew.SaveBoard(out, b)
json.dump(truth, open(out + ".truth.json", "w"), ensure_ascii=False, indent=0)
