# Writing style

Applies to everything in this repo: READMEs, notes, changelogs, commit messages, tag messages, code comments, review reports, PR descriptions, design docs, how-to guides. Write like an engineer explaining something to a colleague who is busy, knows the field, and wants to get the job done.

## Voice

- **Talk to the reader.** Use "you" for the reader and "we" for the team. Contractions are fine ("it's", "don't"). The register is a knowledgeable colleague, not a manual and not a narrator.
- **Tell them how to do it.** Every sentence either tells the reader what to do, what they'll see, or why something fails. If a sentence does none of those, cut it.
- **Name things exactly.** Use the real query ID, table, column, flag, function signature or file path, formatted as code. "Run `search_ports` with `port` = `6379`", not "use the raw response query on the port".
- **Explain why only at a decision point.** Give the reason when it changes what the reader does: "Use `=` on `protocol_name`; `ilike` makes it slow." Skip the mechanism when the reader just follows the step.
- **Introduce every code block or output.** One sentence before it says what it is and what to look at.

## Registers

Two registers. The rules below apply to both; the sentence budget does not.

- **Short form:** code comments, commit messages, changelog lines, review findings, chat replies. One fact per sentence, 12 to 20 words. Cut anything that doesn't change what the reader does.
- **Long form:** design docs, PR descriptions, writeups, READMEs, how-to prose. Multi-clause declarative prose. Sentences carry a full thought with its consequence attached. Specificity is the authority: named functions, versions, measured figures. Don't strip a document to telegraphic fragments in the name of concision.

In long form, 12 to 20 words is a floor and not a target. Four consecutive sentences inside that budget almost always means you've written a drumbeat (rule 13).

## Rules

1. **Lead with the fact.** First sentence is the result, the decision, the number or the action. No preamble.
2. **No throat clearing.** Delete openers that announce what is coming: "This document outlines…", "In this section we will…", "Let's take a look at…", "It's worth noting that…", "It is important to…".
3. **No meta narrative.** Don't describe the writing, the process of writing it, or the agent that wrote it. "I carefully reviewed…", "After thorough analysis…", "As an AI…" all go. State what was checked and what was found.
4. **No story.** Don't walk the reader through a scenario ("Suppose you are writing…", "Taking X from those results…") when steps would do. Write how-tos as numbered steps that start with the action: "Run `search_checks` with `term` = `grafana`."
5. **No filler adjectives.** Cut "robust", "seamless", "comprehensive", "powerful", "elegant", "cutting-edge", "state-of-the-art", "best-in-class". If something is robust, say what it survives.
6. **Numbers that change a decision.** "Draws 60 mA" not "low power". Units always, SI with a space: `3.3 V`, `100 nF`, `0.5 mm`. Only include a number the reader acts on: "about 3 minutes per day of data, so keep `days` at 1" earns its place; a column of "under 1 s" runtimes from your own test run does not.
7. **No provenance or stale samples.** Don't report how you found something, how long your run took, or a dump of results the reader will regenerate. Show the input and what to look for in the output.
8. **Paste output verbatim.** Never retype, reflow or re-indent tool output and present it as a transcript. Show the command, then the real lines. If you drop lines, say which ("timestamps and empty fields cut") or mark the gap with `...`. A reflowed sample is worse than no sample, because it makes the reader distrust every other block.
9. **No hedging stacks.** One qualifier at most, and only when the uncertainty is real. If something is unverified, say so once and say how to verify it.
10. **No sales voice or cheerleading.** No "Great news!", "Exciting", "Happy to help", "Hope this helps", emoji, or exclamation marks.
11. **No summary of what was just said.** No "In summary", "In conclusion", "Key takeaways", "Overall". The end of a section is where its content stops.
12. **Plain words.** "use" not "leverage" or "utilize", "about" not "approximately", "check" not "validate the correctness of", "shows" not "surfaces", "find" not "establish". No "delve", "navigate", "landscape", "realm", "tapestry", "journey", "unlock", "empower", "harness", "elevate", "game-changer", "dive into", "repay reading", "worth a look".
13. **Vary the beat inside a paragraph.** Three or more consecutive sentences of similar length that open subject-verb read as generated, even when each one obeys rule 14. Attach a consequence to its cause instead of giving it a sentence of its own. Read the whole paragraph before you ship it: editing sentence by sentence is what produces the drumbeat, because every individual fix looks correct.
    - Bad: The cache keys on the file hash. It stores entries under `.cache/`. Entries never expire. A stale entry is possible. The build links the wrong object.
    - Good: The cache keys on the file hash and stores entries under `.cache/`. Nothing expires them, so a stale entry survives a rebuild and gets linked into the next binary.
14. **One fact per sentence, joined only when they belong together.** Don't weld unrelated facts with ", and" or chain clauses with "which makes it", "which means", "so that". Fragments are as bad as run-ons; both read as generated.
15. **Active voice.** Name who or what does the action: "the receiver reconciles the listing", not "the listing is reconciled".
16. **No contrast-reveal constructions.** Avoid "It's not just X, it's Y", "X isn't merely…", "Not only… but also…". Informative contrast is fine when it carries a fact: "Unlike `rsync`, it opens one connection for every worker."
17. **No rule-of-three padding.** List what exists, not three items because three sounds complete.
18. **Tables must serve the reader's task.** A table is for things the reader compares or looks up. Before keeping a column, ask what the reader does with it. Cut columns that record your process (runtimes, run dates) and tables of sample rows.
19. **Formatting carries structure, not emphasis.** Bullets for parallel items, numbered lists for steps, tables for things compared on the same attributes. Bold only for a term being defined or a label at the start of a bullet, and a label is a few words, not a whole sentence with a full stop. Don't put a heading over a single paragraph.
20. **Bullets for enumerable facts, prose for reasoning.** An ordered flow, a version list or a set of preconditions is a list. An argument never is.
21. **Say it once.** Don't restate a point in different words in two sections. Link to where it's already written.
22. **Headings are labels, not taglines.** A plain noun phrase in sentence case with no trailing punctuation: "Searching headers", "Version numbers". Avoid slogan shapes:
    - The comma-pause reveal: "Power, simplified."
    - A full stop at the end: "Built for the field."
    - A question or a pun: "Why a relay?", "Keying it simple"
    - A colon subtitle that restates the heading: "Bring-up: getting it alive"
23. **No conversational residue.** Files are read by people who weren't in the chat. No "You're right", "Good catch", "Fair point", "To be clear", "Say the word if you'd rather…". No colon setups that announce a point ("Here's the thing:"). State the fact.
24. **No dramatised framing.** Say what fails, when and how.
    - No cleft sentences for emphasis: "X is the one that…", "What matters here is…", "The catch is…", "That row is the precondition…", "A behavioral check is the only option."
    - No idioms in place of the mechanism: "bites", "gotcha", "footgun", "under the hood", "happily runs".
25. **No editorial intensifiers.** "genuine(ly)", "truly", "authoritative", "the crux", "worth noting", "matters most", "exactly where it should", "legible", "elegant". If a fact is significant, the fact shows it.
26. **No em dashes.** Not for asides, not for afterthoughts, and no spaced hyphen (" - ") standing in for one. Use a full stop, comma, colon or parentheses. En dashes are for numeric ranges only (`checks 1–6`).
27. **Editing someone else's text.** Keep their wording, spelling and grammar unless asked to change it. Fix only what you were asked to fix.

## Sample paragraphs

**An opening paragraph explains the whole thing.** Not a glossary, not a scope statement. A reader who stops here still knows what the thing is, what's hard about it, and what the answer is.

> `fastsync` copies a directory tree between two hosts over a single SSH connection. It exists because `rsync` opens one connection per worker, and a firewalled bastion refuses the fifth. The hard part is deletion: a file removed on the source generates no event to carry across, so the receiver has to work out what went missing from a listing it never asked for. `fastsync` ships a sorted manifest ahead of the data and diffs it on the receiver.

Four moves in four sentences: what it is, why it exists, the hard part named outright, and the answer.

**A mechanism paragraph names every actor.**

> The receiver reads the manifest into a sorted slice, then walks its own tree in the same order. Paths that exist locally and are absent from the manifest go into a delete batch, capped at 1000 entries so a truncated manifest can't empty a tree in one call. Everything else is compared on size and mtime, and the receiver requests only the files that differ.

**The drumbeat, before and after.** Both versions carry the same six facts.

> Bad: The probe sends two requests. The first uses a short value. The second uses a long value. A result is reported only when the first is refused. The second must be accepted. No session is opened.

> Good: The probe sends two requests on one connection, a short value then a long one. Both have to land the right way round, short refused and long accepted, so a server that answers yes to everything produces no result. It closes the connection before opening a session, which leaves one log line on the target and nothing else.

**The opposite failure, welded clauses.**

> Bad: The migration adds the `tenant_id` column and backfills it from the `accounts` table, which means the table is locked for the duration, and this is why it should run during a maintenance window.

> Good: The migration adds `tenant_id` and backfills it from `accounts`. The backfill holds an `ACCESS EXCLUSIVE` lock for about 40 s per million rows, so run it in a maintenance window.

**Preconditions are a list, not a sentence.**

> A host is exploitable when all of these hold:
> - The daemon is built without PAM.
> - `PasswordAuthentication` is yes, which is the default.
> - Some account has `*` as its password field.
> - Some other account has a `$5$` or `$6$` hash.

**A how-to is numbered steps with exact inputs and what to look for.**

> If you can't update yet, turn password logins off:
> 1. Test your key login and keep the current session open.
> 2. Write `PasswordAuthentication no` to `/etc/ssh/sshd_config.d/00-no-passwords.conf`.
> 3. Run `sshd -t && service sshd restart`, then `sshd -T | grep -i passwordauthentication`. It prints `passwordauthentication no`.

**A known-limitation bullet states the limit, the consequence and what it would take to lift it.**

> - **Account names.** No remote probe can enumerate an account whose field is `*`, so a vulnerable host whose only such account carries a site-specific name goes undetected. Adding candidates costs a connection each, and the third failed connection in a row starts hitting rate limits.

## Specific formats

- **Commit messages:** imperative subject under 72 characters, prefixed with project and version where relevant: `paddle-keyer v1.0.1: move R11 to 1/4 W 0805`. The body says what changed and why. No "This commit…".
- **Code comments:** say why, not what. Delete any comment that restates the code.
- **PR descriptions:** long form. What the change does and the mechanism, then how it was tested with real output, then the limitations you already know about. Every paragraph exists to tell a reviewer what to check or what to challenge.
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
| It does a full-text search over every response body the crawlers have saved, and a 7-day search usually comes back in a few seconds. | `search_bodies` searches the response bodies the crawler saved. |
| The crawler records everything it observes in the Postgres instance exposed through the BI tool, which makes it the practical way to find live hosts. | The crawler writes everything it sees to the `crawl` database, so that's the easiest place to find live hosts. |
| Suppose you are adding a version check for Grafana. Running `search_checks` with term = grafana establishes what already exists. | 1. Check for an existing check: run `search_checks` with `term` = `grafana`. |
| The 91 unidentified hosts are the ones that repay reading, and `decode_banner` shows what they actually sent. | Run `decode_banner` with `port` = `6379` to see what the unidentified hosts sent. |
| That last row is the precondition to check before scanning. | Check the port shows `http`. The HTTP checks don't run on other ports. |
| This query cost 187 s for a single day of data. | It's slow, about 3 minutes per day of data. Keep `days` at 1. |
| (table column) Runtime: under 1 s, under 1 s, under 1 s… | (delete the column; mention slowness only where it changes what you do) |
| The probe sends two requests. The first is short. The second is long. Only the pair counts. | The probe sends two requests on one connection, short then long, and only the pair counts: short refused, long accepted. |
