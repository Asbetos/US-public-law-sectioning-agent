---
name: cv-correct
description: Run the citizen_voice statutes pipeline with autonomous XML-correction review. For each volume, runs the deterministic pipeline through validation, invokes a per-volume Claude Code subagent to identify OCR / parsing quirks, writes the subagent's proposals to a pending queue + a GPO-bound issue log, then publishes the volume's Excel. Use when the operator says "run the citizen_voice pipeline with corrections", "process vols X-Y with corrections", or invokes `/cv-correct`.
---

# cv-correct — Citizen Voice statutes pipeline with autonomous correction review

This skill orchestrates the citizen_voice statutes pipeline with an inline
XML-correction agent step. The agent runs as a Claude Code subagent (one per
volume), proposes corrections to a pending queue, and the deterministic
pipeline publishes the volume's Excel afterwards. Authority is **propose-only**
— proposals require human approval via `approve_corrections.py` before they
enter the active rule set used for future first-time runs. Published Excels
are **hard-frozen** — they are never modified after the fact.

Full architecture in `/home/G39248410/.claude/plans/lively-orbiting-forest.md`.

## When to invoke

The operator asks for any of:
- "run the citizen_voice pipeline on vols X-Y with corrections"
- "review the pipeline output for corrections"
- "/cv-correct <vols>"
- "process vols X-Y through cv-correct"

If the operator says "run the pipeline" without "with corrections", call
`run_pipeline.py` directly — do not invoke this skill.

## Paths (resolve once at start of the workflow)

| Var | Default |
|---|---|
| `PIPELINE_DIR` | `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline` |
| `VENV_PYTHON` | `/home/G39248410/citizen_voice/venv/bin/python` |
| `OUTPUT_DIR` | `${PIPELINE_DIR}/processed_output` |
| `SCRATCH_DIR` | `${OUTPUT_DIR}/scratch` |
| `XML_DIR` | `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06` (read-only) |
| `SKILL_DIR` | `~/.claude/skills/cv-correct` |

## Per-volume workflow

Run these five steps for each volume `N` the operator requested. If any step
returns a non-zero exit code, log the failure but continue to the next volume
— a single bad volume should not halt the batch.

### Step 1 — Run stages 1-5 (parse → segment → enrich → validate)

```bash
${VENV_PYTHON} ${PIPELINE_DIR}/run_pipeline.py \
  --volumes N --stop-before-publish [--force]
```

Add `--force` if the operator explicitly asked to re-process an already-published
volume *and* they have removed the existing Volume-N output dir + manifest
entry. By default, omit `--force`. On success, the runner writes:
- `${SCRATCH_DIR}/enriched_N.parquet`
- `${SCRATCH_DIR}/validation_report_N.json`

If the runner reports `validate_failed`, skip the subagent step (no point
asking it to fix data the validator already rejects); jump to step 5 (publish)
without corrections so a human can investigate.

### Step 2 — Pre-filter to candidate rows

```bash
${VENV_PYTHON} ${SKILL_DIR}/prefilter.py \
  --enriched ${SCRATCH_DIR}/enriched_N.parquet \
  --validation-report ${SCRATCH_DIR}/validation_report_N.json \
  --active ${OUTPUT_DIR}/active_corrections.json \
  --pending ${OUTPUT_DIR}/pending_corrections.json \
  --xml ${XML_DIR}/STATUTE-N.xml \
  --out ${SCRATCH_DIR}/candidates_N.json
```

Writes `candidates_N.json`. If the file's `candidates` array is empty,
**skip step 3** (no point dispatching a subagent with nothing to review).

### Step 3 — Dispatch the correction subagent

Read `${SKILL_DIR}/system_prompt.md` for the system prompt template.
Substitute the per-volume placeholders. Then dispatch the `Agent` tool with:

```
subagent_type: general-purpose
model: opus
description: "cv-correct: review volume N"
prompt: <the filled-in system_prompt.md + the per-volume payload + the reasoning directive below>
```

**Always pass `model: opus`** — the subagent's job (deciding whether a
duplicate group is an extractor bug or an XML quirk, whether a law-number
anomaly is a real misnumbering or a legitimate gap) requires the strongest
reasoning model available, regardless of what model the parent session is
running. Do not omit this argument and do not substitute `sonnet` or
`haiku` to save cost — false positives here become approved corrections
that mutate real published data.

The per-volume payload is a JSON document with these keys (paths above —
read each file's contents into the payload):

```json
{
  "volume": N,
  "candidates": [...]                       // from candidates_N.json
  "validation_report": {...},               // from validation_report_N.json
  "active_corrections": [...],              // from active_corrections.json
  "pending_corrections": [...],             // from pending_corrections.json (do NOT propose duplicates)
  "xml_excerpts": "<XML snippets for the candidate rows>"
}
```

**Reasoning directive — append verbatim to the end of the prompt:**

> Think very hard about each anomaly before deciding. For every law-number
> anomaly, examine the suspect's official title, the neighbouring laws'
> citations, and the XML structure. For every UniqueKey-duplicate group,
> compare the rows column-by-column AND inspect the source XML to classify
> as extractor-fixable vs. XML-data-quality. Do not propose corrections you
> are not confident about — leaving a row un-corrected is always preferable
> to a wrong correction that mutates a published Excel. ultrathink.

The literal token `ultrathink` at the end activates Claude Code's maximum
extended-thinking budget, which is appropriate for this judgement task.

The subagent returns text. Extract the JSON object inside (the schema is
defined in `system_prompt.md`). On parse failure, log + treat as empty.
Write the (possibly empty) response object to
`${SCRATCH_DIR}/subagent_response_N.json` for audit.

### Step 4 — Record proposals + GPO issues

```bash
${VENV_PYTHON} ${SKILL_DIR}/record_proposals.py \
  --volume N \
  --response ${SCRATCH_DIR}/subagent_response_N.json \
  --candidates ${SCRATCH_DIR}/candidates_N.json \
  --pending ${OUTPUT_DIR}/pending_corrections.json \
  --gpo-log ${OUTPUT_DIR}/gpo_issue_log.xlsx
```

Appends new proposals to the pending queue (deduped by `(type, trigger,
correction)`) and writes new issue rows to the GPO Excel. `--candidates`
lets the recorder verify the subagent emitted at least one GPO issue per
anomaly the prefilter surfaced; a warning is logged on under-emission.

### Step 5 — Publish

```bash
${VENV_PYTHON} ${PIPELINE_DIR}/apply_corrections_and_publish.py \
  --volume N --include-pending [--force-republish]
```

`--include-pending` applies the just-written pending proposals in-memory to
the enriched parquet before publishing — so the volume's first Excel is
already corrected, without committing the proposals to the active rule set
(they still need human review via `approve_corrections.py`).

Add `--force-republish` only when the operator explicitly asked to overwrite
an existing published Excel.

The publisher writes:
- `${OUTPUT_DIR}/Volume-N/STATUTE-N_<date>.xlsx`     (full 26-column)
- `${OUTPUT_DIR}/Volume-N/STATUTE-N_<date>_SME.xlsx` (Selection==1 rows only)
- Updates `${OUTPUT_DIR}/run_manifest.json` with `corrections_applied` + `corrections_registry_hash`

The scratch parquet for this volume is deleted on success (unless the
operator passed `--keep-scratch`).

## After the batch

Report a summary table to the operator:

```
Volume | Status              | Candidates | Proposals | Issues | Output
   60  | success             |     0      |     0     |   0    | Volume-60/STATUTE-60_*.xlsx
   70  | success             |     3      |     1     |   2    | Volume-70/STATUTE-70_*.xlsx
   98  | validate_failed     |     -      |     -     |   -    | (no output written)
  114  | success             |     8      |     2     |   4    | Volume-114/STATUTE-114_*.xlsx
```

Then tell the operator how many proposals are pending:

```bash
${VENV_PYTHON} ${PIPELINE_DIR}/approve_corrections.py list --status pending
```

…and remind them to review with `approve_corrections.py show <id>` followed
by `approve_corrections.py approve|reject <id>`.

## Rules

- **Never write to `/groups/brooksgrp/`.** The pipeline's publisher already
  refuses any path under that prefix; if a step fails because of this,
  surface it loudly — don't try to work around it.
- **Hard freeze.** If `apply_corrections_and_publish.py` reports
  `FileExistsError` on a volume, do NOT pass `--force-republish` on your
  own initiative. Ask the operator.
- **Subagent failures are non-fatal.** If a subagent returns malformed JSON,
  times out, or otherwise fails, treat it as "no proposals for this volume"
  and continue to step 5 (publish with no new proposals). The volume still
  publishes successfully — same as the pre-skill baseline.
- **Per-volume isolation.** Each subagent dispatch is one volume. Don't
  batch multiple volumes' candidates into one dispatch — the JSON gets
  hard to attribute back.
- **Parallel dispatch is allowed.** If the operator asks to process many
  volumes, you may dispatch up to ~4 subagents in parallel (one per volume).
  Sequence the Bash invocations per-volume.
