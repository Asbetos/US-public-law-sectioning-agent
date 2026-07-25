# CLAUDE.md — operating rules for the Claude Code agent on this pipeline

This repo parses U.S. Statutes-at-Large USLM XML into per-volume Excels, applies
static + agent-discovered corrections, and logs source-XML issues for GPO. See
[SETUP.md](SETUP.md) to install and [PLAN.md](PLAN.md) for the architecture.

## Environment
- Use the project venv. Install/manage packages with **`python -m pip`**, never
  `venv/bin/pip` directly.
- The pipeline depends on the sibling **`legacy-law-identity`** package
  (editable-installed). If imports fail, re-run `pip install -e ../legacy-law-identity`.

## Hard rules (do not violate)
1. **The source XML dir is READ-ONLY.** Never write anywhere under the
   `--source-xml-dir` (on the original server `/groups/brooksgrp/...`). The
   publisher refuses paths under that prefix — if a step trips this, surface it,
   don't work around it.
2. **Publisher hard-freeze.** Published Excels are frozen. Do **not** pass
   `--force-republish` (or `--force` re-runs that overwrite output) on your own
   initiative — get explicit operator consent first.
3. **Correction subagents run on Opus.** When dispatching `cv-correct` or
   `cv-coder` subagents, always pass `model: opus`. Their judgement (is an
   anomaly a real misnumbering or a legitimate gap?) needs the strongest model —
   a false positive mutates a published legal dataset.
4. **Propose-only.** Agent-discovered corrections go to `pending_corrections.json`
   and require human approval (`approve_corrections.py approve <id>`) before they
   enter the active rule set. `--include-pending` applies them to a publish
   in-memory without committing them to active.

## Pipeline
```
parse → segment → enrich → validate → publish
```
- `run_pipeline.py --volumes <spec> [--stop-before-publish] [--source-xml-dir D]`
  — `--volumes` takes a list/range (`64-70`, `44,45`); `--force` re-runs a
  volume the manifest considers current (needed after removing its output).
- `apply_corrections_and_publish.py --volume N [--include-pending] [--force-republish]`
  — publishes from the stop-before-publish checkpoint.
- `approve_corrections.py list|show|approve|reject` — manage the correction queue.

## Skills (in `skills/`, symlinked into `~/.claude/skills/`)
- **cv-correct** — run the pipeline with per-volume correction review (prefilter
  → Opus subagent → record proposals + GPO log → publish). Batch helpers:
  `scripts/build_subagent_prompt.py`, `scripts/merge_slices.py`.
- **cv-coder** — implement an approved `type: "other"` code-level correction
  (failing regression test first, then the full pytest gate).
- **cv-classifier** — label a published volume with the SME coding questions.

## Legacy vs modern volumes
- **Vol ≤ 64** = legacy USLM: public-law number from the `<sidenote>`; adds
  `VolumeNumber/Congress/Session` columns + an 11-segment UniqueKey.
- **Vol > 64** = modern USLM: law id from `<citableAs>`; 26-column schema.
- Congress/Session for legacy volumes are anchored to the law's own congress
  (from the LawIdentifier) so an overlapping session-boundary date can't
  misassign it.

## Before claiming done
Run the tests: `python -m pytest -q`. Verify published output (row counts,
distinct-law counts, no illegitimate UniqueKey collisions) before reporting.
