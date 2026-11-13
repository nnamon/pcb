# AGENTS.md

Instructions for any agent working in this repository. It holds the `pcb` tool and the standards (`GUIDELINES.md`, `STYLE.md`) that every board project follows. Board projects live in their own repositories.

## Before you start

1. Read `STYLE.md`. Everything written here, including commit messages and review reports, follows it.
2. Read `DESIGN.md` for the part of the tool you are changing, and `tests/README.md`.
3. Run `pcb doctor`.

## Hard rules

- **Test before pushing.** Run `cargo xtask test` in the pinned image (`ci/`) after any change to the tool, and push only when it passes. There is no CI test run: GitHub Actions minutes are paid, and the local run is the check (owner, 5 Nov 2026). Run clippy with `-D warnings` on a host that has it.
- **Source and case.** A new check names the board fault it came from, and has a case in `tests/cases/` that fails without it.
- **Output contract.** A change to a command's output changes `schemas/<command>.json`; a new error or warning code gets a row in `docs/codes.md`.
- **Independent review.** A milestone's checks are reviewed by a fresh agent given the files and the claims, not the reasoning. Save the report as written in `docs/reviews/`, with closures beneath it.
- **`GUIDELINES.md` changes.** Tell the owner of every change to `GUIDELINES.md`, so the mirrors (the claude.ai project "PCB Designs" and the Claude doc "PCB Project Guidelines") are synced.
- **Versions.** `Cargo.toml` carries the version; projects pin MAJOR.MINOR, so a change that makes a passing board fail, or changes a file `pcb release` writes, is a new MINOR. Record each version in `TAGS.tsv` (tag `v<x.y.z>`, commit, message) and never edit or remove a line.

## Git

- Commit messages start with `pcb` and the version: `pcb 0.5.1: read the edge clearance from custom rules`.
- Work on a branch; merge to `main` when the tests pass. Never force-push `main` and never move or delete a tag.
- Do not commit `target/` or `pcb_work/`. Keep single files under 50 MB.
