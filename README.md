# pcb

`pcb` is a command-line tool that takes a KiCad project from an empty folder through parts, placement, routing, copper zones and checks to the Gerber, BOM and CPL files JLCPCB makes and assembles a board from. It is written to be driven by an AI agent as much as by a person. An agent can't look at the board, so a regulator wired by the wrong pin numbering, or a part the assembly line turns the wrong way, would show up only in JLCPCB's order preview or on the boards that arrive. `pcb` checks against JLCPCB's own data instead: `pcb sync` refuses a pin whose name differs from JLCPCB's symbol, and `pcb parts` matches each assembled footprint to JLCPCB's to solve the CPL rotation. `pcb edit`, `route`, `place`, `zone`, `paste` and `art` keep the old board if KiCad's DRC gets worse, and `pcb release` reads the plotted Gerbers back against the board's nets and JLCPCB's limits before anything is ordered.

It works within these limits:
- JLCPCB only, 1.6 mm boards;
- 2 or 4 copper layers for a board `pcb sync` makes;
- assembled parts on the top side;
- boards in KiCad 10's file format, with KiCad 10.0.8 installed;
- tested only in the Ubuntu 24.04 image built from `ci/`.

[`GUIDELINES.md`](GUIDELINES.md) is the standard every board here follows: the stages a board goes through, two independent review gates, the 21 checks before an order, file naming, version numbers, JLCPCB's rules and the first power-up.

## Workflow

These steps take a new board from an empty folder to an order. `pcb route`, `pcb edit`, `pcb info` and `pcb render` take the board's path; the other commands find `pcb.toml` in the current folder, or in `--project DIR`.

1. Run `pcb new my-board --size 60x40`. It prints:

   ```
   wrote my-board: my-board, 2 layers, 19 files. Next: git init, draw hw/my-board.kicad_sch, pcb parts --live, pcb sync
   ```

   The folder holds `pcb.toml`, the records GUIDELINES asks for (`README.md`, `NOTES.md`, `CHANGELOG.md`, `VERSION`, `TAGS.tsv`, `CHECKSUMS.txt`), `AGENTS.md` and `CLAUDE.md`, a `.gitignore`, a tag-and-release GitHub workflow, and empty folders `hw/`, `parts/`, `docs/`, `reviews/`, `firmware/` and `scripts/`. `--layers` defaults to 2, `--size WxH` (mm) to 50x50, and `--mask` to green, with white silkscreen (black on a white mask). `cd my-board` and run `git init` yourself. Write the requirements brief in `README.md` before choosing any part (GUIDELINES, "Process and gates").
2. Draw the schematic in KiCad 10 at `hw/my-board.kicad_sch`, the path `[project] netlist` names; `pcb` exports the netlist from it with `kicad-cli`. Annotate it: `pcb sync` refuses a reference left as `R?` or used twice. Every part needs one of:
   - a field named `LCSC` (or `LCSC Part #`) holding its JLCPCB part number, such as `C5446`;
   - a Footprint field `LIB:NAME` and a file `footprints/NAME.kicad_mod` beside `pcb.toml`, for a part JLCPCB has no footprint for, such as a test pad. This footprint is used even when the part also has an LCSC code.

   Pin names must match JLCPCB's symbol for the part, or the datasheet names you give in `[parts.<LCSC>] pins`. KiCad's DNP and Exclude from BOM checkboxes keep a part off the BOM and CPL; so does a field named `DNP` or `exclude_from_bom` that is empty or says yes, true, 1 or x.
3. Run `pcb parts --live`. It downloads JLCPCB's footprint, symbol, stock and library type into `parts/`. Commit that folder: every other command reads only the cache. It fetches every part in the schematic that has an LCSC code, assembled or not. Run it again on order day, since stock changes.
4. Run `pcb sync`. It makes `hw/my-board.kicad_pcb` from `[outline]` and the schematic, with JLCPCB's footprints, and puts new parts in a column to the right of the outline (warning `unplaced`). Run it after every schematic change: it adds, replaces, removes and renets footprints, and removes copper left on a net no pad has any more. A change that would leave tracks joining the wrong pads is refused; `--rip` removes those tracks instead. From here `pcb status` works, and it is the first command of every session.
5. Write a `[[place]]` entry for each part you want placed by the file, and run `pcb place`. Parts without an entry can be placed by hand in KiCad. A part with an entry that is then moved in KiCad makes `pcb check` report `stale`. Write a `[[near]]` for each decoupling and regulator capacitor and an `[[edge]]` for each group of parts that belongs at an edge; `pcb check` judges both. `pcb drawing placement -o docs/placement` writes the Gate 1 placement proposal as three A3 sheets (top view, bottom view, placement table) in SVG and PNG, and one PDF.
6. Run `pcb zone` if the board has planes or pours, before routing. The router leaves a net that has a zone to its zone; without the zone it lays the net as tracks.
7. Lay the nets a router shouldn't choose for you (a crystal, a USB pair, a switching regulator's loop) by hand with `pcb edit`, and mark them `class = "critical"`. Then route the rest:

   ```
   pcb route hw/my-board.kicad_pcb --region 20,20,80,60 --project .
   ```

   The region is in KiCad's coordinates (see "Coordinates"); `20,20,80,60` is the whole of a 60 × 40 mm board made by `pcb sync`. Everything outside the region stays locked. A net with a zone is left to its fills: the router lays nothing for it and `--rip all` rips nothing of it, unless `--nets` or `--rip` names it or `--no-zones` is given. If such a net has pads its fills don't join, the run warns `plane-open`. With `--project`, a net is laid at its `[nets.<NET>] width_mm`, or at the IPC-2221 width for its `current_a` when that is wider than its existing tracks (the widest any allowed layer needs: 1 A is 0.31 mm on an outer layer and 1.57 mm once an inner layer is allowed, so give such a net a `width_mm`). Any other net is laid at its most common existing track width, or the board's default for a net with no tracks yet. `--width NET=MM` replaces all of these for one run. Also with `--project`, `pcb route` refuses to run while a critical net is incomplete and never rips or lays one. When the result makes DRC worse only where some nets' new copper runs, that copper is dropped, the rest is written, and the dropped nets are named (warning `route-partial`). Without `-o` it overwrites the board. Measure the result with `pcb quality`.
8. Run `pcb zone` again, since new tracks can cut a plane apart (warning `plane-split`), then `pcb paste` and `pcb art`. `pcb paste` applies paste rules: windows on exposed pads, pin-in-paste on plated pads, no paste on test pads. `pcb art` draws artwork from GeoJSON and text in a TrueType font, including the version on the silkscreen. Run each again after changing its settings, or `pcb check` reports it stale.
9. Run `pcb check --fab`. It runs every check below, then plots the Gerbers and reads them back. Fix each finding, or add a `[[waiver]]` with the reason, until nothing unwaived is left.
10. Run `pcb gate pass layout`. It runs `pcb check` without the read-back and, when nothing is unwaived, records the gate in `pcb.toml` with a hash of the board, its `.kicad_pro` and `.kicad_dru`, `pcb.toml` less its `[gates]`, the schematic, and the `[[art]]` files and `[[text]]` fonts. Changing any of them, or `[project] version`, makes the gate stale (`pcb gate status`). This records only that `pcb check` passed; it isn't Gate 2, the independent review in GUIDELINES check 18.
11. Run `pcb release -o order`. It refuses to run without a recorded gate, with a stale one, or into a folder that isn't empty, and writes into `order/`:
    - `my-board_v0.1.0_gerbers.zip`: every copper layer, both masks, silkscreen, the outline, paste for the sides the assembler places, and PTH and NPTH drill files, plotted by `kicad-cli` with the origin at the outline's centre;
    - `my-board_v0.1.0_BOM.csv`, columns `Comment,Designator,Footprint,LCSC Part #`;
    - `my-board_v0.1.0_CPL.csv`, columns `Designator,Mid X,Mid Y,Layer,Rotation`, in mm from the outline's centre, y up;
    - `CHECKSUMS.txt`, with bare file names: check it from inside `order/` with `sha256sum -c CHECKSUMS.txt`.

    It then reads the Gerbers back, re-checks the parts from the cache, and compares the board with the schematic and every `[[place]]`. Any problem moves the folder to `order.rejected` (then `order.rejected.2` and on), so it can't be uploaded by mistake. A clean release ends with the order options for `[finish]`, for example "order with: PCB Color Black, Silkscreen White, Surface Finish ENIG". The tag-and-release workflow publishes the project-root `CHECKSUMS.txt`, so copy the lines there with an `order/` prefix.

`pcb` doesn't make the rest of the package GUIDELINES describes: the package zip (the tag-and-release workflow builds it), the schematic and assembly PDFs, the full BOM, renders from the Gerbers, the bring-up sheet and the 1:1 fit print.

For a board that already exists, `pcb init BOARD` writes a `pcb.toml` beside it with the name, version 0.1.0, the layer count, the fab file and the widths of nets routed wider than usual. It writes no `netlist`, `pcb` pin, `[finish]` or `[quality]`; add those, then continue from step 5.

## The project file

`pcb.toml` holds what the board file can't. `pcb new` writes a starting file with the fab, finish, Economic assembly, the outline and `[quality]` limits. The limits are on from the start, so `pcb check` fails on poor routing from the first route. A misspelt key is refused. A project typically adds sections like these:

```toml
[nets.V3V3]
class = "power"          # held to [quality] power_width_mm
current_a = 0.3          # the width-current check

[nets.XTAL_IN]
class = "critical"       # with --project, pcb route never rips or lays it

[[place]]
ref = "U1"
at = [0.0, 2.5]          # footprint origin, mm from the outline's centre, y up
rot_deg = 90             # anticlockwise, seen from the top

[[place]]
ref = "J1"
at = [0.0, -17.0]
locked = true            # later runs never move it

[[near]]
part = "C3"
to = "U2.VOUT"
max_mm = 3.0
why = "LDO output capacitor, datasheet layout section"

[[edge]]
side = "bottom"
parts = ["J1"]
max_mm = 1.0
why = "USB-C mouth at the case wall"

[[zone]]
net = "GND"
layers = ["F.Cu", "B.Cu"]
clearance_mm = 0.3
thermal = { gap_mm = 0.3, spoke_mm = 0.4 }

[[text]]
name = "version"
text = "my-board v{version}"        # {version} is the project's version
font = "hw/fonts/Inter-ExtraBold.ttf"
cap_mm = 1.0
at = [0.0, 15.0]
frame = "centre"
layer = "F.SilkS"

[[waiver]]
check = "drc"
item = "courtyards_overlap <no net>"
max = 2
why = "J1's shell tabs overlap C1's courtyard by design; checked against the connector drawing"
```

The other sections are `[assembly]` (machine sides, hand-fitted parts, designator renames, boards ordered, the service), `[finish]`, `[outline]` (`rect_mm`, or a GeoJSON `file`), `[[keepout]]`, `[fill]` and `fill_grow_mm`, `[[stitch]]`, `[[net_tie]]`, `[[pad_override]]`, `[[drc_allow]]`, `[[paste]]`, `[[art]]`, `[parts.<LCSC>]`, `[bringup]`, `[drawing]` and `[decisions]`. `[parts.<LCSC>]` holds CPL offsets and datasheet pin names, and needs a `source` saying where they came from. `[decisions]` records owner decisions an agent must not ask about again. The fields of every section are the structs in [`src/project.rs`](src/project.rs); "Project file" in [`DESIGN.md`](DESIGN.md) explains most of them.

`[project] pcb` pins the tool, for example `pcb = "0.8"`. The commands that check the project (`status`, `parts`, `sync`, `place`, `zone`, `paste`, `art`, `check`, `gate pass`, `release`, `drawing`, `render --look`) refuse a build of another MINOR version, and a pin of `"0.8.0"` accepts that version alone. A MINOR release of `pcb` is one that could make a passing board fail or changes a file `pcb release` writes, so a pinned board keeps being judged by the checks it was designed under.

## Coordinates

Three frames are in use, and a value in the wrong one moves a part or a region by half the board.

| Frame | Origin and axes | Used by |
| --- | --- | --- |
| Centred | The outline's bounding-box centre, y up, mm | `[[place]]`, `[outline]` GeoJSON, `[[art]]` and `[[text]]` with `frame = "centre"`, the CPL, the Gerbers |
| KiCad | KiCad's origin, y down, mm | `pcb route --region`, `pcb edit` points, `[[keepout]] rect`, `[[stitch]] rect`, `frame = "board"`, `pcb render --region`, `pcb info` |
| Datum A | The board's lower-left corner, y up, mm | The placement table of `pcb drawing` |

A board `pcb sync` makes has the outline's top-left corner at KiCad (20, 20). On a board W × H mm, the centred point (x, y) is KiCad (20 + W/2 + x, 20 + H/2 − y): on 60 × 40 mm the centre is KiCad (50, 40) and the whole board is the region `20,20,80,60`. `[[edge]] side` names the edge as the board is drawn, so `top` is the edge at the smaller KiCad y.

## What `pcb` checks

### When the board changes

`pcb edit`, `route`, `place`, `zone`, `paste` and `art` write through one gate. It runs KiCad's DRC on the board before and after the change. A result with any new violation is written beside the output as `<name>.rejected.kicad_pcb` (for example `hw/my-board.rejected.kicad_pcb`) with the new violations listed, and the board is left as it was. Some growth is accepted:
- `zone`, `place`, `paste` and `art` accept what a `[[drc_allow]]` entry names, up to its `max` and with a reason;
- `place` accepts unconnected items on the nets whose tracks it removed;
- `route` accepts unconnected items and dangling vias on nets that have a zone, which the next `pcb zone` joins.

A DRC in which KiCad listed only its first 199 violations of a type (499 for clearance) is refused, because past that limit KiCad lists a different set on each run.

`pcb sync` writes the board without the gate. It reads its own result back instead: every pad must carry its net from the schematic.

`pcb edit hw/my-board.kicad_pcb --ops ops.json` (or `--ops -` to read standard input) applies a list of operations, each naming its target and what it expects to find there, in KiCad coordinates:

```json
{"ops": [
  {"op": "add_track", "net": "V3V3", "layer": "F.Cu", "width": 0.4, "points": [[42.0, 30.5], [47.5, 30.5]]},
  {"op": "move_footprint", "ref": "C3", "from": [51.0, 36.0], "to": [49.5, 36.0]}
]}
```

It refuses the whole list, writing nothing, when no item is where an operation points (`edit-no-target`), when the item is there but differs (`edit-mismatch`), when new copper joins nothing of its net (`edit-unjoined`), or when an item is locked and the operation doesn't say `"unlock": true` (`edit-locked`). The operations are `add_track`, `add_via`, `move_via`, `delete`, `set_width`, `move_footprint`, `set_pad`, `silk_widen`, `silk_clear`, `silk_remove`, `add_slot` and `add_hole`. "Edit language" in `DESIGN.md` gives their fields.

### Building and placing

| Refused by | Condition |
| --- | --- |
| `sync` | A connected pin number the footprint has no pad for |
| `sync` | A pin name that differs from JLCPCB's symbol or `[parts.<LCSC>] pins`. JLCPCB's record for the XC6206 regulator (C5446) carries two pin numberings, and a schematic drawn from the wrong one puts USB power on the regulator's output |
| `sync` | Tracks on a net whose pads change, without `--rip` |
| `sync`, `place` | Removing, replacing or moving a locked part |
| `place` | An assembled part on a side not in `[assembly] machine_sides` |
| `place` | A pad centre off the outline, or pads in a `[[keepout]]` that forbids footprints |
| `place` | A part over a plated through-hole pad of a part on the other side, which is copper on both sides |

`pcb place` removes the tracks ending on a part it moves, with anything that hangs from them alone, and lists them.

### Parts

`pcb search WORDS [--package P]` finds a part before it is in the schematic. It asks JLCPCB's parts API and lists Basic parts first, then Preferred, then Extended, the largest stock first, each with its LCSC code, package, stock and price. Parts that need Standard assembly are left out unless `--standard` is given. With `--package` and no Basic or Preferred part in that package, it also lists Basic parts in other packages (warning `basic-other-package`): GUIDELINES asks for the next package size before an Extended part. For example, `pcb search 100nF --package 0201` finds no part Economic assembly takes and lists the Basic 0402 and 0603 ones.

`pcb parts` judges every assembled part from the cache:

| Code | Condition |
| --- | --- |
| finding `missing` | No JLCPCB data, or the part isn't listed |
| finding `stock` | Stock under `[assembly] boards` (default 5) times the part's count |
| finding `economic` | JLCPCB marks the part Standard-only (`componentProductType` 2), whatever `[assembly] service` says |
| warning `buy-ahead` | Stock under 20 times the need, or under 1000 |
| warning `extended-parts` | Extended parts that aren't Preferred, each a loading fee, listed. Preferred Extended parts carry no fee; they are named after the others, and `data.parts[].preferred` marks each |
| warning `parts-stale` | Data over 30 days old |

It also matches each assembled top-side part's pads to JLCPCB's footprint over the four quarter turns. JLCPCB's pads must land within 0.05 mm of the board's (0.15 mm for two-pad parts). The turn and origin that fit must equal `[parts.<LCSC>] rotation_offset_deg` and `cpl_offset_mm` (zero when absent), the origin within 0.02 mm (0.1 mm for two-pad parts). A two-pad part matched by shape alone, or a pad pattern that fits at more than one turn, is a finding, because the CPL could place it reversed. Numbering a footprint's pads as JLCPCB's footprint does avoids both.

### `pcb check`

KiCad's DRC runs twice, once with the board's own rules and once with the fab's from `fab/`. Each violation counts at the larger of the two, and unconnected items and shorts are errors whatever the board's settings say. It then runs these checks:

| Finding | Condition |
| --- | --- |
| `erc` | KiCad's ERC on the schematic, when `[project] netlist` is a `.kicad_sch`: each violation type KiCad calls an error, plus `multiple_net_names` and `same_local_global_label`, where a net isn't the net its name says. Other ERC warnings are listed in one warning (`erc-warnings`); library-link warnings are ignored. With a `.net` file it warns `erc-skipped` |
| `circuit` | Five rules of thumb over the netlist, each waivable where it doesn't apply: an IC supply pin with no capacitor to ground (`decoupling U1 +3V3`); a USB-C receptacle's CC1 or CC2 with no 5.1 kΩ to ground and no controller, the two tied together, or a pull-down of another value (`usb-cc J1 CC1`); an I2C net with no pull-up to a supply (`i2c-pullup U1 SDA`); a crystal terminal with no load capacitor to ground (`crystal-load Y1`); a two-pin LED with no resistor in series on either terminal (`led-resistor D1`). They read reference prefixes (`U`, `C`, `R`, `Y`, `D`, `J`), pin names and net names, so a part named otherwise isn't judged |
| `stale` | `pcb zone`, `paste` or `art` hasn't run since its settings or files changed; what `paste` or `art` made is missing from the board; or the board differs from the schematic (parts, values, LCSC codes, flags, every pad's net) or from a `[[place]]` |
| `width-current` | The narrowest track per layer on a net with `current_a`, against IPC-2221 at a 10 °C rise (outer 1 oz, inner 0.5 oz) |
| `via-current` | A net with `current_a` whose pads are joined only through vias that together carry less: each via carries what its barrel does (IPC-2221 at a 10 °C rise, 18 µm plating: 1.4 A for a 0.3 mm hole). The item names the first via (`V5 via 30.5 44.2`) |
| `near` | A part farther than `max_mm` from its pin, pad centre to the nearest pad centre on the same net |
| `edge` | A part's footprint origin farther than `max_mm` from the outline, measured towards its side, or outside the outline; or a hole with less than `min_web_mm` of board to the nearest edge |
| `spec` | With a `[finish]` and Economic assembly: a board spec the service refuses (4 layers other than green, ENIG other than green, black 2-layer without HASL). On 6 layers it warns `spec-unchecked` instead |
| `via-in-pad` | A via's hole in a pasted pad of an assembled part; an open drill wicks solder away from the joint |
| `paste` | An assembled SMD pad with no paste |
| `paste-unassembled` | Paste on a part left out of the CPL, on its pads or drawn in its footprint, which JLCPCB would print and reflow into a solder bump |
| `side` | An assembled part on a side not in `machine_sides` |
| `cpl-bottom` | Any part assembled on the bottom. `pcb release` writes its CPL rotation as seen from the bottom, a rule JLCPCB doesn't publish, so check each in JLCPCB's placement preview and waive this with the date |
| `silk` | Silkscreen lines under 0.15 mm; text under 0.6 mm cap height |
| `silk-owner` | A visible footprint reference whose middle is nearer another part's pads than its own, or that lies over another part's pad and clear of its own part |
| `ring` | Annular rings under 0.13 mm on vias, 0.2 mm on plated pads |
| `edge-setting` | An outline with arcs and zones, and a copper-to-edge setting under 0.35 mm: pours fill to chords of a curve and read back under 0.3 mm |
| `testpoint` | A `[bringup] test_points` reference missing, or with no exposed outer pad |
| `quality` | A route measure over its `[quality]` limit: power track width, detour against the shortest path, vias on a two-pad net, segments per 10 mm, distinct widths, length run over another net's track on the other side, small pieces of a pour. Two measures follow the copper: `max_decap_loop_mm`, the copper from an IC's supply pin through its nearest decoupling capacitor and back to its ground pin (`decap-loop U1 +3V3`), and `max_unreferenced_mm`, the outer-layer track of a `critical` net with no ground fill on the next layer in (`unreferenced XIN`); with no ground fill on the board, all of it |

In the JSON output a finding carries `at`, its place on the board in KiCad's coordinates, when it names one part, pad or via or is a DRC kind (the first violation's place), and `fix`, the command or change that clears it, where one does.

`pcb check` exits 1 while any finding is unwaived. A `[[waiver]]` gives the check, the item exactly as `pcb check` prints it, the most it may count, and the reason. Copy the item from the output: a DRC item is the kind followed by the nets involved, such as `courtyards_overlap <no net>`. Waived findings are listed with their reasons, and a waiver that matches nothing is warned. `stale` and `spec` take no waiver; for `spec`, set `[assembly] service = "standard"` if you mean to pay for Standard assembly.

### The Gerber read-back

`pcb release` and `pcb check --fab` plot the Gerbers and drill files and read them back from the files alone. The copper's connectivity is rebuilt from the Gerbers and plated holes, and each pad must sit in its net's island: a net in two islands is open, and an island holding two nets is a short. These limits are measured on the plotted shapes, with the numbers from `fab/`:

- copper at least 0.15 mm wide everywhere, and 0.15 mm from other nets;
- copper 0.3 mm from every ring of the outline, cut-outs included, and none off the board;
- holes of different nets 0.5 mm apart edge to edge, holes of one net 0.254 mm;
- copper 0.2 mm from an unplated hole;
- silkscreen at least 0.15 mm wide, off exposed copper and off open holes;
- on 4 and 6 layers, inner copper of another net 0.3 mm from a component hole and 0.2 mm from a via.

KiCad's DRC judges the board's objects and the read-back judges the plotted shapes. So the read-back finds what the DRC can't: a neck under 0.15 mm left where a pour or artwork meets a track, and copper near an unplated hole, which KiCad has no rule for. A limit finding is waived with `check = "dfm"` and `item = "<rule> <layer>"`, such as `cu_edge F.Cu`. Opens, shorts and inner copper near a hole can't be waived; JLCPCB won't make the last. Mask openings closer than the fab's solder mask bridge, and silkscreen over tented vias, are warned.

### Coverage of GUIDELINES

`pcb` runs all or part of GUIDELINES checks 2 to 4 and 6 to 16, 19 and 21:

| GUIDELINES check | What `pcb` does |
| --- | --- |
| 2 Pins against the datasheet | Pin names against JLCPCB's symbol or your datasheet names; it can't read a datasheet or a connector drawing |
| 3 JLCPCB eligibility and stock | `pcb parts` |
| 4 Ratings and margins | `circuit`: decoupling, USB-C CC resistors, I2C pull-ups, crystal load capacitors and LED resistors are present; apart from the 5.1 kΩ CC pull-down, not their values, ratings or margins |
| 6 Design for test | `testpoint`, and `erc`: KiCad's ERC |
| 7 DRC | `pcb check`, twice |
| 8 Netlist match | `stale`: the board against the schematic |
| 9 Current, thermal and signal | `width-current`, `via-current`, `near`, `quality` (the decoupling loop and ground under critical nets among its measures); not heat, and not a return path's shape beyond ground being under the track |
| 10 Mechanical fit | `[[edge]]`, footprint keep-outs, the off-board refusal; not mating parts or enclosures |
| 11 to 13 Gerber set, connectivity, DFM | The read-back |
| 14 Paste layer | `paste`, `paste-unassembled`, `via-in-pad` |
| 15 Renders from the Gerbers | `silk-owner` (designator placement) |
| 16 BOM and CPL | `pcb release`, `pcb parts`, `spec`, `cpl-bottom` |
| 19 Release record | `CHECKSUMS.txt` |
| 21 On order day | `pcb parts --live` re-checks stock |

Checks 1, 5, 17, 18 and 20, and the rest of check 4, are a person's or a reviewer's: the requirements trace, ratings and margins, protection, firmware, the independent Gate 1 and Gate 2 reviews and the package check.

### Known limits

- `[[edge]]` measures from each footprint's origin, so for a large part the distance isn't its body's. It measures to the outline drawn on the board, cut-outs included; an outline held in a footprint isn't read, and one that isn't closed gives `edge` findings with the wrong reason.
- `silk-owner` reads only KiCad's own reference text, and takes its width as one character width per letter. A top- or bottom-justified reference, or one with "keep upright" off, is placed up to half its height or its whole length off. A board whose designators are artwork gets no judgement, so the reviewer checks those by eye.
- Paste drawn as footprint graphics counts for `paste-unassembled` only: on an assembled part `paste` still asks for paste on the pads, and the Gerber read-back doesn't judge drawn paste. Draw paste as pads.
- The copper lengths `pcb` measures are lower bounds: a path counts a fill as the straight line between the two things it joins, and a via as 1.6 mm. `via-current` judges a group of vias that is the only copper between some of a net's pads. It holds `current_a` against every branch, so a pull-up behind one via on a 2 A net is a finding to waive, and it stays silent where the current is shared between vias that join different pieces of copper. The decoupling loop is measured for the nearest capacitor of each IC supply net, not for each supply pin, and only when the netlist names or types the IC's supply pins.
- A bottom-side part's CPL rotation follows the rule JLCPCB's importers use (180 minus KiCad's angle, plus the part's offset). No order of ours has proved it, so `cpl-bottom` stays a finding until the placement preview has been checked.
- The `circuit` rules check that a part is there, not that it is the right value or near enough: a 100 pF capacitor passes `decoupling`, and its distance from the pin is a `[[near]]` rule's. `pcb search` and `pcb parts --live` use JLCPCB's parts API, which is not a published interface and can change.
- `pcb route` refuses a board with track arcs (`arc-unsupported`): replace them with segments, or route that net by hand. Paste windows work on the top side only, and `add_via` makes through vias only.
- `pcb new --layers 6` is accepted, but `pcb sync` can't make the board. JLCPCB publishes no Economic assembly colour or finish rules for 6 layers, so on that process `pcb check` warns `spec-unchecked` and doesn't judge the spec. There is no 8-layer fab file.
- Fab files exist for JLCPCB's 1.6 mm 2-, 4- and 6-layer processes. Another process is a new file in `fab/` and a line in `src/fab.rs`.

## Commands

`pcb --help` lists every command and `pcb <command> --help` its options; [`DESIGN.md`](DESIGN.md) describes each in full.

| Stage | Commands |
| --- | --- |
| Start | `pcb new`; `pcb init BOARD`; `pcb doctor` |
| Parts and circuit | `pcb search WORDS`, `pcb parts`, `pcb sync` |
| Layout | `pcb place`, `pcb route BOARD`, `pcb edit BOARD`, `pcb zone`, `pcb paste`, `pcb art` |
| Checks | `pcb check [--fab]`, `pcb quality` |
| Gates and release | `pcb gate status`, `pcb gate pass NAME`, `pcb release -o DIR`, `pcb compare-gerbers A B` (two Gerber sets compared shape by shape; every difference needs an explanation or the outcome is rejected) |
| Inspection | `pcb status`; `pcb info BOARD` (the board, one part or one net); `pcb diff A B` (two boards or git revisions as `REV:path`: parts moved, copper per net, zones); `pcb render BOARD` (a PNG with nets labelled, or `--look` for the board as it will look made, in the `[finish]` colours); `pcb drawing placement` |
| Import and diagnostics | `pcb import-tscircuit` (a KiCad board from a tscircuit circuit JSON); `pcb roundtrip` (a check that pcb's KiCad parser writes a board back unchanged) |

The `pcb route` options a first route needs are `--region`, `--project`, `--width`, `--rip NETS` (clear and re-route a net's copper inside the region) and `--layers`, which defaults to `F.Cu,B.Cu`, so inner layers are routed only when named. `--timeout` is 900 s per Freerouting run, and a route runs Freerouting up to `--attempts` plus one times. When a route leaves nets open, try `--attempts 4`: each attempt after the first gives the router the nets in another order, and the one leaving fewest open is kept. `pcb route --help` lists the rest.

Every command prints a summary and exits with one of these codes:
- 0, done;
- 1, the result was rejected (a DRC regression, unwaived findings, a failed read-back);
- 2, it refused its input (`pcb gate pass` with unwaived findings is a refusal, `gate-check`);
- 3, it failed.

With `--json` it prints one object instead: `schema`, `ok`, `outcome`, `data` and `warnings`, plus `written` when it wrote a file and `error` (`code` and `message`) when it refused or failed. `schemas/<command>.json` describes `data` for each command, and [`docs/codes.md`](docs/codes.md) lists every error and warning code with what to do about it.

Scratch files go under `pcb_work/` in the folder you run from (`--work` sets another). `pcb` marks each folder it creates git-ignored.

## Install

`pcb` is tested against these versions only:

- KiCad 10.0.8, with `kicad-cli` on the path and a `python3` that can import `pcbnew`;
- Freerouting 2.5.0 on Java 25 or later;
- `python3` with shapely, and gerbonara 1.6.3 with click and rtree, for the Gerber read-back;
- `curl` for `pcb parts --live`, `git` for `pcb diff REV:path`, and `sha256sum`;
- Rust 1.97.0 to build it.

`pcb doctor` checks the KiCad, Java and Freerouting versions and the KiCad behaviours `pcb` relies on; nothing checks the Python packages. The image built from `ci/Dockerfile` holds all of the above. Build it and `pcb` from this repository's folder:

```
docker build -t pcb-ci:8-local ci/
docker run --rm -v "$PWD":"$PWD" -w "$PWD" pcb-ci:8-local cargo build --release
```

Then run `pcb` in the image with your project mounted. From the `pcb` folder, for a project in `~/boards/my-board`:

```
docker run --rm -v "$PWD":"$PWD" -v ~/boards:/work -w /work/my-board pcb-ci:8-local "$PWD"/target/release/pcb doctor
```

The container runs as root, so on a Linux host the files it writes are owned by root. The image sets `PCB_FREEROUTING_JAR`. Outside it, set that variable to the jar's path or pass `--freerouting`, and set `PCB_JAVA` if the `java` on the path is older than 25. A board in an older KiCad format is refused with the `kicad-cli pcb upgrade` command to convert a copy; one from a newer KiCad is refused too.

## Tests

Run `cargo xtask test` in the image before every push; GitHub runs no tests. It runs every command on three fixture boards (`sample_node`, and paddle-keyer both imported from tscircuit and built from its netlist) and checks the results with independent oracles. [`tests/README.md`](tests/README.md) explains the layout. Useful flags:
- `--only WORD` runs one group, such as `--only sample_node`;
- `--full` clears the cache, so every step runs (later runs otherwise repeat only the steps whose inputs changed);
- `--fast` skips the Freerouting runs and the mutation suites.

## Also in this repository

| Path | What it is |
| --- | --- |
| [`STYLE.md`](STYLE.md) | How the documents, commit messages and reviews in `pcb` and the project repositories are written |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each version |
| [`docs/drawing-standard.md`](docs/drawing-standard.md) | The house style `pcb drawing` follows |
| [`fab/`](fab/) | JLCPCB's limits per process, and the board specs its Economic assembly refuses |
| [`schemas/`](schemas/) | The JSON output of each command |
