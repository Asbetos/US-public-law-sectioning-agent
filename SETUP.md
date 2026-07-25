# Setup — reproduce this pipeline (and its Claude Code agent) on a new server

This repo is the U.S. Statutes-at-Large **data-preprocessing pipeline** plus the
**Claude Code skills** (`cv-correct`, `cv-coder`, `cv-classifier`) that drive the
autonomous correction / labelling workflow. Following the steps below reproduces
the full setup so a Claude Code agent can run the exact same tasks elsewhere.

## 0. Prerequisites

- **Python 3.11** (the shared venv is CPython 3.11.6; `legacy-law-identity`
  requires `>=3.11`).
- **git**, and **Claude Code** installed for the operator.
- **Source data** (NOT in this repo — it is large and read-only):
  - `STATUTE-<N>.xml` — the USLM XML per volume (from GPO / govinfo.gov).
  - `Congress_Session_Dates.csv` — congress/session date table (read from the
    source dir by the enricher).
  - `AgencyList.xlsx` — agency/bureau lookup (seeded into `processed_output/`).
  On the original server these live in
  `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/`. On a new
  server, put them anywhere and pass `--source-xml-dir <dir>` (see step 5).

## 1. Clone both repos (side by side)

The pipeline imports the **`legacy-law-identity`** package (the legacy pLaw
identity resolver), which is a **separate repo** kept as a sibling directory:

```
<workspace>/
├── data-preprocessing-pipeline/     ← this repo
└── legacy-law-identity/             ← sibling package (its own repo)
```

```bash
git clone <this-repo-url> data-preprocessing-pipeline
git clone <legacy-law-identity-repo-url> legacy-law-identity
cd data-preprocessing-pipeline
```

## 2. venv + dependencies

```bash
python3.11 -m venv ../venv           # or: uv venv ../venv --python 3.11
../venv/bin/python -m pip install -r requirements.txt
../venv/bin/python -m pip install -e ../legacy-law-identity   # editable install
```

> Use `python -m pip` (never `venv/bin/pip` directly) in this project's venv.

Verify: `../venv/bin/python -c "import legacy_law_identity, lxml, pandas; print('ok')"`

## 3. Seed the local lookup files

The pipeline treats `processed_output/AgencyList.xlsx` and
`processed_output/DivisionMapping.xlsx` as the source of truth and never writes
back to the source dir. Seed them once:

```bash
../venv/bin/python seed_lookup_files.py --source-dir <source-data-dir>
```

(`DivisionMapping.xlsx` starts empty and grows as volumes are enriched.)

## 4. Install the Claude Code skills

The agent skills live in [`skills/`](skills) and must be visible to Claude Code
under `~/.claude/skills/`. Symlink them (the repo stays the source of truth):

```bash
mkdir -p ~/.claude/skills
for s in cv-correct cv-coder cv-classifier; do
  ln -sfn "$(pwd)/skills/$s" ~/.claude/skills/$s
done
```

`setup.sh` does steps 2–4 automatically.

## 5. Run the pipeline

```bash
# Deterministic pipeline (parse → segment → enrich → validate → publish)
../venv/bin/python run_pipeline.py --volumes 64-70 \
    --source-xml-dir <source-data-dir>

# Checkpoint before the correction stage (for the cv-correct agent workflow)
../venv/bin/python run_pipeline.py --volumes 64 --stop-before-publish \
    --source-xml-dir <source-data-dir>

# Apply approved (+ optionally pending) corrections and publish
../venv/bin/python apply_corrections_and_publish.py --volume 64 --include-pending
```

Outputs land in `processed_output/Volume-<N>/STATUTE-<N>_<timestamp>.xlsx`.
Only the **final** Excel per volume is version-controlled; scratch parquets,
download bundles, and per-session split sheets are gitignored/regenerable.

## 6. Run the agent tasks

With the skills installed (step 4), an operator drives the correction workflow
from a Claude Code session:

- **`/cv-correct <vols>`** — run the pipeline with autonomous per-volume
  correction review (dispatches an Opus subagent per volume, writes proposals to
  `pending_corrections.json` + a GPO issue log, then publishes).
- **`/cv-coder implement <id>`** — implement an approved `type: "other"`
  (code-level) correction via an Opus subagent with a failing-test-first gate.
- **`/cv-classifier <vol>`** — label a published volume with the SME questions.

Review/approve proposals with `approve_corrections.py list|show|approve|reject`.

See [CLAUDE.md](CLAUDE.md) for the agent's operating rules and
[PLAN.md](PLAN.md) for the full architecture.
