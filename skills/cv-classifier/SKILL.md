---
name: cv-classifier
description: |
  Label a published U.S. Statutes volume Excel with the 7 SME classification
  questions (Q1-Q7) via the zero-shot Opus labelling agent. Outputs a new
  Excel that matches the SME coding-sheet schema (43 columns; Q8 excluded).
  Uses claude-agent-sdk (no Anthropic API key needed). Use when the operator
  says "label volume N with cv-classifier", "run text classification on
  volume N", or "/cv-classifier <volume>".
---

# cv-classifier Skill — zero-shot SME-question labeller

The reasoning step is a per-row, per-question dispatch via the Anthropic
tool-use schema. The labeller lives at
`text-classification-pipeline/classifier/`.

## Per-volume workflow

### Step 1 — Locate the published volume Excel

Find the latest non-SME Excel for the volume. Candidates:

```bash
ls /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/Volume-<N>/STATUTE-<N>_*.xlsx
ls /groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/Volume-<N>/
```

Pick the latest by timestamp; exclude `*_SME.xlsx` (legacy variant).

### Step 2 — Run the labeller

```bash
source /home/G39248410/citizen_voice/venv/bin/activate
cd /home/G39248410/citizen_voice/Code/text-classification-pipeline

python label_volume.py \
    --input <path-to-published-xlsx> \
    --volume <N> \
    --limit 10            # for a dry run; omit for full volume
```

Output lands at `output/labelled_vol<N>_<timestamp>.xlsx`. The file has 43
columns matching the SME coding sheet (identity + parser output + Q1-Q7
answer + quoted-span + "other" columns + Notes). Q8 is intentionally
excluded.

### Step 3 — Verify a sample

```bash
python -c "
import pandas as pd
df = pd.read_excel('output/labelled_vol<N>_<timestamp>.xlsx', engine='openpyxl')
print(df.iloc[0])
"
```

Spot-check the first few rows: Q1 label + quoted_span should match the row's
Text; skipped questions should have 'Skipped: Q1=No' (or similar) in Notes.

### Step 4 — Optional: compare to SME gold

If SMEs have coded this volume, the IRR pipeline can ingest the agent's
Excel as a 5th coder. See the parent plan
(`docs/plans/2026-06-03-citizen-voice-classifier-agent-plan.md` §6).

## Per-row dispatch logic

```
Q1 (always)
  |- "No"   -> defaults: Q2='No', Q3='No', Q4=[], Q5=[]
  |- "Yes"  -> Q2
                |- "Yes"  -> defaults: Q3='No', Q4=[], Q5=[]
                |- "No"   -> Q3, Q4, Q5
Q6 (always)
Q7 (always)
```

LLM calls per row: 3 (Q1=No), 4 (Q1=Yes, Q2=Yes), or 7 (Q1=Yes, Q2=No).

## Model + cost

- Model: latest Claude Opus with extended thinking (via claude-agent-sdk).
- Avg per row: ~5 calls. With prompt caching on the system+definition
  blocks, marginal cost is dominated by the section Text token count.
- 2,878-row volume 95: ~14,000 calls; budget ~$300-1,000.

## Failure modes

| Failure | Behavior |
|---|---|
| Single row errors | Logged; row gets `error=<msg>` in Notes; other rows continue |
| Model declines to use the tool | Currently raises; future v2: retry with stricter prompt |
| Section Text > model context | Truncate at 30K chars (warning logged); future v2: chunk |
| claude-agent-sdk auth failure | Run `claude` CLI to re-auth |

## What this skill does NOT do

- Does NOT modify the published Excel (read-only input).
- Does NOT update any registry or manifest (this is purely an output-side
  pipeline).
- Does NOT compare to SME gold automatically — that's a separate step via
  `irr_analysis/`.

## Quick reference

| What you say | What runs |
|---|---|
| "label volume 95 with cv-classifier" | full vol 95 labelling |
| "dry-run cv-classifier on volume 95" | `--limit 10` |
| "label vol N starting from row K" | use `--start-row K --limit M` (v2; not yet implemented) |
