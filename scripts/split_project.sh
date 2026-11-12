#!/bin/sh
# Split one project out of claude-pcb into its own repository, history kept (DESIGN.md, "Repository split").
# usage: split_project.sh SOURCE_REPO PROJECT_FOLDER NEW_NAME OUT_DIR
# Makes OUT_DIR/NEW_NAME: the project's folder as the repository root, every commit that touched it, and a
# TAGS.tsv whose tags are v<x.y.z> (fw-v<x.y.z>) on the rewritten commits. Nothing is pushed.
set -eu
src=$(cd "$1" && pwd); proj=$2; name=$3; out=$4
mkdir -p "$out"; dest="$out/$name"
[ ! -e "$dest" ] || { echo "$dest exists" >&2; exit 1; }
git clone -q --no-local --single-branch --branch main "$src" "$dest"
cd "$dest"
git filter-repo --quiet --subdirectory-filter "$proj"
map=.git/filter-repo/commit-map
{
  echo "# One line per version: tag, commit, then the tag message (tab-separated)."
  echo "# Split from claude-pcb on $(date +%Y-%m-%d): tags were $proj-v<x.y.z> there, on the commits its TAGS.tsv names."
  echo "# The \"Tag and release\" workflow (run by hand) creates each missing tag and its GitHub release. Never edit or remove a line."
  git -C "$src" show main:TAGS.tsv | grep -v '^#' | while IFS="$(printf '\t')" read -r tag sha msg; do
    case "$tag" in "$proj"-fw-v*|"$proj"-v*) ;; *) continue ;; esac
    # the last commit at or before the tagged one that touched the project
    last=$(git -C "$src" log -1 --format=%H "$sha" -- "$proj")
    new=$(awk -v o="$last" '$1 == o { print $2 }' "$map")
    case "$new" in ""|0000000000000000000000000000000000000000) echo "no rewritten commit for $tag ($sha)" >&2; exit 1 ;; esac
    # the tree must be the project's folder at the tagged commit, byte for byte
    [ "$(git rev-parse "$new^{tree}")" = "$(git -C "$src" rev-parse "$sha:$proj")" ] || { echo "$tag: tree differs after the split" >&2; exit 1; }
    printf '%s\t%s\t%s\n' "${tag#"$proj"-}" "$new" "$msg"
  done
} > TAGS.tsv
# what a repository of its own needs: agent instructions, ignore rules, the release workflow (pcb new's own)
tmp=$(mktemp -d); "${PCB:-pcb}" new "$name" --dir "$tmp/p" > /dev/null
mkdir -p .github/workflows
cp "$tmp/p/.github/workflows/tag-and-release.yml" .github/workflows/
cp "$tmp/p/.gitignore" "$tmp/p/CLAUDE.md" .
rm -rf "$tmp"
cat > AGENTS.md <<AGENTS
# AGENTS.md

Instructions for any agent working in this repository. It holds one PCB project, $name, made and assembled by JLCPCB. It was split from the repository claude-pcb on $(date +%Y-%m-%d), where it was the folder \`$proj/\`; its history came with it.

## Before you start

1. Read \`GUIDELINES.md\` and \`STYLE.md\` in the \`pcb\` repository. They are binding: the process gates, the checks before ordering, naming, JLCPCB rules, bring-up, and how to write.
2. Read \`README.md\` and \`NOTES.md\` here. \`NOTES.md\` holds status per version, order records, bring-up results and lessons.
3. Install \`pcb\` (repository \`pcb\`) and run \`pcb doctor\` before any board work.

## Layout

This project predates \`pcb new\` and keeps the layout it was made with: \`order/\` (exactly what was sent to JLCPCB), \`docs/\`, \`renders/\`, \`source/\`, \`design/\` (reviews, scripts and, where the project has one, \`design/pcb/pcb.toml\`), \`firmware/\`. A new MAJOR version may move to the layout \`pcb new\` writes; an ordered version's files never move.

## Hard rules

- Never order, or say the board is ready to order, until every check in GUIDELINES has passed or carries a written waiver in the README.
- The Gerbers are the truth. After any change to exported files, read them back again.
- Gate 1 and Gate 2 reviewers are fresh agents given the files and the checks they own, not the design reasoning. Save their findings as written.
- Any change to \`order/\` bumps the version. An ordered version is frozen; the next change starts the next MAJOR.
- Check JLCPCB data; do not assume stock, Basic or Extended, or Economic eligibility.
- Mains, Li-ion charging, high current and RF transmit paths need review by a qualified person. Say so.

## Git

- Commit messages start with the version: \`v1.0.1: widen R11 trace for 150 mA\`.
- Tags are \`v<x.y.z>\` (firmware \`fw-v<x.y.z>\`), annotated, recorded in \`TAGS.tsv\`, never moved or deleted. In claude-pcb they were \`$proj-v<x.y.z>\`; documents written before the split use those names and claude-pcb's commit hashes.
- Work on a branch; merge to \`main\` when the stage's gate passes. Never force-push \`main\`.
AGENTS
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-Claude}" -c user.email="${GIT_AUTHOR_EMAIL:-noreply@anthropic.com}" commit -q -m "Split from claude-pcb: $proj becomes the repository $name

History kept: every commit that touched $proj/, with that folder as the
root. TAGS.tsv lists each version on its rewritten commit, as v<x.y.z>;
each tagged tree was compared with claude-pcb's and is identical.
${TRAILER:-}"
echo "$name: $(git rev-list --count HEAD) commits, $(grep -vc '^#' TAGS.tsv) tags"
