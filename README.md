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
| `legacy/` | Original extractor modules (still imported by the pipeline) + standalone GPO scrapers — see [Legacy modules](#legacy-modules) |

## Legacy modules

The original, pre-refactor extractor scripts live in [`legacy/`](legacy/) and
are **vendored into this repo** so it is self-contained (no dependency on the
parent directory):

| File | Status | Role |
|---|---|---|
| `Extract_Sections_Divisions_From_XML.py` | **live dependency** | Raw USLM section/division extractor; wrapped by `parser/uslm_parser.py` |
| `post_process.py` | **live dependency** | Agency substring-tagging; wrapped by `pipeline/enricher.py` |
| `generate_id_keys.py` | **live dependency** | `UniqueKey` + section-number formatting; used by enricher + parser |
| `scrape_gpo.py`, `scrape_and_download_gpo.py` | standalone | Fetch the GPO bulk-data modification timeline + download `STATUTE-N.xml` |
| `tag_appropriations.py` | standalone | Config-driven appropriations tagging (superseded by the pipeline) |
| `config.conf`, `data/*.xlsx` | reference | Old config + scraped GPO timeline spreadsheets |

The three **live-dependency** modules are still imported by the active
pipeline. `run_pipeline.py`, `tests/conftest.py`, `pipeline/enricher.py`, and
`parser/uslm_parser.py` add `legacy/` to `sys.path` (via a path relative to
the repo) so imports resolve regardless of where the repo is checked out.

## Quick start

```bash
# 1. Use the shared project venv (uv-managed CPython 3.11), or create one:
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

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

## cv-coder workflow (autonomous code fixes)

`type:"other"` corrections describe extractor-code changes that can't be
expressed as a simple data trigger+replacement rule. The **cv-coder** skill
takes one or more approved `type:"other"` corrections and implements them in
`parser/uslm_parser.py`, gated on a TDD discipline (failing test first), a
scope guard (only `parser/`, `pipeline/`, `tests/`), and a full `pytest` gate.

The workflow runs **direct to `main`** — no feature branch, no human merge
gate. The pytest gate is the safety net. On any gate failure the working
tree is reverted (`git checkout HEAD --` for tracked files; `rm` for newly
created tests) and the entry(ies) are marked `implementation_status=failed`
in the registry.

### End-to-end

```bash
# 1. After cv-correct surfaces a type='other' proposal, approve it.
python approve_corrections.py approve <id>
```

For `type:"other"` entries the CLI then prompts:

- **Family mode** (most cases — when the entry belongs to a known family with
  other pending members):
  ```
  ⚙ Entry #14 is type='other' (family: null-num)
    4 entries in this family currently have implementation_status='pending':
      #2, #14, #15, #16
    Batch all family members into ONE coder task? [Y/n]:
  ```
  Empty input or `Y` queues ONE coder task covering all 4 entries.

- **Single-entry mode** (one-off corrections or family declined):
  ```
  ⚙ Entry #14 is type='other' — describes an extractor-code change.
    Auto-implement now via the cv-coder agent? [y/N]:
  ```
  `y` queues a task with just this entry.

```bash
# 2. In a Claude Code session, invoke the cv-coder skill:
#    "implement correction <task_id> with cv-coder"
```

Claude follows the cv-coder playbook in [skills/cv-coder/SKILL.md](skills/cv-coder/SKILL.md):

1. Verifies working tree is clean
2. Dispatches an Opus subagent (with `ultrathink`) using the system prompt
   in [skills/cv-coder/system_prompt.md](skills/cv-coder/system_prompt.md)
3. Saves the coder's response to `scratch/coder_response_<task_id>.json`
4. Runs `finalize_implementation.py` — the post-coder gate:
   - status == "success"
   - scope clean (no edits outside `parser/`, `pipeline/`, `tests/`)
   - at least one new test added
   - `pytest tests/ -x` is green on the working tree
5. On all gates pass: `git commit` directly to `main` + mark all entry_ids
   `implementation_status=implemented` + auto-chain
   `re_publish_after_fix.py --entry <task_id> --yes`
6. On any gate failure: revert working tree + mark `failed` with notes

### Families

`pipeline/correction_families.py` classifies `type='other'` entries by
keywords in `trigger.pattern` (or fallback to `correction.description`):

| Family | Entries (current registry) | Root cause |
|---|---|---|
| `null-num` | #2, #14, #15, #16 | `<section>` elements without `<num>` collapse to identical UniqueKey via the extractor's `"000000000000001"` fallback |
| `top-level-container` | #3, #7, #11, #17 | `<main>` contains `<part>` / `<title>` / `<chapter>` / `<quotedContent>` directly with no top-level `<section>` — extractor's section walker silently drops the pLaw |
| `sibling-appropriations` | #5 | Sibling `<appropriations>` elements sharing identical `<heading>` text |
| `sibling-level` | #13 | Sibling `<level>` elements within a `<title>` with distinct headings collapse to same UniqueKey |
| `none` | one-offs | No family match |

Batch mode lets one coder run write a fused fix for all family members in
ONE commit, with one regression test per member.

### Re-publish auto-chain

After a successful commit, `finalize_implementation.py` invokes
`re_publish_after_fix.py --entry <task_id> --yes`. The re-publish helper
identifies affected volumes via a validation-warning keyword map (e.g.,
`null-num` matches volumes whose validation report lists `Duplicate
UniqueKey rows`; `top-level-container` matches volumes with `Distinct
LawIdentifier count` mismatch warnings), then loops:

1. Delete the existing `Volume-N/` directory contents
2. Clear the manifest entry's status fields
3. Run `run_pipeline.py --volumes N --stop-before-publish`
4. Run `apply_corrections_and_publish.py --volume N --include-pending`

If re-publish fails mid-volume the commit still stands — re-publish can be
retried manually:

```bash
python re_publish_after_fix.py --entry <id>
```

### Manual escape hatches

- **Re-publish only**: `python re_publish_after_fix.py --entry <id>` —
  re-publishes affected volumes for an already-implemented entry
- **Dry run**: `python re_publish_after_fix.py --entry <id> --dry-run` —
  print the plan, do nothing
- **Skip cv-coder, implement by hand**: edit `parser/uslm_parser.py`
  directly, then manually flip the entry's `implementation_status` to
  `manual_override` in `processed_output/active_corrections.json` (a CLI
  for this is future work)

### What gets checked

Every cv-coder run must satisfy ALL of:

- Coder's reported `status == "success"`
- All modified files under `parser/`, `pipeline/`, or `tests/` (and NONE
  in the forbidden list: `pipeline/corrections_registry.py`,
  `apply_corrections_and_publish.py`, `approve_corrections.py`)
- At least one new test added (TDD)
- `pytest tests/ -x` is green on the working tree

If any gate fails, the working tree is reverted and the entry(ies) are
marked `failed` with notes recording the specific blocker.

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

208 unit tests cover the parser/segmenter, registry, prefilter, approval
CLI, publisher freeze, ingest, manifest, and dedup logic.

## Authorship

Built collaboratively by the citizen_voice team with Claude Code
(Claude Opus 4.7) for the parser, autonomous correction agent, and
publishing pipeline.
