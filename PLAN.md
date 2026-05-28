# Citizen Voice — Data-Preprocessing Pipeline Plan

**Document path:** `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/PLAN.md`  
**Status:** Revised after stakeholder review (Section 15 decisions applied)  
**Date:** 2026-05-17  
**Author:** Pipeline architecture review

**Revision summary (v2):**
- **Output destination changed**: all pipeline outputs go to `processed_output/` under this folder. The production directory at `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/` is **read-only** — the pipeline never writes there.
- **Lookup files now local**: `AgencyList.xlsx` and `DivisionMapping.xlsx` are copied from the read-only source XML dir into `processed_output/`. All mutations happen on the local copies.
- **Scope tightened**: Volumes 1–36 are permanently dropped; volumes 37–58 promoted from Phase 4 to Phase 3.
- **Section 15 converted**: Open Questions → Stakeholder Decisions (all 10 resolved).
- **Already-curated production outputs are preserved**: the pipeline produces parallel outputs in `processed_output/` but does not touch any curated files in `latest/`.

---

## 1. Executive Summary

This plan describes a hardened, end-to-end data-processing pipeline for the "citizen_voice" project. The pipeline ingests U.S. federal Statutes at Large (Public Laws) from GovInfo/GPO in USLM XML format, parses and segments each law into typed records (sections, divisions, appropriations entries), enriches those records with agency tags and hierarchical identifiers, validates outputs against the source XML, and delivers a curated Excel dataset ready for Subject Matter Expert (SME) review.

The current rudimentary pipeline consists of five loosely coupled scripts that must be run by hand for each volume. It has processed approximately 68 of 137 volumes (volumes 59–72 and 74–137 are visible in the latest output directory as of 2026-05-16; volumes 1–58 are absent). Known issues include a 1,750-line monolithic parser, duplicated appropriations-parsing code in four locations, no orchestration runner, no manifest/reproducibility tracking, and identifier-format inconsistencies across the volume boundary at vol 63.

The target state is a six-stage pipeline with a CLI runner, a content-hash-based manifest, per-volume QA assertions, a clean 26-column data model, and a defined SME handoff protocol. **All pipeline outputs land in `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/`; the existing production directory at `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/` is read-only and never modified.** Lookup files (`AgencyList.xlsx`, `DivisionMapping.xlsx`) are copied from `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/` into `processed_output/` on first run; mutations stay local. The pipeline is estimated at approximately 18 new or significantly modified files achievable in 4–8 weeks by one engineer.

**Headline shape:** 6 stages, ~18 files, 4 implementation phases, zero writes to `/groups/brooksgrp/`.

---

## 2. Goals and Non-Goals

### In Scope

- Process **volumes 37–137** of U.S. Statutes at Large from the read-only source `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/`. Volumes 37–58 are lower priority but expected in the near term (Phase 3).
- Filter to Public Laws only (existing `publicPrivate == "public"` check is correct and must be preserved)
- Parse and segment: sections, divisions (including the full division/title/subtitle/chapter/subchapter hierarchy), and appropriations entries (3-level nesting)
- Normalize law identifiers to a canonical format across both modern (vol > 63, `citableAs` field) and legacy (vol ≤ 63, `sidenote` regex) branches
- Apply and extend the externalized correction tables in `law_id_corrections.py`
- Enrich with agency tags (`AgencyList.xlsx`) and appropriations flags
- Assign hierarchical UniqueKey (`generate_id_keys.py`)
- Validate each volume's output row count, schema, and known regression cases
- Produce a manifest recording input XML modification time and output file SHA-256
- Deliver per-volume Excel files with a defined SME-ready column set into the **local** `processed_output/` directory
- **Copy `AgencyList.xlsx` and `DivisionMapping.xlsx`** from the source XML directory into `processed_output/` on first run; all mutations target the local copies only
- Add a CLI runner capable of running all volumes, a range, or selected volumes without editing `config.conf`
- Expand the pytest suite to cover all pipeline stages

### Not in Scope

- Legal interpretation of statute text
- OCR re-recognition of scanned pages (the digitization vendor produced the XML; we consume it as-is)
- Processing Private Laws, concurrent resolutions, or proclamations within the XML (permanently excluded per stakeholder decision)
- Full-text search indexing or vector embeddings
- A production web UI or dashboard (the SME handoff is file-based in this plan)
- **Volumes 1–36** (permanently out of scope — not part of the GovInfo USLM corpus this project consumes)
- **Any write to `/groups/brooksgrp/`** — the source XML directory and the production output directory are both read-only references
- **Google Sheets / Drive upload** (the SME handoff format is Google Sheets, but that integration is a separate workstream after this pipeline is functional)
- **Parallel-volume processing** (deferred to a future iteration once the present pipeline is verified)
- **Re-processing volumes that have already been SME-curated** (curation is a substantial labor effort; protect those outputs by never writing into `latest/`)

---

## 3. Glossary

| Term | Definition |
|---|---|
| **pLaw** | A `<pLaw>` XML element representing one Public Law or Private Law within a STATUTE-{vol}.xml file. One volume may contain hundreds of pLaws (e.g., STATUTE-114 has 431). |
| **USLM** | United States Legislative Markup — the GPO XML schema (`http://schemas.gpo.gov/xml/uslm`) used for all Statutes at Large XML files. Schema versions range from 2.0.10 to 2.0.17 across the corpus. |
| **citableAs** | The `<citableAs>` element in modern USLM (vol > 63) that gives the human-readable law identifier, e.g., "Public Law 106–171". Vol 70 and entries with "v" in the value require special fallback to `<docNumber>` + `<congress>`. |
| **sidenote** | In legacy USLM (vol ≤ 63), the law identifier is embedded in a `<sidenote>` element and extracted via regex patterns matching "Public Law NNN" or "Pub. No. NNN". |
| **Section** | A `<section>` element in the `<main>` body of a pLaw; the primary unit of legislative text. Has a `<num>` (section number) and optional `<heading>`. |
| **Division** | A structural grouping element — `<division>`, `<title>`, `<subtitle>`, `<chapter>`, or `<subchapter>` — that contains sections. Also used for `<appropriations>` entries which have heading/subheading/content nesting. Stored as `EntryType = "Division"` in the output. |
| **Appropriations** | A `<appropriations>` element that appears at top-level `<main>`, inside `<chapter>`, inside `<title>`, or inside `<division>/<title>/<chapter>`. Nested up to 3 levels. Represents a discrete funding item. |
| **EntryType** | Column in the output with value "Section" or "Division". Appropriations entries are classified as Division. |
| **SME** | Subject Matter Expert — a legal domain expert who curates the pipeline output, deciding which segments are substantively relevant. |
| **Selection** | Binary column (0/1) in the output. Currently set by a random sample of 600 entries per volume (excluding "sense of congress", "sunset", "severability", "short title", "table of contents" section names and CRA disapproval resolutions). SMEs use this to prioritize review. |
| **UniqueKey** | Hierarchical identifier of the form `VVV-LLL-DDD-TTT-SSS-CCC-UUU-{S|D}-NNNNNNNNNNNNNNN` generated by `generate_id_keys.py`. Volume, Law, Division, Title, Subtitle, Chapter, Subchapter, EntryType, SectionNumber/DivisionHeadingID. |
| **KeyVersion** | Timestamp string stored alongside UniqueKey indicating when the key was last recomputed. Will be replaced by a content hash in the target architecture. |
| **DivisionMapping.xlsx** | A shared lookup table at `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/DivisionMapping.xlsx` mapping division heading text to integer IDs used in UniqueKey computation. The current pipeline mutates this file in place — a significant reproducibility risk. |
| **AgencyList.xlsx** | Spreadsheet at the same path with "Agency" and "Bureau" columns used for substring matching against segment text. |
| **LawType** | Text extracted from `<docTitle>` element; values like "AN ACT", "A JOINT RESOLUTION", etc. |
| **vol boundary** | The integer 63 is the threshold between "modern" and "legacy" USLM identifier extraction paths. Vol 63 itself uses the legacy (sidenote) path per the `int(vol) > 63` condition. |

---

## 4. Current State

### What the Rudimentary Pipeline Does Today

The five scripts are run manually from the working copy directory (`/home/G39248410/citizen_voice/Code/`) or the shared copy (`/groups/brooksgrp/citizen_voice/python_programs/citizen_voice_statutes/Code/`). They depend on `config.conf` being in the current working directory at import time (`config.read('config.conf')` fires at module import in `post_process.py`, `tag_appropriations.py`).

The typical operator workflow for one volume:

1. Edit `config.conf` — set `Mode=Selected`, `VolumeNumber=<N>`
2. Run `python Extract_Sections_Divisions_From_XML.py` (reads XML, produces Excel in `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/Volume-{N}/`)
3. Run `python generate_id_keys.py` (re-reads the Excel, computes UniqueKeys, writes back to same file)
4. Optionally run `python tag_appropriations.py` (produces `Appropriations_Volume-{N}.xlsx`)
5. Optionally run `python post_process.py` (agency enrichment, though this is now integrated into step 2's main loop)

Steps 2 and 3 are partially merged: the `__main__` block of `Extract_Sections_Divisions_From_XML.py` calls `generate_and_process_id()` and `update_all_directories()` after each volume. But `update_all_directories()` in `generate_id_keys.py` contains a hardcoded filter `if not any(str(v) in str(filename) for v in [70]):` which limits key updates to Volume-70 only and would need manual editing for each volume.

### Data Flow Diagram (Current State)

```
┌──────────────────────────────────────────────────────────────────┐
│  MANUAL TRIGGER (edit config.conf, python Extract_...py)         │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────┐
│  scrape_and_download_gpo.py         │  (run separately, ad hoc)
│  → GovInfo XML API                  │
│  → STATUTE-{vol}.xml saved to       │
│    /groups/brooksgrp/laws/...       │
└─────────────────────────────────────┘
                       │ (XML file already on disk)
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Extract_Sections_Divisions_From_XML.py  (~1750 lines)          │
│  extract_public_law_from_uslm(file_path, vol)                   │
│  ├─ For each <pLaw>:                                            │
│  │   ├─ Filter: publicPrivate == "public"                       │
│  │   ├─ Extract law_identifiers                                 │
│  │   │   ├─ vol > 63: <citableAs> with fallbacks               │
│  │   │   └─ vol ≤ 63: <sidenote> + regex                       │
│  │   ├─ apply_law_id_corrections() (law_id_corrections.py)     │
│  │   ├─ Walk <main> for sections, appropriations, levels,       │
│  │   │   titles, subtitles, chapters, subchapters, parts,       │
│  │   │   divisions, division/titles, division/chapters         │
│  │   └─ apply_section_number_correction()                       │
│  │                                                              │
│  create_xlsx_output_from_json()                                 │
│  ├─ Merge Sections + Divisions DataFrames                       │
│  ├─ Sort by (LawNumber, counter)                                │
│  ├─ Sample 600 rows → Selection=1                               │
│  └─ Save to /groups/brooksgrp/.../statutes_broken.../          │
│                                                                 │
│  add_grouped_agencies() (post_process.py)                       │
│  └─ Substring match AgencyList.xlsx against text cols          │
│                                                                 │
│  generate_and_process_id() (generate_id_keys.py)               │
│  ├─ Read/update DivisionMapping.xlsx (IN PLACE — risk!)        │
│  ├─ Compute UniqueKey for every row                             │
│  └─ Save final xlsx to latest/Volume-{N}/STATUTE-{N}_{ts}.xlsx │
│                                                                 │
│  update_all_directories()   ← hardcoded to vol 70 only         │
└─────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────┐
│  tag_appropriations.py  (manual)    │
│  → Appropriations_Volume-{N}.xlsx   │
└─────────────────────────────────────┘
```

### Known Processed Volumes (as of 2026-05-16)

From `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/`:

Volumes present: 59, 60, 61, 62, 63, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 102, 103, 105, 106, 107, 108, 109, 110, 111, 112, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134.

Volumes missing from latest output (XML exists on disk): 64, 65, 66, 67, 68, 69, 90, 101, 104, 113, 114 (appears present in listing), plus all vols 1–58 which have no XML in the raw input directory listing either (the glob showed STATUTE-37.xml through STATUTE-137.xml only, meaning vols 1–36 are absent from the GovInfo download set).

The actual coverage gap is smaller than the stated "~76 of 137" — the directory listing shows approximately 65 volumes processed. Some volumes like 64–69, 90, 101, 104, and 113 are missing from the output despite XML being available.

---

## 5. Target State

The target pipeline has six explicit stages, each with a defined interface, logging, and failure mode. All stages can be run by a single CLI command for one volume, a range, or all volumes. Incremental re-runs skip volumes whose input XML hash matches the manifest entry.

```
┌────────────────────────────────────────────────────────────────────┐
│  CLI Runner: run_pipeline.py  --volumes 37-137  --stages all       │
└──────────────┬─────────────────────────────────────────────────────┘
               │
     ┌─────────▼──────────┐
     │  Stage 1: Ingest   │  read XML (read-only); copy lookup files
     └─────────┬──────────┘    on first run; build manifest
               │  processed_output/run_manifest.json
               │  processed_output/AgencyList.xlsx       (copy)
               │  processed_output/DivisionMapping.xlsx  (copy)
     ┌─────────▼──────────┐
     │  Stage 2: Parse    │  XML → typed raw records (dict list)
     └─────────┬──────────┘
               │  processed_output/scratch/raw_records_{vol}.parquet
     ┌─────────▼──────────┐
     │  Stage 3: Segment  │  filter + classify + sort
     └─────────┬──────────┘
               │  processed_output/scratch/segmented_{vol}.parquet
     ┌─────────▼──────────┐
     │  Stage 4: Enrich   │  agency tags + appr flag + UniqueKey
     └─────────┬──────────┘    (uses LOCAL DivisionMapping.xlsx)
               │  processed_output/scratch/enriched_{vol}.parquet
     ┌─────────▼──────────┐
     │  Stage 5: Validate │  schema + counts + regression tests
     └─────────┬──────────┘
               │  processed_output/scratch/validation_report_{vol}.json
     ┌─────────▼──────────┐
     │  Stage 6: Publish  │  Excel + manifest hash + SME view
     └─────────────────────┘
               │  processed_output/Volume-{vol}/STATUTE-{vol}_{date}.xlsx
               │  processed_output/Volume-{vol}/STATUTE-{vol}_{date}_SME.xlsx
               │  processed_output/run_manifest.json (updated)

Read-only references (never written by this pipeline):
  /groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/                       (source XML)
  /groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/  (production output; curated)
```

---

## 6. Gap Analysis

| Component | Current State | Target State | Gap |
|---|---|---|---|
| Orchestration | Manual config edits per volume | CLI runner with `--volumes`, `--stages`, `--force` flags | Missing: `run_pipeline.py` |
| Output destination | Writes to production `/groups/brooksgrp/.../latest/` | Writes only to local `processed_output/`; production stays read-only | Path constants + manifest under local dir |
| Lookup file location | Reads & **mutates** `/groups/brooksgrp/.../DivisionMapping.xlsx` in place | Reads-and-mutates **local copy** in `processed_output/DivisionMapping.xlsx`; copies once on first run | Bootstrap step + path constant |
| Ingestion manifest | None | `run_manifest.json` with input XML mtime + SHA-256 | Missing: manifest module |
| XML parsing | `extract_public_law_from_uslm()` in monolith | Same logic refactored into `parser/uslm_parser.py` with appropriations extracted to `parser/appr_parser.py` | Missing: module split |
| Legacy vol ≤63 path | Inline regex in main function | Same logic, same file, just isolated to `_extract_legacy_law_id()` helper | Needs extraction |
| Law ID normalization | `apply_law_id_corrections()` in `law_id_corrections.py` | Same file, extended; adds `normalize_law_id()` to produce canonical `{congress}-{number}` form | Needs `normalize_law_id()` |
| Section number corrections | `apply_section_number_correction()` in `law_id_corrections.py` | Same, extended as older volumes processed | Ongoing extension |
| Appropriations parsing | Duplicated 3-level loop in 4 locations | Single `extract_appropriations_block()` function called from all 4 locations | Missing: de-duplication |
| Agency tagging | `post_process.py`, import-time `config.read()` | Same logic, config passed as argument | Fix CWD coupling |
| Appropriations flag | `tag_appropriations.py`, separate script | Integrated as `enrich.tag_appropriations_flag()` | Needs integration |
| UniqueKey generation | `generate_id_keys.py`, mutates production `DivisionMapping.xlsx` in place | Same logic; loads **local** `processed_output/DivisionMapping.xlsx` once; mutations deferred to a single atomic write at end of run | Fix mutation risk + redirect to local copy |
| Content hash | None (KeyVersion is timestamp) | SHA-256 of concatenated Text column per law → `ContentHash` column | Missing |
| Validation | None | `validation/validator.py` with row count, schema, regression assertions | Missing entirely |
| Per-volume regression | Manual inspection | Pytest parametrized fixtures for known law-ID and section-number corrections | Needs expansion |
| SME review state | `Selection` (0/1), `Order` columns | Add `ReviewStatus`, `ReviewerNote`, `ReviewedAt` columns; version-stable UniqueKey as join key | Missing columns |
| CWD coupling | `config.read('config.conf')` at import in 3 files | Config path passed as argument to all functions | Needs fix (Tier B) |
| Coverage | ~65 of 101 available volumes processed in production `latest/` | All volumes 37–137 processed into `processed_output/` (volumes 1–36 permanently out of scope) | Needs runner + Phase 3 backfill of vols 37–58 |
| Reproducibility | No manifest; output filename embeds timestamp only | Manifest with input hash, output hash, run timestamp, script git hash | Missing |

---

## 7. Architecture

### Stage 1 — Ingestion & Bootstrap

**Responsibility:** Ensure the local `processed_output/` workspace is initialized; verify input XML availability; record a manifest. Downloads from GovInfo are out of scope for routine runs (XMLs are pre-positioned at the shared read-only source); the existing scraper is retained as a tool to refresh that source separately when needed.

**Existing reusable code:**
- `/home/G39248410/citizen_voice/Code/scrape_gpo.py` — `scrape_name_last_modified()` returns a DataFrame of volume number → last-modified timestamp. Reuse as a separate utility when the source dir needs refreshing.
- `/home/G39248410/citizen_voice/Code/scrape_and_download_gpo.py` — `download_xml_files()` downloads XMLs with skip-if-exists logic. Used only when refreshing the source. **Note:** Current code writes to `/groups/brooksgrp/laws/...`. For the new pipeline, the download utility is invoked manually when needed; the runner itself does not write to `/groups/brooksgrp/`.

**New module:** `pipeline/ingest.py`

Key functions:
- `bootstrap_workspace(processed_output_dir, source_xml_dir)` — on first run, create `processed_output/`, `processed_output/scratch/`, and `processed_output/Volume-*/` placeholders; copy `AgencyList.xlsx` and `DivisionMapping.xlsx` from `source_xml_dir` into `processed_output/`. Idempotent (skip-if-exists).
- `build_manifest(xml_dir, manifest_path)` — for each STATUTE-{vol}.xml in the source, compute SHA-256 and record mtime. Write to `processed_output/run_manifest.json`.
- `check_incremental(vol, manifest_path, xml_dir)` — return True if the stored hash matches the current source file, allowing the runner to skip the volume.

The manifest JSON schema:
```json
{
  "volumes": {
    "114": {
      "xml_path": "/groups/brooksgrp/laws/.../STATUTE-114.xml",
      "xml_sha256": "abc123...",
      "xml_mtime": "2024-01-09T00:00:00",
      "last_run": "2026-05-17T10:00:00",
      "output_path": "/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/Volume-114/STATUTE-114_2026-05-17.xlsx",
      "output_sha256": "def456...",
      "status": "success"
    }
  }
}
```

### Stage 2 — Parsing

**Responsibility:** Parse STATUTE-{vol}.xml, walk the pLaw tree, and return a list of raw record dicts. Apply law-ID extraction (both branches), law-ID corrections, and section-number corrections. Filter to Public Laws only. Produce no DataFrames yet — just Python dicts.

**Existing reusable code:**
- `extract_public_law_from_uslm()` in `/home/G39248410/citizen_voice/Code/Extract_Sections_Divisions_From_XML.py` — all logic is correct and battle-tested. The goal is to extract it into its own module, not rewrite it.
- `get_clean_text()`, `extract_section_text()`, `process_section()` — utility functions, move with the parser.
- `apply_law_id_corrections()`, `apply_section_number_correction()` in `law_id_corrections.py` — keep exactly as-is.

**New module:** `parser/uslm_parser.py`

The primary refactoring target is the duplicated 3-level appropriations loop. It appears verbatim in at least four `findall("uslm:appropriations", ns)` call sites across the function: at top-level `<main>`, inside `<chapter>` under `<title>`, inside `<title>` directly, and inside `<division>/<title>/<chapter>`. Extract this to:

```python
# parser/appr_parser.py
def extract_appropriations_block(
    appropriation_elem, ns, law_meta, parent_context
) -> list[dict]:
    """
    Recursively walk a single <appropriations> element up to 3 levels deep.
    Returns a list of record dicts ready to append to results["Divisions"].
    parent_context contains: LawIdentifier, Division, Title, Chapter, ...
    """
```

This single function replaces ~400 lines of duplicated code.

**New module:** `parser/law_id_utils.py`

Extract and add:
```python
def normalize_law_id(raw_id: str) -> str:
    """
    Canonical form: '{congress}-{number}' with ASCII hyphen, e.g. '106-171'.
    Strips 'Public Law ' prefix, normalizes en-dash (U+2013) to hyphen.
    Returns raw_id unchanged if pattern doesn't match (logged as warning).
    """
```

This function is called after `apply_law_id_corrections()` on every pLaw and again during UniqueKey generation. The existing `generate_unique_key()` already does `re.search(r'(\d+)[–-](\d+)', str(row['LawIdentifier']))` which handles both forms, but consumers that do string comparison need the normalized form.

**Vol boundary logic:** The `int(vol) > 63` branch stays exactly where it is in `extract_public_law_from_uslm()`. The vol 70 and "v in law_identifiers" fallbacks stay intact. The one hardcoded correction in the main loop (`law_identifiers =='81-207' and '14' in title_text and '15' in chapter_text`) should be migrated to `law_id_corrections.py` as a third corrections table (`INLINE_CORRECTIONS`).

**Output of Stage 2:** `raw_records_{vol}.json` cached in a scratch directory (optional but recommended for debugging).

### Stage 3 — Segmentation and Classification

**Responsibility:** Convert raw records to a DataFrame, sort, assign `EntryType`, apply the selection sampling logic, and assign `OriginalOrder`.

**Existing reusable code:**
- `create_xlsx_output_from_json()` in `Extract_Sections_Divisions_From_XML.py` — contains the merge, sort, filter, and 600-row sampling logic. Extract this into:

**New module:** `pipeline/segmenter.py`

Key functions:
- `build_dataframe(raw_records: dict) -> pd.DataFrame` — merges Sections and Divisions, assigns EntryType, sorts by (LawNumber, counter).
- `apply_selection_sampling(df, n=600, seed=42) -> pd.DataFrame` — applies the current exclusion filters and random sample. The exclusion list (`exclude_section_names`) and pattern (`exclude_joint_res_wording`) should move to a config constant or a YAML file to allow easy extension without code changes.
- `assign_original_order(df) -> pd.DataFrame` — assigns the sequential `OriginalOrder` column.

**Note on sampling reproducibility:** `np.random.seed(42)` is currently set globally at module import. This means re-running the pipeline with identical inputs produces identical `Selection` and `Order` assignments, which is correct for reproducibility. The seed should be an explicit parameter passed to `apply_selection_sampling()`.

**Note on small volumes:** If a volume has fewer than 600 eligible entries, `sample(n=600)` will raise. Add a guard: `n = min(600, len(eligible))` and log a warning.

### Stage 4 — Enrichment and Tagging

**Responsibility:** Add agency tags, appropriations flag, content hash, and UniqueKey.

**Existing reusable code:**
- `fetch_agency_list()`, `add_grouped_agencies()` in `post_process.py` — correct logic, just fix the `config.read()` at import-time issue by accepting `datapath` as a parameter.
- `generate_and_process_id()` in `generate_id_keys.py` — correct, but see the `DivisionMapping.xlsx` mutation risk below.
- `tag_appropriations.py` — integrate the `isAppropriation` flag computation inline.

**New module:** `pipeline/enricher.py`

Key functions:
- `add_agency_tags(df, agency_list) -> pd.DataFrame` — wraps `add_grouped_agencies()` without config coupling.
- `add_appropriations_flag(df) -> pd.DataFrame` — inline the logic from `tag_appropriations.py`: a law has `isAppropriation=True` if any of its rows has `EntryType == "Division"`.
- `add_content_hash(df) -> pd.DataFrame` — compute SHA-256 of sorted concatenated `Text` values per `LawIdentifier`, store in `ContentHash` column.
- `add_unique_keys(df, division_mapper) -> pd.DataFrame` — wraps `generate_and_process_id()` with the mapper pre-loaded externally.

**DivisionMapping.xlsx mutation strategy:** Currently, every run of `generate_and_process_id()` reads the production `DivisionMapping.xlsx` directly, adds new headings it encounters, and writes the file back. In the new pipeline this is replaced with a two-part fix:

1. **Source location**: the runner reads only `processed_output/DivisionMapping.xlsx` (the local copy bootstrapped in Stage 1). The production file at `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/DivisionMapping.xlsx` is **never** opened for write by this pipeline.
2. **Atomic write**: load the mapping once at pipeline start into a dict, accumulate new entries in memory across all volumes in the run, then write `processed_output/DivisionMapping.xlsx` atomically (write to temp, rename) at the end of the run. The `enricher.py` module accepts the mapper dict by reference and returns it alongside the enriched DataFrame.

This eliminates the parallel-run corruption hazard and removes any dependency on write access to `/groups/brooksgrp/`.

### Stage 5 — Validation and QA

**Responsibility:** Assert that each volume's output meets structural invariants, row count expectations, and regression cases.

**New module:** `validation/validator.py`

Key functions:
- `validate_schema(df) -> list[str]` — check that all 26 target columns are present with expected dtypes; return list of error messages.
- `validate_row_counts(df, vol, xml_path, ns) -> list[str]` — count pLaw elements in the source XML (public only) and compare to the number of distinct `LawIdentifier` values in the output. Flag if any expected law ID is missing. This requires a lightweight XML scan (just pLaw elements, not full parsing).
- `validate_entry_type_totals(df) -> list[str]` — check that EntryType has only "Section" and "Division" values; check that the Section count is non-zero per volume.
- `validate_regression_cases(df) -> list[str]` — assert known fixed law-IDs and section numbers appear in the output. Example assertions:
  - LawIdentifier "79-466" exists (not "79-496") when the specific title is present
  - LawIdentifier "81-174" exists (not "81-175") in vol 63 output
  - SectionNumber "SEC. 6." exists for law "106-382" with heading "USE OF PICK-SLOAN POWER"
- `run_all_validations(df, vol, xml_path) -> ValidationReport` — aggregate and return a structured report with pass/fail per check.

**New module:** `validation/report.py`

A simple dataclass and JSON serializer for `ValidationReport`:
```python
@dataclass
class ValidationReport:
    vol: int
    passed: list[str]
    failed: list[str]
    warnings: list[str]
    row_count: int
    law_count: int
    timestamp: str
```

The runner fails loudly (exits with non-zero code) if any `failed` entries exist for a volume. Warnings do not block output but are logged and written to the manifest.

### Stage 6 — Publication and SME Curation Handoff

**Responsibility:** Write final Excel files, update the manifest with output hashes, and produce any SME-specific views.

**Existing reusable code:**
- The `df_with_id.to_excel(...)` call in `Extract_Sections_Divisions_From_XML.py` — same pattern, moved to `pipeline/publisher.py`.

**New module:** `pipeline/publisher.py`

Key functions:
- `write_volume_excel(df, output_dir, vol) -> Path` — writes to `processed_output/Volume-{vol}/STATUTE-{vol}_{date}.xlsx` with the 26-column schema, atomically (write to temp, rename). `output_dir` defaults to `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/`.
- `update_manifest(manifest_path, vol, output_path, output_sha256, report)` — updates `processed_output/run_manifest.json` for this volume.
- `write_sme_view(df, output_dir, vol)` — write a filtered view containing only `Selection == 1` rows for SME consumption, with the review-state columns pre-populated with `ReviewStatus = "Pending"`. Filename: `processed_output/Volume-{vol}/STATUTE-{vol}_{date}_SME.xlsx`.

**Production-output safety:** `publisher.py` never accepts a path under `/groups/brooksgrp/`. A safety guard asserts that the resolved output directory starts with the configured local root and raises if a caller tries to override it to the production directory. The Google Sheets upload step is a separate, future workstream (see Stakeholder Decisions §15).

---

## 8. Data Model

The target output schema has 26 columns (compared to the current 23). Three new columns are added: `ContentHash`, `IsAppropriation`, and `ReviewStatus`. The `KeyVersion` timestamp is supplemented by content hash logic.

### Full Column Specification

| # | Column | Type | Nullable | Source | Definition |
|---|---|---|---|---|---|
| 1 | `UniqueKey` | str | No | `generate_id_keys.py` | Hierarchical ID: `VVV-LLL-DDD-TTT-SSS-CCC-UUU-{S\|D}-NNNNNNNNNNNNNNN`. Stable across re-runs for the same record structure. |
| 2 | `KeyVersion` | str | No | `generate_id_keys.py` | ISO datetime of last key computation. Retained for backward compatibility. |
| 3 | `ContentHash` | str | Yes | `enricher.add_content_hash()` | SHA-256 hex of sorted `Text` column values for this `LawIdentifier`. Null for Division-only laws. |
| 4 | `OriginalOrder` | int | No | `segmenter.assign_original_order()` | 1-based row index within the volume's combined output, assigned after sort by (LawNumber, counter). |
| 5 | `EntryType` | str | No | Parser | "Section" or "Division". Appropriations entries are "Division". |
| 6 | `Selection` | int | No | `segmenter.apply_selection_sampling()` | 0 or 1. 1 = row included in the SME review sample. |
| 7 | `Order` | int | Yes | `segmenter.apply_selection_sampling()` | 1–600 random presentation order for `Selection == 1` rows; null for unselected rows. |
| 8 | `LawIdentifier` | str | No | Parser (post-correction, post-normalize) | Canonical form `{congress}-{number}` e.g., "106-171". For modern volumes, derived from `<citableAs>`; for legacy, from sidenote regex. After `apply_law_id_corrections()` and `normalize_law_id()`. |
| 9 | `LawType` | str | Yes | Parser | Text from `<docTitle>`, e.g., "AN ACT", "A JOINT RESOLUTION". Null if element absent. |
| 10 | `LawTitle` | str | Yes | Parser | Text from `<officialTitle>` (cleaned, no sidenote/page/footnote content). |
| 11 | `approvedDate` | str | Yes | Parser | Text from `<approvedDate>`. String, not parsed to date, to preserve original formatting. |
| 12 | `IsAppropriation` | bool | No | `enricher.add_appropriations_flag()` | True if this law has any Division-type entries (i.e., contains appropriations blocks). |
| 13 | `Division` | str | Yes | Parser | Outer division label, e.g., "DIVISION A". Null for laws with no division structure. |
| 14 | `Title` | str | Yes | Parser | Title label within division/law, e.g., "TITLE IV". |
| 15 | `SubTitle` | str | Yes | Parser | Subtitle label, e.g., "SUBTITLE B". |
| 16 | `Chapter` | str | Yes | Parser | Chapter label, e.g., "CHAPTER 5" or "CHAPTER VII". |
| 17 | `SubChapter` | str | Yes | Parser | Subchapter label. |
| 18 | `SectionNumber` | str | Yes | Parser | Section number as string, e.g., "SEC. 101." or "576.". Applied corrections override the XML value. Null for Division entries. |
| 19 | `SectionName` | str | Yes | Parser | Section heading text. Null for Division entries. |
| 20 | `DivisionHeadingLevel1` | str | Yes | Parser | Top-level heading+subheading of an appropriations block. Null for Section entries. |
| 21 | `DivisionHeadingLevel2` | str | Yes | Parser | Second-level heading+subheading. |
| 22 | `DivisionHeadingLevel3` | str | Yes | Parser | Third-level heading+subheading. |
| 23 | `Text` | str | Yes | Parser (`get_clean_text`) | Full extracted text of the segment; sidenote, page, footnote, approvedDate content excluded. |
| 24 | `Agencies_Row` | str | Yes | `post_process.add_grouped_agencies()` | Pipe-separated list of agency/bureau names matched in this row's text. "(blank)" if none. |
| 25 | `Agencies_Law` | str | Yes | `post_process.add_grouped_agencies()` | Pipe-separated union of all agencies matched across all rows for this `LawIdentifier`. |
| 26 | `ReviewStatus` | str | No | Publisher | "Pending" on initial output. SMEs update to "Accepted", "Rejected", or "Needs_Discussion". Pre-populated only for `Selection == 1` rows; "N/A" for `Selection == 0` rows. |

### Migration from Current 23-Column Schema

The three new columns are additive. `IsAppropriation` was previously only in the separate `Appropriations_Volume-{vol}.xlsx` file. `ContentHash` is entirely new. `ReviewStatus` is entirely new. No existing columns are renamed or removed. The column order in the output Excel changes to put the three new columns after `KeyVersion` (positions 3, 12, 26).

### Backward Compatibility

The 23 columns that already exist in the current output files in `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/` are unchanged in semantics. Existing SME-curated values in those files are not overwritten unless `--force` is passed to the runner.

---

## 9. Orchestration

### CLI Runner Design

**New file:** `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/run_pipeline.py`

```
Usage:
  run_pipeline.py [OPTIONS]

Options:
  --volumes TEXT        Comma-separated list or range, e.g. "59-137" or "71,72,114".
                        Volumes 1-36 are rejected (out of scope).
  --stages TEXT         Comma-separated stages: ingest,parse,segment,enrich,validate,publish
                        Default: all
  --force               Re-run even if manifest shows volume is current
  --config PATH         Path to config.conf [default: ./config.conf]
  --output-dir DIR      Override local output root.
                        [default: /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/]
                        Cannot point inside /groups/brooksgrp/ (enforced).
  --scratch DIR         Directory for intermediate parquet/json cache files
                        [default: <output-dir>/scratch/]
  --dry-run             Print what would be run without executing
  --log-level TEXT      DEBUG, INFO, WARNING [default: INFO]
```

The runner imports from the stage modules, iterates over the requested volumes, and calls each stage in order. Failures at validate or earlier stop that volume (logged, manifest updated with `status: "failed"`) but do not stop other volumes. A summary table is printed at the end.

### Config.conf Handling

The existing `/home/G39248410/citizen_voice/Code/config.conf` paths must stay pointed at `/groups/brooksgrp/` for production data flow compatibility. The runner reads config once at startup and passes values explicitly to stage functions — no module-level `config.read()`. This resolves the CWD brittleness in `post_process.py` and `tag_appropriations.py`.

### Incremental Re-runs

The manifest (`run_manifest.json`) enables incremental re-runs. A volume is skipped if:
1. Its XML file's SHA-256 matches the manifest entry, AND
2. The existing output Excel exists and its SHA-256 matches the manifest entry, AND
3. `--force` is not set.

### Cache Strategy

Intermediate parquet files are written to a `--scratch` directory (default: `processed_output/scratch/`). The parquet format is chosen over JSON for the intermediate stage because large volumes (STATUTE-114 has 3,831 output rows; older large volumes may have more) benefit from columnar compression.

**Retention policy (per stakeholder decision §15.10):** Parquet files for a volume are **deleted** as soon as that volume's final published Excel has been validated and confirmed error-free. On failure they are retained for debugging until the next successful run. The runner has a `--keep-scratch` flag to override this for ad-hoc investigation.

### Failure Recovery

- A volume that fails at Stage 2 (parse) leaves no output. The existing output for that volume (if any) is preserved. The manifest records `status: "parse_failed"`.
- A volume that fails at Stage 5 (validate) writes a validation report but does not overwrite the existing Excel. The manifest records `status: "validate_failed"` and lists the failing checks.
- A volume that passes all stages updates both the Excel and the manifest atomically.

### Logging

Each stage logs to both the console and a `pipeline.log` file in the scratch directory. Log entries include volume number, stage name, elapsed time, and row counts. The format matches what `Extract_Sections_Divisions_From_XML.py` already uses (`%(asctime)s %(levelname)s %(name)s: %(message)s`).

---

## 10. Validation Plan

### Per-Volume Checks

| Check | Implementation | Failure Mode |
|---|---|---|
| Schema completeness | All 26 columns present | Hard fail — output not written |
| EntryType values | Only "Section" and "Division" | Hard fail |
| UniqueKey uniqueness | `df["UniqueKey"].is_unique` | Hard fail (de-duplication logic in `generate_id_keys.py` already handles this — ensure it raises rather than silently appending suffixes in batch mode) |
| Public-law count | Count distinct `LawIdentifier` values vs. count `<pLaw publicPrivate="public">` in XML | Warning if mismatch > 0 |
| Section row count | At least 1 Section row per distinct LawIdentifier that has a `<main><section>` child | Warning |
| Text non-null rate | At least 80% of rows have non-null, non-empty `Text` | Warning |
| Selection sample size | `Selection.sum()` == min(600, eligible_count) | Warning if < 600 and volume has > 600 eligible rows |
| LawNumber extractability | All `LawIdentifier` values match `\d+-\d+` | Hard fail |

### Regression Assertions

These correspond to the known corrections in `law_id_corrections.py` and `SECTION_NUMBER_CORRECTIONS`. Each correction has a corresponding assertion in `validation/validator.py`:

- Vol 63 output must contain `LawIdentifier == "81-174"` (not "81-175") when `LawTitle` contains "social security"
- Vol 63 output must contain `LawIdentifier == "81-268"` (not "81-208") when `LawTitle` contains "federal crop insurance"
- Vol 63 output must contain `LawIdentifier == "79-466"` (not "79-496")
- Vol 63 output must contain `LawIdentifier == "79-573"` (not "79-673")
- Vol 63 output must contain `LawIdentifier == "79-579"` (not "79-679")
- Vol 63 output must contain `LawIdentifier == "84-663"` (not "84-274")
- Vol 104 output must contain `LawIdentifier == "104-79"` (not "104-9") — note en-dash in raw input
- Vol 114 output for law "106-382" must contain a row with `SectionNumber == "SEC. 6."` and `SectionName` containing "USE OF PICK-SLOAN POWER"
- Vol 114 output for law "106-259" must contain rows with `SectionNumber` in `{"SEC. 8015.", "SEC. 8041."}`
- Vol 114 output for law "106-181" must contain `SectionNumber == "SEC. 128."`
- Vol 112 output for law "98-369" must contain `SectionNumber == "SEC. 734."`

### pytest Expansion Plan

**Existing tests** (`/home/G39248410/citizen_voice/Code/test_law_id_corrections.py`): 11 tests covering `apply_law_id_corrections` (9 parametrized + 2 edge cases) and `apply_section_number_correction` (7 tests). Keep all; move the file to `tests/unit/test_law_id_corrections.py`.

**New test files:**

- `tests/unit/test_appr_parser.py` — unit tests for the extracted `extract_appropriations_block()` function with synthetic XML fragments at 1-, 2-, and 3-level nesting
- `tests/unit/test_segmenter.py` — unit tests for `apply_selection_sampling()` including the fewer-than-600 guard case
- `tests/unit/test_law_id_utils.py` — unit tests for `normalize_law_id()` including en-dash inputs, "Public Law" prefix stripping, and no-match passthrough
- `tests/unit/test_enricher.py` — unit tests for `add_appropriations_flag()` and `add_content_hash()`
- `tests/integration/test_validator.py` — integration tests for `validator.py` using the existing output Excel for Volume-114 as a fixture (read-only access to `/groups/brooksgrp/...`)
- `tests/integration/test_pipeline_vol63.py` — smoke test: run full pipeline on STATUTE-63.xml against a temp output dir and assert the regression cases for known law-ID corrections

---

## 11. SME Curation Handoff

### What SMEs Receive

Each volume produces one Excel file at:
```
/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/Volume-{N}/STATUTE-{N}_{date}.xlsx
```

The SME-relevant subset: rows where `Selection == 1` (600 per volume; per stakeholder decision §15.3 the value is fixed). For convenience, `publisher.write_sme_view()` writes a separate filtered file:
```
/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/Volume-{N}/STATUTE-{N}_{date}_SME.xlsx
```

This file contains only the 600 selected rows, with the full 26 columns, sorted by `Order` (the randomized presentation sequence). The `ReviewStatus` column is pre-populated as "Pending" for all rows.

**Note on delivery:** The eventual delivery format is **Google Sheets** uploaded to a shared Google Drive with SME-specific formatting (per stakeholder decision §15.2). That upload step is a separate future workstream; it is **not** part of this pipeline. This pipeline's job is to produce the local Excel artifacts in the format and shape that the upload workstream will consume.

### How SMEs Record Decisions

SMEs update the `ReviewStatus` column in the Excel to one of:
- `"Accepted"` — the segment is substantively relevant to the citizen voice analysis
- `"Rejected"` — the segment is not relevant
- `"Needs_Discussion"` — SME is uncertain; flags for team discussion

An optional `ReviewerNote` free-text column (27th column, appended by the SME) captures rationale. SMEs do not modify any other columns.

### How Decisions Feed Back

The `UniqueKey` is the stable join key. After SME curation, the pipeline's `publisher.py` module should include a `merge_sme_feedback(volume_xlsx, sme_xlsx)` function that:
1. Reads the SME Excel
2. Left-joins on `UniqueKey` to pull `ReviewStatus` and `ReviewerNote` into the full volume Excel
3. Writes the merged result back to the volume Excel

This preserves all pipeline-generated data and layers SME decisions on top without overwriting. If the pipeline re-runs with `--force` on an already-curated volume, the merge step preserves existing non-"Pending" review statuses.

### Idempotency

The `UniqueKey` is deterministic given identical input XML and `DivisionMapping.xlsx` state. If a volume is re-processed (e.g., because the source XML was updated), any rows whose UniqueKey persists across runs retain their SME review status. New rows (new keys) receive `ReviewStatus = "Pending"`. Deleted rows (keys in the old output but not the new one) are logged as warnings.

### Already-Curated Volumes

Per stakeholder decision §15.7, **already-curated production files are never modified**. The pipeline produces parallel outputs in `processed_output/` for all in-scope volumes (including those already curated in production), but those parallel outputs are not sent for re-labeling. If a future workflow needs to reconcile curated production outputs with this pipeline's re-runs, that diff/merge logic is a separate workstream.

### Format Considerations

The pipeline emits Excel (.xlsx) as its local artifact format. The downstream delivery step (Google Sheets, see §15.2) handles any conversion or formatting tailored to SME ergonomics. The `openpyxl` engine is already installed in the venv.

---

## 12. Implementation Phases

### Phase 1 — Foundation & Workspace (Weeks 1–2)

Goal: establish the new directory structure, bootstrap the `processed_output/` workspace, fix the most dangerous bugs, and ensure existing passing volumes do not regress.

- [ ] Create `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/` directory structure (this file, `run_pipeline.py`, `pipeline/`, `parser/`, `validation/`, `tests/`, `processed_output/`)
- [ ] Create `pipeline/__init__.py`, `parser/__init__.py`, `validation/__init__.py`
- [ ] **Bootstrap `processed_output/`**: copy `AgencyList.xlsx` and `DivisionMapping.xlsx` from `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/` into `processed_output/`; create `processed_output/scratch/` and empty `processed_output/run_manifest.json`
- [ ] Move existing test file to `tests/unit/test_law_id_corrections.py`; confirm `pytest tests/` still passes
- [ ] Fix `config.read()` at import-time in `post_process.py`: wrap `fetch_agency_list()` to accept `datapath` argument; remove module-level config call
- [ ] Fix `config.read()` at import-time in `tag_appropriations.py`: convert to a callable with arguments
- [ ] Extract `extract_appropriations_block()` into `parser/appr_parser.py`; verify all 4 call sites in `Extract_Sections_Divisions_From_XML.py` are replaced and output is byte-for-byte identical on Vol-114 (compared against the production `latest/Volume-114/` file as a read-only reference)
- [ ] Add `normalize_law_id()` to `parser/law_id_utils.py`; add 10 unit tests
- [ ] Add `tests/unit/test_appr_parser.py` with synthetic XML fixtures
- [ ] Add a `--output-dir` guard that rejects any path inside `/groups/brooksgrp/`

**Milestone:** `pytest tests/` green; Vol-114 re-run into `processed_output/` produces identical row count and identical UniqueKeys to the production reference; `/groups/brooksgrp/` is verifiably never opened for write by the new pipeline.

### Phase 2 — Runner and Validation (Weeks 3–4)

Goal: stand up the CLI runner, validate framework, and produce parallel outputs for the volumes already covered in production (59–137 currently in `latest/`).

- [ ] Write `run_pipeline.py` with `--volumes`, `--stages`, `--force`, `--config`, `--output-dir`, `--dry-run` flags
- [ ] Write `pipeline/ingest.py` with `bootstrap_workspace()`, `build_manifest()`, `check_incremental()`
- [ ] Write `validation/validator.py` with all 8 per-volume checks
- [ ] Write `validation/report.py` dataclass and JSON serializer
- [ ] Write `tests/integration/test_validator.py` using Vol-114 as read-only fixture (compare production output against new pipeline output)
- [ ] Run `run_pipeline.py --volumes 59-137` and confirm parallel outputs match the production reference within tolerance (UniqueKey set identical; column count 26 vs production 23 is expected)
- [ ] For volumes 64–69, 90, 101, 104, 113 that are missing from production: produce fresh outputs; add corrections to `law_id_corrections.py` as needed
- [ ] Verify regression assertions pass for all volumes

**Milestone:** All volumes 59–137 (except those missing from the source XML) processed into `processed_output/`; validation green; manifest file populated; zero writes to `/groups/brooksgrp/`.

### Phase 3 — Data Model Extension, SME Handoff & Volumes 37–58 (Weeks 5–6)

Goal: add the three new columns, produce SME view files, complete the enrichment integration, **and backfill volumes 37–58** (per stakeholder decision §15.1, these are expected sooner than originally projected).

- [ ] Add `add_appropriations_flag()` to `pipeline/enricher.py`; deprecate separate `tag_appropriations.py` (keep file, add deprecation warning)
- [ ] Add `add_content_hash()` to `pipeline/enricher.py`; add unit tests
- [ ] Add `ReviewStatus` column to the publisher output
- [ ] Fix `DivisionMapping.xlsx` mutation: load `processed_output/DivisionMapping.xlsx` once at runner start, pass dict through enricher, write atomically at runner end
- [ ] Write `pipeline/publisher.py` with `write_volume_excel()`, `write_sme_view()`, `merge_sme_feedback()`, `update_manifest()` — include the safety guard that refuses output paths under `/groups/brooksgrp/`
- [ ] Re-run all volumes 59–137 through the full 6-stage pipeline; verify 26-column output in `processed_output/`
- [ ] Write `tests/integration/test_pipeline_vol63.py` regression test
- [ ] **Process volumes 37–58**: run `run_pipeline.py --volumes 37-58`; expect parse anomalies (older USLM structure); extend `law_id_corrections.py` and validator regression cases as discoveries land
- [ ] Document any vol-specific quirks discovered in 37–58 in a `processed_output/NOTES.md`

**Milestone:** All volumes 37–137 have 26-column Excel + SME view + manifest entries in `processed_output/`; `ContentHash` and `IsAppropriation` present; tests green.

### Phase 4 — Hardening & Operational Polish (Weeks 7–8)

Goal: harden the pipeline, suppress noisy debug output, and prepare for the eventual Google Sheets upload workstream.

- [ ] Replace the 4 `print("found")` / `print("replaced")` debug statements in `law_id_corrections.py` with `logger.debug()`
- [ ] Add `--log-level DEBUG` integration to runner
- [ ] Performance profile: time Stage 2 on the largest volumes; if STATUTE-63.xml or similar takes > 5 minutes, investigate iterparse or lxml as a drop-in replacement for `xml.etree.ElementTree`
- [ ] Implement scratch-file retention policy: delete `processed_output/scratch/*_{vol}.parquet` once Stage 5 reports the volume as error-free
- [ ] Final pytest run: target 100% pass on all unit and integration tests
- [ ] Confirm `processed_output/DivisionMapping.xlsx` is stable across 10 consecutive full pipeline runs (no spurious new entries on identical input)
- [ ] Author a short `processed_output/HANDOFF.md` describing the file format and column semantics for the Google Sheets upload workstream (next iteration)

**Milestone:** All volumes 37–137 processed cleanly; test suite green; manifest fully populated; scratch files cleaned up; pipeline runs end-to-end in a single command; handoff doc ready for the upload workstream.

### Out of Phase (Deferred / Future Iterations)

- **Volumes 1–36**: out of scope permanently (per §15.1)
- **Google Drive / Google Sheets upload**: separate workstream after this pipeline is functional (per §15.2)
- **Parallel volume processing (`--workers N`)**: deferred to a future iteration (per §15.6)
- **Re-curation of already-curated production volumes**: explicitly excluded (per §15.7)

---

## 13. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Accidental writes to `/groups/brooksgrp/`** (production output or production lookup files) | Medium if guard absent | High (would corrupt curated SME work) | Hard guard in `publisher.py` rejects output paths under `/groups/brooksgrp/`; CI/test asserts no write to that path; only the local `processed_output/` copy of `DivisionMapping.xlsx` is mutated |
| Older volumes (vol 37–63) have different XML structures that cause silent data loss | Medium | High | Stage 5 pLaw count check catches missing laws; regression tests on vol 63 catch regressions; Phase 3 discovery run on vols 37–58 surfaces new parse failures early and feeds them back into `law_id_corrections.py` |
| Volume has fewer than 600 eligible rows for Selection sampling (likely for small early volumes 37–58) | Medium | Medium | Add guard `n = min(600, len(eligible))` in Phase 1; log warning |
| UniqueKey collisions after de-duplication suffix logic (`S` → `S1`, `S2`) | Low | Medium | The existing suffix logic in `generate_id_keys.py` handles this; add a final uniqueness assertion in Stage 5 |
| `processed_output/DivisionMapping.xlsx` drifts from production version over time | Medium | Low | Local copy is the source of truth for this pipeline; if reconciliation is needed, a separate diff utility can compare against the read-only production file. No silent overwrite either way. |
| GovInfo changes its XML API or bulk data URL structure | Low | High | XMLs are pre-positioned in the shared read-only source; pipeline operates on what's on disk and is unaffected unless a refresh is requested |
| `AgencyList.xlsx` substring matching produces false positives for common English words | Medium | Medium | Not in scope to redesign the matcher; log the match rate per volume; flag to stakeholders if > 90% of rows match an agency |
| The 81-207 hardcoded correction (currently inlined at Extract_...py line 641) is missed during module split | High if not caught | Medium | Phase 1 migration test: re-run Vol-81 before and after refactoring and assert identical UniqueKeys |
| SME Excel edits are lost when pipeline re-runs with `--force` | High if not handled | High | Phase 3 `merge_sme_feedback()` preserves non-Pending review statuses; document clearly in handoff guide. Already-curated production files are protected by the never-write-to-`/groups/brooksgrp/` rule. |

---

## 14. File Inventory

### Files to Create

| File | Purpose |
|---|---|
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/PLAN.md` | This document |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/run_pipeline.py` | CLI orchestration runner; accepts `--volumes`, `--stages`, `--force`, `--config`, `--dry-run` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/__init__.py` | Package marker |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/ingest.py` | `build_manifest()`, `check_incremental()`, wraps `scrape_and_download_gpo.py` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/segmenter.py` | `build_dataframe()`, `apply_selection_sampling()`, `assign_original_order()` — extracted from `create_xlsx_output_from_json()` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/enricher.py` | `add_agency_tags()`, `add_appropriations_flag()`, `add_content_hash()`, `add_unique_keys()` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/publisher.py` | `write_volume_excel()`, `write_sme_view()`, `merge_sme_feedback()`, `update_manifest()` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/parser/__init__.py` | Package marker |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/parser/uslm_parser.py` | `extract_public_law_from_uslm()`, `get_clean_text()`, `extract_section_text()`, `process_section()` — extracted from the monolith |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/parser/appr_parser.py` | `extract_appropriations_block()` — consolidates 4 duplicated loops |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/parser/law_id_utils.py` | `normalize_law_id()`; imports from and defers corrections to `law_id_corrections.py` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/validation/__init__.py` | Package marker |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/validation/validator.py` | All 8 per-volume checks + 11 regression assertions |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/validation/report.py` | `ValidationReport` dataclass + JSON serializer |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/__init__.py` | Package marker |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/unit/test_law_id_corrections.py` | Moved from `/home/G39248410/citizen_voice/Code/test_law_id_corrections.py` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/unit/test_appr_parser.py` | New: unit tests for `extract_appropriations_block()` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/unit/test_segmenter.py` | New: unit tests for sampling logic including edge cases |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/unit/test_law_id_utils.py` | New: unit tests for `normalize_law_id()` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/unit/test_enricher.py` | New: unit tests for `add_appropriations_flag()` and `add_content_hash()` |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/integration/test_validator.py` | New: integration tests using Vol-114 as read-only fixture |
| `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/tests/integration/test_pipeline_vol63.py` | New: end-to-end smoke test on Vol-63 regression cases |

### Files to Modify (in Working Copy)

| File | Change |
|---|---|
| `/home/G39248410/citizen_voice/Code/post_process.py` | Remove module-level `config.read('config.conf')`; add `datapath` parameter to `fetch_agency_list()` |
| `/home/G39248410/citizen_voice/Code/tag_appropriations.py` | Remove module-level config/import-time execution; wrap in `def run(config_path, volumes):`; add deprecation warning |
| `/home/G39248410/citizen_voice/Code/law_id_corrections.py` | Add `normalize_law_id()`; add `INLINE_CORRECTIONS` table for the `81-207` hardcoded case; replace 4 `print("found")`/`print("replaced")` with `logger.debug()`; add `apply_inline_corrections()` |
| `/home/G39248410/citizen_voice/Code/Extract_Sections_Divisions_From_XML.py` | Replace the 4 duplicated appropriations loops with calls to `extract_appropriations_block()`; replace the `81-207` inline correction with a call to `apply_inline_corrections()`; import from new `parser/` modules as they are extracted (incremental) |
| `/home/G39248410/citizen_voice/Code/generate_id_keys.py` | Remove hardcoded `if not any(str(v) in str(filename) for v in [70]):` filter; accept division mapper dict as argument in `generate_and_process_id()`; remove the file-write of `DivisionMapping.xlsx` from this function (move to publisher) |
| `/home/G39248410/citizen_voice/Code/config.conf` | No change to paths; add `[Pipeline]` section with `scratch_dir`, `manifest_path` defaults |

### Files to Retire (after Phase 3)

| File | Reason |
|---|---|
| `/home/G39248410/citizen_voice/Code/tag_appropriations.py` | Functionality integrated into `enricher.add_appropriations_flag()`; kept with deprecation notice but removed from active pipeline invocation |

### Files Preserved As-Is

| File | Reason |
|---|---|
| `/home/G39248410/citizen_voice/Code/scrape_gpo.py` | Used by `ingest.py` as a library; no changes needed |
| `/home/G39248410/citizen_voice/Code/scrape_and_download_gpo.py` | Used by `ingest.py` as a library; no changes needed |
| `/home/G39248410/citizen_voice/Code/law_id_corrections.py` | Primary corrections table; modifications are additive only |
| `/home/G39248410/citizen_voice/Code/config.conf` | Source data paths unchanged; add `[Pipeline]` section pointing at the local output dir |

### Files NEVER Modified (Read-Only References)

| File / Directory | Reason |
|---|---|
| `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/STATUTE-*.xml` | Source XML; pipeline reads only |
| `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/AgencyList.xlsx` | Copied once into `processed_output/` on first run; production copy untouched |
| `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/DivisionMapping.xlsx` | Copied once into `processed_output/` on first run; production copy untouched |
| `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/Volume-*/` | Production curated outputs; read-only reference for regression comparison only |

### Runtime Output Layout (`processed_output/`)

The pipeline materializes the following structure on first run via `bootstrap_workspace()`:

```
/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/
├── AgencyList.xlsx                                   # copied from source XML dir
├── DivisionMapping.xlsx                              # copied from source XML dir; mutated locally
├── run_manifest.json                                 # input XML hash + output hash per volume
├── HANDOFF.md                                        # written in Phase 4; column semantics for Google Sheets upload workstream
├── NOTES.md                                          # parse anomalies log (filled during Phase 3 for vols 37–58)
├── scratch/                                          # intermediate parquet/json; deleted on success
│   ├── raw_records_{vol}.parquet
│   ├── segmented_{vol}.parquet
│   ├── enriched_{vol}.parquet
│   └── validation_report_{vol}.json
└── Volume-{N}/
    ├── STATUTE-{N}_{date}.xlsx                       # full 26-column output
    └── STATUTE-{N}_{date}_SME.xlsx                   # filtered view (Selection==1, 600 rows max)
```

---

## 15. Stakeholder Decisions

The questions raised in the v1 draft have been resolved. All 10 are recorded here as decisions so future readers can see the rationale without needing the original conversation. Add new open items at the bottom as they arise.

### 15.1 Volume coverage

**Decision:** Volumes **1–36 are permanently out of scope** (not part of the GovInfo download set this project consumes). Volumes **37–58** are lower priority but expected to be processed in the near term. The implementation plan promotes them from Phase 4 (v1 draft) to **Phase 3** in this revision.

### 15.2 SME delivery format

**Decision:** Final delivery is **Google Sheets uploaded to a shared Google Drive** with SME-specific formatting that makes per-section labeling ergonomic. That integration is a **separate workstream** to be undertaken after this pipeline is functional. This pipeline produces local Excel artifacts (`processed_output/Volume-{N}/STATUTE-{N}_{date}_SME.xlsx`) that the upload workstream will consume.

### 15.3 Selection sample size

**Decision:** **600 rows per volume**, fixed. No change. (The fewer-than-600 guard in Phase 1 still applies for small volumes — it caps at `min(600, eligible)` and logs a warning.)

### 15.4 Private Laws

**Decision:** **Permanently excluded.** The existing `publicPrivate == "public"` filter is correct and must be preserved. No separate Private-Laws output table.

### 15.5 Lookup file location and mutation

**Decision:** Copy `AgencyList.xlsx` and `DivisionMapping.xlsx` from `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/` into `processed_output/` on first run. The pipeline mutates **only** the local copies. The production files at `/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06/` are **never** modified by this pipeline.

> **Note on filename:** The stakeholder reply mentioned "AgencyMapping.xlsx"; the actual file in the production directory is **`AgencyList.xlsx`**. This plan uses the real filename throughout. Flag if the stakeholder intended a different file.

### 15.6 Parallel volume processing

**Decision:** **Deferred** to a future iteration after the present sequential pipeline is implemented, verified, and stable. Tracked in §12 "Out of Phase".

### 15.7 Re-processing already-curated volumes

**Decision:** **Never modify already-curated production files.** Labelling is a significant labor effort and curated outputs must be protected. The pipeline writes only to local `processed_output/`; production `latest/Volume-*/` is read-only. This naturally protects curated work — it is never overwritten because it is never touched. If parallel outputs for already-curated volumes are produced in `processed_output/` (e.g., during a coverage run), they are not sent for re-labeling.

### 15.8 Selection method

**Decision:** **Random sampling retained as-is** (with the existing exclusion filters: short-title, table-of-contents, sense-of-congress, sunset, severability, and CRA-disapproval-resolution patterns). Seed is `42` for reproducibility.

### 15.9 Output directory

**Decision:** Pipeline writes only to `/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/`. The production output directory `/groups/brooksgrp/citizen_voice/python_output/statutes_broken_into_sections/latest/` is **read-only** to this pipeline. A safety guard in `publisher.py` rejects any output path under `/groups/brooksgrp/`.

### 15.10 Intermediate parquet retention

**Decision:** Delete `processed_output/scratch/*_{vol}.parquet` once the corresponding published Excel for that volume has been validated and confirmed error-free. Implemented in Phase 4. A `--keep-scratch` runner flag overrides this when needed for ad-hoc debugging.

---

### Remaining Open Questions

*None at this time. As the pipeline is implemented, new questions surfaced by Phase 2/3 discovery runs (especially for legacy volumes 37–58) will be appended here for stakeholder resolution.*

---

*End of PLAN.md (v2)*
