#!/usr/bin/env bash
# One-shot setup for the data-preprocessing-pipeline on a new server.
# See SETUP.md for the manual walkthrough and data prerequisites.
#
# Usage:
#   ./setup.sh [--venv <path>] [--source-dir <source-data-dir>] [--no-skills]
#
# Assumes this repo and the sibling `legacy-law-identity` repo are checked out
# side by side:  <workspace>/data-preprocessing-pipeline  and  <workspace>/legacy-law-identity
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/../venv"
SOURCE_DIR=""
DO_SKILLS=1

while [ $# -gt 0 ]; do
  case "$1" in
    --venv) VENV="$2"; shift 2;;
    --source-dir) SOURCE_DIR="$2"; shift 2;;
    --no-skills) DO_SKILLS=0; shift;;
    *) echo "unknown arg: $1"; exit 2;;
  esac
done

LEGACY="$HERE/../legacy-law-identity"
[ -d "$LEGACY" ] || { echo "ERROR: sibling package not found at $LEGACY (clone it next to this repo)"; exit 1; }

echo "==> venv at $VENV"
[ -d "$VENV" ] || python3.11 -m venv "$VENV"
PY="$VENV/bin/python"

echo "==> install pipeline dependencies"
"$PY" -m pip install -q -r "$HERE/requirements.txt"

echo "==> editable-install legacy-law-identity"
"$PY" -m pip install -q -e "$LEGACY"

"$PY" -c "import legacy_law_identity, lxml, pandas, openpyxl; print('    imports OK')"

if [ -n "$SOURCE_DIR" ]; then
  echo "==> seed lookup files from $SOURCE_DIR"
  "$PY" "$HERE/seed_lookup_files.py" --source-dir "$SOURCE_DIR" || true
else
  echo "==> (skipping lookup seed — pass --source-dir to seed AgencyList/DivisionMapping)"
fi

if [ "$DO_SKILLS" = 1 ]; then
  echo "==> install Claude Code skills into ~/.claude/skills (symlinks)"
  mkdir -p "$HOME/.claude/skills"
  for s in cv-correct cv-coder cv-classifier; do
    ln -sfn "$HERE/skills/$s" "$HOME/.claude/skills/$s"
    echo "    ~/.claude/skills/$s -> $HERE/skills/$s"
  done
fi

echo "==> running tests"
( cd "$HERE" && "$PY" -m pytest -q ) || echo "    (tests reported failures — review above)"

echo "==> done. See SETUP.md step 5 to run the pipeline."
