# Drawing standard for `pcb drawing`

The house style for planning drawings, taken from the badge carrier's placement proposal (NNDC27-CAR-PLC-001, rev 0.2.0, drawn by `design/placement/draw.py`, 29 Oct 2026). `pcb drawing` writes every planning-phase drawing in this style from the board and `pcb.toml`, so no project writes its own drawing script again.

## When it is made

- **Placement proposal**, before Gate 1: `pcb drawing placement` after `pcb place`. Status PROPOSAL.
- **Revised after review**: the same command with the new revision. The previous PDF stays in git history.
- **For release**: the same sheets with status RELEASED, plus the assembly page and fit print from `pcb release`.

## Sheet

- **Size:** A3 landscape, 420 × 297 mm. The PDF is vector and true to scale. Each sheet also gets a 150 dpi PNG preview.
- **Frame:** outer border 10 mm from the trim (0.7 mm line), inner border 5 mm inside it (0.35 mm). Zone markers 1–8 along the top and bottom, A–D down both sides, in the 5 mm band.
- **Title block:** 180 × 56 mm at the lower right, inside the inner frame. Each cell has a small grey label (4.2 pt) and a value. The rows, top to bottom:
  1. TITLE (9.5 pt bold);
  2. PROJECT, followed by the sheet's subject in brackets;
  3. DOCUMENT NO., REV (bold), STATUS (bold: PROPOSAL, REVIEWED or RELEASED), SHEET "n OF N";
  4. SCALE ("1:1 AT A3"), UNITS (MILLIMETRES), DATE (ISO), SIZE (A3);
  5. DRAWN ("Claude (AI)"), CHECKED (the gate and its state), APPROVED (owner);
  6. TOLERANCES UNLESS STATED, and PROJECTION with the third-angle symbol.
- **Fonts:** DejaVu Sans; notes and tables in DejaVu Sans Mono. ASCII only in the table; any other characters are replaced.

## Content

| Sheet | Holds |
| --- | --- |
| 1 Top view, scale 1:1 | Board outline; every footprint with pads, courtyard, pin-1 mark and designator; mating parts, modules and panels dashed; keep-outs hatched and labelled; mounting holes with keep-out rings; overall dimensions; ordinate dimensions from datum A along both axes; leader notes for every placement decision; legend; numbered notes |
| 2 Bottom view, seen from below (mirrored), scale 1:1 | Back-side parts and top-side through-hole leads (grey); hand-fitted parts; keep-outs; datum A shown at the mirrored corner; a section through the tallest stack, vertical scale stated |
| 3 Placement table | REF, X, Y, ROT, SIDE, LCSC, MPN for every part, top-view coordinates from datum A at the footprint origin, rotation counter-clockwise. Two full-height columns, then columns that stop above the title block |

- **Datum A** is the lower-left corner of the top view, at (0, 0). Every dimension is in mm from it.
- **Ordinates** are spread so that labels never overlap, with a minimum gap between them.
- **Leaders** carry the reason as well as the fact, in capitals: "J102 USB-C, POWER BANK IN; CL X 12.00, MOUTH FLUSH WITH TOP EDGE".
- **Notes** are numbered. They state the status, the datum and units, the board stack-up and workmanship class, the assembly sides (SMT top, hand-fitted parts listed), the sources of module data, what to confirm with parts in hand, and where the full results are.

## Colours and lines (mm on paper)

| Item | Colour | Line |
| --- | --- | --- |
| Ink, frame, outline | #111111 | outline 0.5, frame 0.5 |
| Copper pads | #c8792b, edge #8a4f17 | part 0.18 |
| Courtyards | #b03aa8 | 0.12 |
| Mating parts, modules | #1b5fb4, dashed | 0.3 |
| Keep-outs | #d23c3c, hatched //// | 0.15 |
| Dimensions | #005f60 | 0.15 |
| Silkscreen marks | #2a2a2a | thin 0.12 |

## Inputs

- **The board:** footprints, pads, courtyards, holes and outline.
- **`pcb.toml [drawing]`:** document number, title, tolerances, checked and approved by, and the notes.
- **`pcb.toml [[drawing.leader]]`:** a part or point, the text, and the side to place it on.
- **`pcb.toml [[drawing.outline]]`:** mating parts and modules, each as a rect or polygon with a label and line style.
- **`pcb.toml [[keepout]]`:** reused from the zone rules.
- **`[drawing.section]`:** the stack-up section, as layers with thicknesses and labels.

A drawing never holds a fact that is not in the board or `pcb.toml`, so it cannot disagree with them.

## Checks

- **Dimensions agree with the board:** every ordinate value equals the coordinate of a feature on it.
- **Placement table matches:** the table equals `pcb` CPL output for the same board.
- **No overlapping text:** checked on the rendered page by bounding boxes.
- **True scale:** the frame measures 420 × 297 mm in the PDF.
- **Fixture:** the badge placement drawing is regenerated and compared, sheet by sheet, against the 0.2.0 PDF. Expected differences are listed in the test.
