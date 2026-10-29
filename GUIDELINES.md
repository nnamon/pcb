# PCB Project Guidelines: Deliverables, Checks, Formats

Last updated 24 Oct 2026. Mirrors the Claude doc "PCB Project Guidelines"; when one changes, update the other.

Every board in this project ships as one versioned zip that a person can order from without reading the source, and it passes two independent review gates (schematic, then release) plus checks on the final Gerbers before anything is ordered. These rules come from the Quansheng paddle adapter (v1.0.0, two boards) and the paddle keyer (v0.2.x).

## Principles

- **The Gerbers are the truth.** Anything added after export (art, copper logos, paste fixes, pours) bypasses the design-level DRC, so every check that matters re-runs on the final Gerber and drill files.
- **Check what JLCPCB will actually do.** Footprint rotations, Economic eligibility, Basic vs Extended and DFM limits are checked against JLCPCB's own data, not assumed from the design tool.
- **Never grade your own work alone.** Fresh reviewers that haven't seen the design reasoning check it at both gates. On v0.0.2 the first review found an overloaded resistor, a missing coil clamp diode, a firmware stuck-key bug and 8 parts that did nothing.
- **Review early, when changes are cheap.** A schematic error found before layout costs minutes; after routing it costs a re-layout; after ordering it costs a board spin.
- **Unrecorded means unchecked.** Each release records which checks ran, with what script, on which files, and the result.
- **Prototype economics.** Default to HASL, ink-jet silkscreen, green, 1.6 mm, Economic assembly. Upgrades like ENIG or high-precision silkscreen cost about 4× the board on tiny boards, so they need a reason.
- **Scope and limits.** These guidelines cover low-voltage USB and battery boards. Mains, Li-ion charging, high current and RF transmit paths need review by a qualified person before ordering. Claude can't verify a physical board, so first-article testing and fit are checked by hand.

## Process and gates

Each stage ends at a gate with written exit criteria. A change after a gate re-runs the checks it affects, and goes back through the gate if it touches the schematic.

1. **Requirements.** A one-page brief at the top of the README, before any part is chosen. It covers function, interfaces and their mating parts, supply range and power budget, size and mechanical limits, environment (handheld, outdoor, near RF), quantity, target cost, and pass/fail acceptance tests. Exit: the person agrees the brief.
2. **Schematic.** Parts chosen and checks 1–6 pass. Exit: **Gate 1**, an independent schematic review before any layout.
3. **Layout.** Placement, routing and art; checks 7–17 pass on the final files.
4. **Release.** **Gate 2**, the independent release review (check 18), then freeze. Files are checksummed, and any later change to `order/` bumps the version.
5. **Order and bring-up.** Order exactly the released files and record the order in `NOTES.md` against the version. Bring-up follows the README, and failures go to the errata.

## Naming and versioning

Every file a person uploads or keeps carries the project, board and version in its name, so nothing generic like `gerbers_upload_this.zip` ever leaves the workspace.

| Item | Pattern | Example |
| --- | --- | --- |
| Package | `<project>_v<x.y.z>.zip` | `paddle-keyer_v1.2.0.zip` |
| Gerber zip | `<board>_v<x.y.z>_gerbers.zip` | `A_L-shape_v2.0.3_gerbers.zip` |
| BOM | `<board>_v<x.y.z>_BOM.csv` | `B_straight_v2.0.3_BOM.csv` |
| CPL | `<board>_v<x.y.z>_CPL.csv` | `paddle-keyer_v1.2.0_CPL.csv` |
| Firmware | `<project>_fw_v<x.y.z>.uf2` | `paddle-keyer_fw_v1.4.1.uf2` |

- **Version on the board.** The silkscreen carries the full version (`v2.0.3`) and matches the file names. Update it with every bump that changes the order files; a script should do this so it is never missed.
- **Multiple boards in one project** get a letter and a short shape name (`A_L-shape`, `B_straight`). They share the project's version, and each is its own JLCPCB order with its own files. Alternative designs of the same board, where only one will be ordered, share the version with a letter suffix (`0.2.1a`, `0.2.1b`) and each has its own board folder.
- **Version control.** Design sources and scripts live in this repository (`nnamon/claude-pcb`) with a tag per version (`paddle-keyer-v1.2.0`), so any board, ordered or not, can be regenerated exactly.

### Version numbers

Versions are `MAJOR.MINOR.PATCH`. MAJOR counts board spins sent to JLCPCB; MINOR and PATCH count the work within a spin. MAJOR `0` is pre-production: a project that has never been ordered is `0.MINOR.PATCH`.

| Part | Meaning | Bump when | Resets |
| --- | --- | --- | --- |
| MAJOR | Fabrication spin. Spin N is the Nth design sent to JLCPCB. | Starting work after a spin has been ordered. | MINOR and PATCH to 0 |
| MINOR | Big change within the spin. | The circuit, interfaces or physical form change: parts added, removed or given a new function; connector, outline or mounting changes; re-placement or re-route of a significant area; a new firmware feature that needs hardware support. | PATCH to 0 |
| PATCH | Iterative change within the spin. | Anything else that changes the order files: a value or part swap with the same function and footprint, routing and clearance fixes, silkscreen and art, paste and DFM fixes, BOM/CPL corrections. | nothing |

- **Spin lifecycle.** Spin 2 starts at `2.0.0` and moves through `2.0.1`, `2.1.0`, `2.1.1` and so on. Whatever version is current when it passes Gate 2 is the one ordered, for example `2.1.1`. That version is tagged and frozen, and the next change starts `3.0.0`.
- **Gates by bump.** A MINOR bump goes back through Gate 1 before layout continues. A PATCH bump re-runs the checks it affects. Every ordered version passes Gate 2, whatever it took to get there.
- **Re-ordering** the same files keeps the same version; add the new order to `NOTES.md` and the tag message. Any change at all, even silkscreen, is a new PATCH and therefore a new spin once ordered.
- **No bump** for README, notes or other changes that leave `order/` and firmware unchanged.
- **Every version is tagged** when it is committed: hardware `<project>-v<x.y.z>`, firmware `<project>-fw-v<x.y.z>`, annotated. Add a line to `TAGS.tsv` (tag, commit, message). Agent sessions cannot push tags, so `TAGS.tsv` is the record of each version's commit; the "Tag and release" workflow, run by hand, creates the tags and GitHub releases (package zip or firmware files, pre-release for `0.x`). The tag message says whether the version was ordered.
- **Firmware** has its own version, `<hw major>.<minor>.<patch>`, tagged `<project>-fw-v<x.y.z>`. Its MAJOR always equals the hardware spin it targets, so firmware 2.x.x runs on spin 2 boards. Its MINOR and PATCH follow the same rules for features and fixes, independently of the hardware's. The firmware reports both its own version and the hardware spin it expects.
- **CHANGELOG.md** lists what changed in each version and why, including review findings fixed.

## Package and deliverables

The package is the one download a person needs: the `order/` folder is everything JLCPCB gets, and the rest is for understanding, review and the next version.

```
<project>_v<x.y.z>/
  README.md
  CHANGELOG.md
  CHECKSUMS.txt     SHA-256 of every file in order/
  order/            upload these, nothing else
    <board>_v<x.y.z>_gerbers.zip
    <board>_v<x.y.z>_BOM.csv
    <board>_v<x.y.z>_CPL.csv
  docs/
    <board>_v<x.y.z>_schematic.pdf
    <board>_v<x.y.z>_assembly.pdf    top and bottom, designators and polarity marks
    <board>_v<x.y.z>_BOM_full.csv    see columns below
  firmware/         if the board has an MCU
    <project>_v<x.y.z>.uf2
    <source>/       buildable source, toolchain and core versions noted
    config.html     if there is a config tool
  renders/
    both_sides_from_gerbers.png
    block_diagram.png
  source/           for external reviewers
    readable hand-written design source, datasheet pin names
    netlist.csv     pad-level
    KiCad schematic
  design/           scripts that regenerate the order files and run the checks
```

The full BOM carries one row per line with designators, quantity, value, package, manufacturer, MPN, LCSC code, Basic/Extended, DNP flag and an alternate part where one exists. JLCPCB's BOM stays in its own format in `order/`.

The README covers, in this order:

1. **Requirements brief** and its acceptance tests.
2. **Summary:** what the board does, size, layers, part count, BOM lines, Basic vs Extended count.
3. **Fabrication notes:** FR-4 TG135, 1.6 mm, 1 oz outer copper, HASL, green mask, white silk, IPC-A-610 Class 2 workmanship, and anything non-default.
4. **Ordering steps,** naming each file to upload and every JLCPCB option that differs from default, with remarks ready to paste.
5. **Expected costs:** Extended-part fees, edge rails, "Remove Mark".
6. **Verification record:** each check, the script or reviewer, the date and the result; review findings and how each was closed; waivers with their reason.
7. **Assumptions** that only the physical board can confirm.
8. **Bring-up:** expected rail voltages and idle current, the meter checks before first power, then the acceptance tests.
9. **Known issues (errata),** updated after bring-up.

Alongside the package, keep `<project>/NOTES.md` (status per version, order records, bring-up logs and lessons) updated after each design, order and bring-up.

## Required checks before ordering

A board is orderable only when every check below passes on the final files, or carries a written waiver in the README. A failure sends the design back, and the later checks re-run.

**Schematic (Gate 1)**

1. **Requirements trace.** Every requirement maps to a circuit block or firmware feature, and every block maps back to a requirement. This catches parts that do nothing.
2. **Pins against the datasheet.** Map every IC, connector and polarised part by pad position against the datasheet and the EasyEDA footprint and symbol. tscircuit's JLCPCB import swapped VIN and VOUT on the XC6206 LDO.
   - For every connector, check the mating part as it will physically meet the board: gender (badges carry the female SAO header, add-ons the male), the side the cable or board enters, and its orientation when fitted. Read the connector's section drawing for which side the FFC/FPC enters relative to the solder tails, and derive the pin-to-pad map from the flat cable's real path. On nandynarwhals-defcon-sg-2027-badge 0.1.0 the SAO header was male and the e-paper map assumed the wrong mouth side; 0.2.0 first reversed every e-paper pin.
   - For a module on a header, confirm which way its header is fitted (on a Pi-style module, pins up on the component side means it mounts face down) and map the socket from that flip. Check that the module's holes and header stay aligned after the flip.
3. **JLCPCB eligibility and stock.** Query each LCSC code for library type (Basic/Extended), `componentProductType` (0 = Economic OK, 2 = Standard only) and stock. Prefer Basic, and flag low stock in the README. A part with stock under 20 times the need, or under 1000, goes in a buy-ahead table: the owner buys it into the JLCPCB parts library (or the LCSC cart if hand-fitted) before ordering.
4. **Ratings and margins.**
   - Resistors at ≤ 50 % of rated power (I²R × duty).
   - MLCCs rated ≥ 2× working voltage, since DC bias cuts their capacitance.
   - Semiconductors within voltage and current ratings with margin.
   - Logic-level MOSFETs for 3.3 V gate drive.
   - Solve each transistor stage's DC operating point, feedback included, and rate its parts from that solution rather than the intended current. On Nightjar 0.1.0 a collector-base feedback resistor set 18 mA where the comment said 10 mA, and an emitter resistor ran at 108 %.
   - A power amplifier's load line includes the output network's loss, and its harmonic terminations are part of the design. Nightjar 0.1.0's load ignored a 0.75 dB loss and left the drain inductive at 2f; together they cut 10 W to an estimated 2–6 W.
   - A transmitter's PA and driver are simulated large-signal with the maker's SPICE models, from the exciter's real source impedance to the antenna, at every supply and load corner: SWR 3 at all phases, open, short, and the drive with the level control failed. Report output power, drain peaks against the rating, dissipation and junction temperature, and run a no-drive kick test into a short and an open. Stability also needs large disturbances: key-up from full drive and from over-drive, an abrupt cut (interlock, reset), into every load, watched for at least 1 ms afterwards. Small kicks only prove the operating point is stable; on Nightjar 0.1.0 a 1 kΩ drain-gate feedback damped every kick but latched a 3 MHz limit cycle after a key-up into a short (round 7). Then check every firmware protection rule against that model in time (bias recovery, thermal tails, calibration start points), since rules written from steady-state figures tripped on normal keying (round 10). On Nightjar 0.1.0 this found a 70 MHz drain ring reaching 91 V of 100 V, a 3.5 MHz oscillation into a short, and an op-amp exciter that could not reach 10 W in the slow-part corner; linear network models had shown none of them.
   - Name the heat sink and its mounting. Size it for continuous carrier at the maximum ambient, then derive the fold-back time from the device's transient thermal impedance at the worst fault dissipation.
   - An op-amp drives at most the capacitive load its datasheet allows. A reference buffer feeding a large decoupling capacitor needs an isolation resistor inside the feedback loop; one driving a switch at RF needs a hold capacitor at the switch, since its open-loop output impedance is tens of ohms there.
5. **Protection and defined states.**
   - ESD protection on lines a person or cable touches.
   - Reverse-polarity and overcurrent protection where power comes in.
   - A clamp diode on every inductive load.
   - Trace the DC path through every RF network. Wherever a DC rail meets an inductor to ground or a connector, a series capacitor breaks the path. Nightjar 0.1.0 had none at the PA drain, so VSYS reached the antenna and shorted through the receive inductors.
   - A transmit/receive switch has a hardware interlock, so the transmitter cannot be driven while the receive path is unprotected.
   - USB-C CC pull-downs of 5.1 kΩ.
   - No floating inputs, and outputs safe at reset and when unpowered.
   - No back-powering through I/O from a connected device.
   - Lines another device reads (a radio's key input, say): read how its firmware samples them before adding filtering, ESD parts or any other load. Note the pull-up, any discharge or settle timing, and what it does with an ambiguous read, then set a capacitance and leakage budget for the line. The NR7Y firmware samples its USB paddle pins microseconds after discharging them, so the v1.0.0 adapter's 1 nF RF capacitors held a released dah pressed.
   - RC corners well away from the signal; simulate (SPICE) any analog block whose behaviour depends on values.
   - Prefer an integrated protection part (eFuse, surge stopper) to a discrete feedback clamp. A discrete clamp is a control loop: check its phase margin over part spread and temperature, and set its threshold from a temperature-stable reference, not a zener at a few microamps. On Nightjar 0.1.0 a zener-referenced clamp had 4–14° of margin and moved 2 V with temperature.
   - Every capacitor's surge or rush-current rating holds at hot-plug (polymer types are often limited to about 10 A), and every pass transistor's pulsed rating holds at the inrush the lead allows.
   - An input protected by a series resistor, a clamp and a pull-up still reaches a valid logic low when the far end is pulled to ground: the pull-up must be several times the series resistor. Check the unpowered case too: the clamp must hold the pin under its limit with the processor off.
   - Sum the datasheet maximum currents before setting a current acceptance limit.
6. **Design for test.** Test points on every rail and GND, programming and debug access (SWD, BOOT), and acceptance tests that can run without probing fine-pitch pins. ERC is clean.

**Layout**

7. **DRC** clean against JLCPCB's limits (table below).
8. **Netlist match.** `compare_netlist.py` proves the readable source matches the routed board.
9. **Current, thermal and signal.**
   - Trace widths sized for each net's current (IPC-2152), with copper for parts that dissipate heat.
   - Decoupling capacitors at their pins.
   - Unbroken return paths under fast signals.
   - USB pairs and crystals routed per the MCU's hardware guide.
10. **Mechanical fit.** Check connector positions and overhangs against the mating parts' drawings, plus keep-outs and the outline. When fit matters, use a 1:1 paper print with the real parts laid on it, or a STEP check against the enclosure.

**Final Gerbers and drill files**

11. **Gerber set complete.** RS-274X (X2 preferred) plus Excellon drill. Every expected layer is present, the outline is closed, and the units and origin match the CPL.
12. **Gerber connectivity.** Rebuild copper islands from the Gerbers and drill, handling pour polarity, and compare them with the intended netlist: no opens, no shorts, no unconnected pads. Re-run after any post-export edit.
13. **DFM.** `jlc_dfm.py` checks trace and gap, copper-to-edge, annular ring, hole-to-hole between nets, slots, mask dams, silk width, and silk over pads or drills.
14. **Paste layer.** Apertures 1:1 with the pads, and exposed pads windowed to about 65 % coverage. tscircuit's default of 70 % × 70 % is too little at 0.4 mm pitch.
15. **Renders from the Gerbers.** Look at both sides: silkscreen not under parts, art and labels where intended, orientation right.

**Assembly files and firmware**

16. **BOM/CPL.**
    - Every designator exists, and LCSC codes match the design.
    - X/Y sit at the footprint centre in the Gerber origin.
    - Rotation is solved against JLCPCB's EasyEDA footprint, so pad 1 lands on pin 1. JLCPCB rotates counter-clockwise, viewed from the top.
    - Not-assembled pads are excluded.
17. **Firmware vs hardware.**
    - GPIO numbers match the netlist, and input polarity matches the circuit.
    - Outputs have duty limits and timeouts, and a watchdog stops a hang from leaving one on.
    - Keying and transmit outputs arm only after every input has read idle since power-up, so a wrong switch position or a stuck input at power-up can't key anything.
    - The firmware reports the board version.
    - The build is reproducible, with toolchain and core versions recorded.

**Release (Gate 2)**

18. **Independent release review.** Fresh reviewers that haven't seen the reasoning, split by area: one checks every pin against datasheets, one rebuilds connectivity from the Gerbers and checks every CPL rotation. They write their own scripts rather than reusing the project's. Fixes re-run checks 11–17. Severity:
    - **BLOCKER:** the board won't work, could be damaged, or could damage what it plugs into. Must be fixed.
    - **SHOULD-FIX:** it works but is out of margin, unreliable or needlessly costly. Fix it, or justify it in the README.
    - **NOTE:** no action needed.
    - Every finding is closed with a fix or a written reason.
19. **Release record.** The README's verification record is complete, `CHECKSUMS.txt` matches the files in `order/`, and the release is tagged.
20. **Package check.** Unzip the final package and confirm the file names, the README steps and the checksums agree.
21. **On order day.** Re-check stock and price of every BOM line, and confirm JLCPCB's upload preview matches the renders.

## JLCPCB rules and part selection

Design to JLCPCB's standard 2-layer process with Economic assembly, all parts on top; anything outside these numbers needs a stated reason in the README.

| Rule | Project default | Why |
| --- | --- | --- |
| Layers, thickness, finish | 2 layers, 1.6 mm, 1 oz copper, HASL | Cheapest; HASL is fine for 0.5 mm-pitch USB-C |
| Trace / gap | 0.15 / 0.15 mm | Standard process |
| Vias | 0.3 mm drill / 0.6 mm pad | Standard process |
| Hole-to-hole, different nets | ≥ 0.5 mm edge to edge (design to 0.56) | Means ≥ 0.2 mm copper between via pads, including vias next to NPTH pegs |
| Copper to routed edge | ≥ 0.3 mm | JLCPCB guideline |
| Silkscreen | ink-jet; lines ≥ 0.15 mm; text ≥ 0.6 mm cap height in a bold font (Inter ExtraBold), 1.0 mm where there is room | JLCPCB asks for 0.8 mm; 0.6 mm bold text with 0.15 mm strokes is the project's floor. The adapter A test (Oct 2026, ink-jet) printed separate dots from 0.12 mm and merged 0.10 mm, so 0.15 mm strokes have margin. Polarity marks are shapes, not text. High-precision silkscreen costs 4× here |
| Assembly | Economic, top side only | Standard PCBA is $25 setup per side and forces a 70 × 70 mm panel with rails |

**Part selection**

- Check Economic eligibility when choosing a part, not at order time. Edge-mount and clamp USB-C plugs are often Standard-only (C530607 was; C52741990 replaced it).
- Prefer Basic parts. Each Extended part costs about $3. Not every common value is Basic: 27 Ω 0402 (C25100) is Extended, so use 22 Ω (C25092).
- Basic 0805 resistors are 1/8 W; a 1/4 W 0805 is Extended (C49308148, 47 Ω).
- Cache EasyEDA footprints (`eda_cache/`); the API sometimes returns 403.

**Layout**

- Treat every part body as a silkscreen obstacle, not just its pads, or labels end up under parts.
- Treat a through-hole pad as copper on both sides when packing parts and checking overlaps. A same-side check let an SMD capacitor sit on a back-side connector's plated pad (badge carrier, Oct 2026).
- When writing Gerber regions with holes (pours, silkscreen), draw them largest first. A hole is drawn in clear polarity and erases anything drawn before it inside the hole: on the badge carrier it wiped the text inside the holder outline, and would have wiped pour islands of other nets.
- Freerouting leaves fixed (pre-routed) wires and vias out of its session file, so add them back when importing the routing.
- Leave no room for, and ask JLCPCB not to add, order numbers or tooling holes inside small boards; plan for edge rails instead.
- Keep a readable hand-written source with datasheet pin names next to the generated files.

## Ordering

The README's ordering steps list only what differs from JLCPCB's defaults, per board, so a person can order without a back-and-forth.

1. **Upload** only that board's Gerber zip from `order/`. Confirm JLCPCB detects 2 layers and the expected size, which the README states. "Detected 0 layer" means nothing was read. Step through JLCPCB's layer preview and compare it with the renders.
2. **PCB options:** Remove Mark; colour and silkscreen technology as chosen; everything else default.
3. **PCB remark** (paste-ready in the README): name anything intentional that looks odd, such as bottom art, exposed copper or test patterns, and add: "Please do not add tooling holes, order numbers or marks inside the board outline."
4. **Assembly:** Economic, top side, qty 5 (minimum); Confirm parts placement: Yes; depanel and edge rails if cheap.
5. **Assembly remark:** call out intentional overhangs, for example a USB-C plug past the board edge, and repeat "rails outside the outline, no tooling holes inside".
6. **BOM/CPL:** upload that board's two CSVs; check every line is matched and quantities are right; in the placement preview, check polarised and edge parts.
7. **Record the order:** options chosen and the order and arrival dates go in `<project>/NOTES.md` against the version; order numbers and cost only if they are to hand.
8. **After paying:** watch email for a day. JLCPCB sends engineering questions before production, and the order waits for an answer.

Flag in the README any option that changes price a lot (ENIG, high-precision silkscreen) so the person can decide by clicking it.

## When the boards arrive

No board is plugged into anything valuable until it has passed inspection and a current-limited first power-up. Log the results per unit in `<project>/NOTES.md`.

- [ ] **Inspect** every unit against the assembly drawing to IPC-A-610 Class 2. Check polarised-part orientation, solder bridges on fine-pitch pins, tombstoned parts, and the silkscreen result, including any test pattern.
- [ ] **Unpowered meter checks:** no short between each rail and GND, plus the continuity paths the README lists.
- [ ] **First power on a current-limited supply,** set just above the expected idle current. Measure each rail and the idle current against the README's expected values, and stop on any mismatch.
- [ ] **Program and run the acceptance tests** from the requirements brief, on every unit, recording pass or fail.
- [ ] **Connect to the real target device** only after the above pass.
- [ ] **Close the loop:** update the errata and `NOTES.md`, and turn each lesson into a check or rule here.
