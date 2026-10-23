# Writing style

Applies to everything in this repo: READMEs, notes, changelogs, commit messages, tag messages, code comments, review reports. Write like an engineer writing for another engineer who is busy and knows the field.

## Rules

1. **Lead with the fact.** First sentence is the result, the decision or the number. No preamble.
2. **No throat clearing.** Delete openers that announce what is coming: "This document outlines…", "In this section we will…", "Let's take a look at…", "It's worth noting that…", "It is important to…".
3. **No meta narrative.** Don't describe the writing, the process of writing it, or the agent that wrote it. "I carefully reviewed…", "After thorough analysis…", "As an AI…" all go. State what was checked and what was found.
4. **No filler adjectives.** Cut "robust", "seamless", "comprehensive", "powerful", "elegant", "cutting-edge", "state-of-the-art", "best-in-class". If something is robust, say what it survives.
5. **Numbers over adjectives.** "Draws 60 mA" not "low power". "0.15 mm gap" not "tight clearance". Units always, SI with a space: `3.3 V`, `100 nF`, `0.5 mm`.
6. **No hedging stacks.** One qualifier at most, and only when the uncertainty is real. If something is unverified, say so once and say how to verify it.
7. **No sales voice or cheerleading.** No "Great news!", "Exciting", "Happy to help", "Hope this helps", emoji, or exclamation marks.
8. **No summary of what was just said.** No "In summary", "In conclusion", "Key takeaways", "Overall". The end of a section is where its content stops.
9. **Plain words.** "use" not "leverage" or "utilize", "about" not "approximately" in prose, "check" not "validate the correctness of". No "delve", "navigate", "landscape", "realm", "tapestry", "journey", "unlock", "empower", "harness", "elevate", "game-changer", "dive into".
10. **No contrast-reveal constructions.** Avoid "It's not just X, it's Y", "X isn't merely…", "Not only… but also…".
11. **No rule-of-three padding.** Don't list three items because three sounds complete. List what exists.
12. **Short sentences, active voice.** Name who or what does the action: "JLCPCB rotates the footprint counter-clockwise", not "the footprint is rotated".
13. **Formatting carries structure, not emphasis.** Use bullets for parallel items and tables for things compared on the same attributes. Use bold only for a term being defined or a label at the start of a bullet. Don't put a heading over a single paragraph.
14. **Say it once.** Don't restate a point in different words. Link to where it's already written.
15. **Headings are labels, not taglines.** A heading names what the section contains, as a plain noun phrase in sentence case with no trailing punctuation: "True power measurement", "Bring-up", "Version numbers". Avoid slogan shapes:
    - The comma-pause reveal: "True power, visualised." or "Power, simplified."
    - A full stop at the end: "Built for the field."
    - A question or a pun: "Why a relay?", "Keying it simple"
    - A colon subtitle that restates the heading: "Bring-up: getting it alive"
16. **No conversational residue.** Files are read by people who weren't in the chat. No agreement, apology or acknowledgement: "You're right", "Good catch", "Fair point", "To be clear", "I should be clearer". No colon setups that announce a point before making it ("Here's the thing:", "The short answer:"). State the corrected fact.
17. **No dramatised framing.** Say what fails, when and how, as a plain statement.
    - No cleft sentences used for emphasis: "X is the one that…", "What matters here is…", "The catch is…".
    - No idioms in place of the mechanism: "bites", "gotcha", "footgun", "the real killer", "under the hood", "the secret sauce".
18. **No em dashes.** Not for asides, not for afterthoughts, and no spaced hyphen (" - ") standing in for one. End the sentence and start a new one, or use a comma, colon or parentheses. En dashes are for numeric ranges only (`checks 1–6`, `21–22 Oct`).

## Specific formats

- **Commit messages:** imperative subject under 72 characters, prefixed with project and version where relevant: `paddle-keyer v1.0.1: move R11 to 1/4 W 0805`. The body says what changed and why. No "This commit…".
- **Code comments:** say why, not what. Delete any comment that restates the code.
- **Review findings:** `SEVERITY: what is wrong, where, evidence, fix`. One finding per item. Omit "Overall the design looks good".
- **Changelog entries:** one line per change, past tense is fine, with the reason after a semicolon or in parentheses.
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
