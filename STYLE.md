# Writing style

Applies to everything in this repo: READMEs, notes, changelogs, commit messages, tag messages, code comments, review reports, how-to guides. Write like an engineer explaining something to a colleague who is busy, knows the field, and wants to get the job done.

## Voice

- **Talk to the reader.** Use "you" for the reader and "we" for the team. Contractions are fine ("it's", "don't"). The register is a knowledgeable colleague, not a manual and not a narrator.
- **Tell them how to do it.** Every sentence either tells the reader what to do, what they'll see, or why something fails. If a sentence does none of those, cut it.
- **Name things exactly.** Use the real query ID, table, column, flag, function signature or file path, formatted as code. "Run 22646 with `port` = `6379`", not "use the raw response query on the port".
- **Explain why only at a decision point.** Give the reason when it changes what the reader does: "Use `=` on `protocol_name`; `ilike` makes it slow." Skip the mechanism when the reader just follows the step.
- **Introduce every code block or output.** One sentence before it says what it is and what to look at.

## Rules

1. **Lead with the fact.** First sentence is the result, the decision, the number or the action. No preamble.
2. **No throat clearing.** Delete openers that announce what is coming: "This document outlines…", "In this section we will…", "Let's take a look at…", "It's worth noting that…", "It is important to…".
3. **No meta narrative.** Don't describe the writing, the process of writing it, or the agent that wrote it. "I carefully reviewed…", "After thorough analysis…", "As an AI…" all go. State what was checked and what was found.
4. **No story.** Don't walk the reader through a scenario ("Suppose you are writing…", "Taking X from those results…") when steps would do. Write how-tos as numbered steps that start with the action: "Run 22641 with `search` = `grafana`."
5. **No filler adjectives.** Cut "robust", "seamless", "comprehensive", "powerful", "elegant", "cutting-edge", "state-of-the-art", "best-in-class". If something is robust, say what it survives.
6. **Numbers that change a decision.** "Draws 60 mA" not "low power". Units always, SI with a space: `3.3 V`, `100 nF`, `0.5 mm`. Only include a number the reader acts on: "about 3 minutes per day of data, so keep `days` at 1" earns its place; a column of "under 1 s" runtimes from your own test run does not.
7. **No provenance or stale samples.** Don't report how you found something, how long your run took, or a dump of results the reader will regenerate. Show the input and what to look for in the output.
8. **No hedging stacks.** One qualifier at most, and only when the uncertainty is real. If something is unverified, say so once and say how to verify it.
9. **No sales voice or cheerleading.** No "Great news!", "Exciting", "Happy to help", "Hope this helps", emoji, or exclamation marks.
10. **No summary of what was just said.** No "In summary", "In conclusion", "Key takeaways", "Overall". The end of a section is where its content stops.
11. **Plain words.** "use" not "leverage" or "utilize", "about" not "approximately", "check" not "validate the correctness of", "shows" not "surfaces", "find" not "establish". No "delve", "navigate", "landscape", "realm", "tapestry", "journey", "unlock", "empower", "harness", "elevate", "game-changer", "dive into", "repay reading", "worth a look".
12. **One fact per sentence, joined only when they belong together.** Don't weld unrelated facts with ", and" or chain clauses with "which makes it", "which means", "so that". Aim for 12 to 20 words. Fragments are as bad as run-ons; both read as generated.
13. **Active voice.** Name who or what does the action: "JLCPCB rotates the footprint counter-clockwise", not "the footprint is rotated".
14. **No contrast-reveal constructions.** Avoid "It's not just X, it's Y", "X isn't merely…", "Not only… but also…".
15. **No rule-of-three padding.** List what exists, not three items because three sounds complete.
16. **Tables must serve the reader's task.** A table is for things the reader compares or looks up. Before keeping a column, ask what the reader does with it. Cut columns that record your process (runtimes, run dates) and tables of sample rows.
17. **Formatting carries structure, not emphasis.** Bullets for parallel items, numbered lists for steps, tables for things compared on the same attributes. Bold only for a term being defined or a label at the start of a bullet. Don't put a heading over a single paragraph.
18. **Say it once.** Don't restate a point in different words. Link to where it's already written.
19. **Headings are labels, not taglines.** A plain noun phrase in sentence case with no trailing punctuation: "Searching headers", "Version numbers". Avoid slogan shapes:
    - The comma-pause reveal: "Power, simplified."
    - A full stop at the end: "Built for the field."
    - A question or a pun: "Why a relay?", "Keying it simple"
    - A colon subtitle that restates the heading: "Bring-up: getting it alive"
20. **No conversational residue.** Files are read by people who weren't in the chat. No "You're right", "Good catch", "Fair point", "To be clear". No colon setups that announce a point ("Here's the thing:", "The two parameters do different jobs."). State the fact.
21. **No dramatised framing.** Say what fails, when and how.
    - No cleft sentences for emphasis: "X is the one that…", "What matters here is…", "The catch is…", "That row is the precondition…".
    - No idioms in place of the mechanism: "bites", "gotcha", "footgun", "under the hood", "happily runs".
22. **No em dashes.** Not for asides, not for afterthoughts, and no spaced hyphen (" - ") standing in for one. Use a full stop, comma, colon or parentheses. En dashes are for numeric ranges only (`checks 1–6`).
23. **Editing someone else's text.** Keep their wording, spelling and grammar unless asked to change it. Fix only what you were asked to fix.

## Specific formats

- **Commit messages:** imperative subject under 72 characters, prefixed with project and version where relevant: `paddle-keyer v1.0.1: move R11 to 1/4 W 0805`. The body says what changed and why. No "This commit…".
- **Code comments:** say why, not what. Delete any comment that restates the code.
- **Review findings:** `SEVERITY: what is wrong, where, evidence, fix`. One finding per item. Omit "Overall the design looks good".
- **Changelog entries:** one line per change, past tense is fine, with the reason after a semicolon or in parentheses.
- **How-to guides:** one sentence on what the thing is for, then numbered steps. Each step: the action, the exact inputs, what to look for. Put caveats on the step they affect.
- **Waivers and assumptions:** state the deviation, why it is acceptable, and what would make it unacceptable.

## Examples

| Don't | Do |
| --- | --- |
| This README provides a comprehensive overview of the paddle keyer project. | RP2040 USB keyer for VBand and Vail, with relay passthrough to the radio. |
| After carefully analyzing the Gerbers, I'm pleased to report that no issues were found. | Gerber connectivity: 0 opens, 0 shorts, 41/41 pads connected. |
| It's important to note that the 27 Ω resistor is an Extended part, which could potentially increase costs. | 27 Ω 0402 (C25100) is Extended (about $3 fee); used 22 Ω (C25092, Basic). |
| This robust design seamlessly handles power-bank operation. | Runs from a power bank. Some banks switch off below about 70 mA. |
| In summary, the board is ready for ordering. | (delete) |
| ## True power, visualised. | ## True power display |
| You're right, and I should be clearer: the relay is needed. | The relay is needed: without 5 V it connects the paddle straight to D+/D−. |
| The race variant is the one that bites, and it needs concurrency to show up. | The race variant fails only when two tasks write the buffer at once. |
| Gerbers pass DFM — though the silk is tight — and the fish is fine. | Gerbers pass DFM. Silk clearance is 0.16 mm against a 0.15 mm limit. |
| Fix stuff | paddle-keyer v0.0.2: add 1 s watchdog; a hang could leave PTT keyed |
| It does a full-text search over every HTTP response body that AVID-0000503 and AVID-0000504 have saved, and a 7-day search usually comes back in a few seconds. | 22641 searches the page bodies saved by AVID-0000503 and AVID-0000504. |
| ADVANS records everything its scanners observe in the advans-prod Postgres database exposed through ais-redash, which makes it the practical way to find live hosts. | ADVANS stores everything its scanners see in the `advans-prod` database on ais-redash, so it's the easiest place to find live hosts. |
| Suppose you are writing a Grafana version plugin. Running 22650 with term = grafana establishes what already exists. | 1. Check for an existing plugin: run 22650 with `term` = `grafana`. |
| The 91 unidentified hosts are the ones that repay reading, and 22646 decodes what they actually sent. | Run 22646 with `port` = `6379` to see what the unidentified hosts sent. |
| That last row is the precondition to check before scanning. | Check the port shows `http`. HTTP plugins don't run on other ports. |
| This query cost 187 s for a single day of data. | It's slow, about 3 minutes per day of data. Keep `days` at 1. |
| (table column) Runtime: under 1 s, under 1 s, under 1 s… | (delete the column; mention slowness only where it changes what you do) |
