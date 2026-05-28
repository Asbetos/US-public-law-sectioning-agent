# US Public Law Sectioning Agent

An autonomous pipeline for parsing the U.S. Statutes at Large XML
(`STATUTE-N.xml` from GPO), segmenting each Public Law into its
sections / divisions, applying static + dynamically-discovered
corrections, and publishing a per-volume Excel for SME review.

Issues GPO needs to fix in the source XML are written to an
append-only `gpo_issue_log.xlsx` for batch reporting back to GPO.

## Architecture

See [PLAN.md](PLAN.md) for the full design. The short version:

```
raw XML  →  parse  →  segment  →  enrich  →  validate  →  publish
                                       │
                                  (Stage 4.5)
                                       │
                     ┌─────────────────▼──────────────────┐
                     │ cv-correct Claude Code skill       │
                     │ - prefilter: XML-order law-num     │
                     │   anomalies + UniqueKey dups       │
                     │ - dispatch subagent per volume     │
                     │ - record proposals + GPO log       │
                     └────────────────────────────────────┘
```

The reasoning step is a Claude Code subagent dispatched from the
operator's session via the cv-correct skill at
[`skills/cv-correct/`](skills/cv-correct). The skill follows a
five-step workflow per volume — stop-before-publish → prefilter →
subagent → record → publish.

## Key files

| Path | Purpose |
|---|---|
| `run_pipeline.py` | Main runner; pass `--volumes N` and optionally `--stop-before-publish` to checkpoint before the correction stage |
| `apply_corrections_and_publish.py` | Reads the stop-before-publish checkpoint, applies any approved + (optionally) pending corrections, publishes the volume Excel + manifest |
| `approve_corrections.py` | Operator CLI: `list / show / approve / reject / diff` for the pending queue |
| `add_agencies.py` | Operator CLI: append rows to the local `AgencyList.xlsx` between runs |
| `seed_lookup_files.py` | One-time copy of `AgencyList.xlsx` and `DivisionMapping.xlsx` from a source dir into `processed_output/` |
| `law_id_corrections.py` | Static seed corrections (9 law-ID rules + 5 section-number rules) applied at parse time |
| `skills/cv-correct/SKILL.md` | Orchestration playbook the Claude Code session follows |
| `skills/cv-correct/system_prompt.md` | The system prompt embedded in each subagent dispatch (defines the 8-column GPO log schema as the strict format contract) |
| `skills/cv-correct/prefilter.py` | Rule-based pre-filter: walks `<pLaw>` in XML order, surfaces law-number anomalies + UniqueKey duplicates |
| `skills/cv-correct/record_proposals.py` | Parses the subagent's JSON response; appends proposals to `pending_corrections.json` and rows to `gpo_issue_log.xlsx` (with dedup) |
| `pipeline/`, `parser/`, `validation/` | Internal modules — segmenter, enricher, publisher, validator, registry |

## Quick start

```bash
# 1. Create a virtualenv with Python 3.11
python3 -m venv venv
source venv/bin/activate
pip install pandas lxml openpyxl pyarrow numpy pytest

# 2. Seed local lookup files (one-time)
python seed_lookup_files.py

# 3. Run the deterministic pipeline (stages 1–5) for a volume
python run_pipeline.py --volumes 75 --stop-before-publish

# 4. Inside a Claude Code session, invoke the cv-correct skill:
#    "Process vol 75 with cv-correct" (the skill handles the rest)

# 5. Review + approve / reject proposals
python approve_corrections.py list --status pending
python approve_corrections.py show <id>
python approve_corrections.py approve <id> --note "..."
```

## Hard rules

- **Published Excels are frozen.** Re-publishing requires explicit `--force-republish` + manual manifest cleanup.
- **The local lookup files are authoritative.** Production
  (`AgencyList.xlsx`, `DivisionMapping.xlsx`) is never read at run
  time and never written to.
- **The GPO log is locked to 8 columns.** The subagent is not
  authorized to add columns or change the format.

## Tests

```bash
python -m pytest tests/ -x
```

103 unit tests cover the registry, prefilter, approval CLI, publisher
freeze, ingest, manifest, and dedup logic.

## Authorship

Built collaboratively by the citizen_voice team with Claude Code
(Claude Opus 4.7) for the parser, autonomous correction agent, and
publishing pipeline.
