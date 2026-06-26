# legacy/ — original extractor modules & GPO scrapers

These are the pre-refactor scripts from before the pipeline was packaged into
`parser/`, `pipeline/`, and `validation/`. They were moved here (from the old
`citizen_voice/Code/` top level) so this repository is **self-contained**.

## Live dependencies (still imported by the pipeline)

Do **not** delete these — the active pipeline imports them:

| Module | Imported by | Provides |
|---|---|---|
| `Extract_Sections_Divisions_From_XML.py` | `parser/uslm_parser.py` | raw USLM section/division extraction |
| `post_process.py` | `pipeline/enricher.py` | agency substring-tagging |
| `generate_id_keys.py` | `pipeline/enricher.py`, `parser/uslm_parser.py` | `UniqueKey` + section-number formatting |

`run_pipeline.py`, `tests/conftest.py`, `pipeline/enricher.py`, and
`parser/uslm_parser.py` add this `legacy/` directory to `sys.path` (via a path
relative to the repo root), so these imports resolve from any checkout
location. The canonical `law_id_corrections.py` lives at the repo root (these
modules import it from there).

## Standalone tools (not imported anywhere)

Run directly if needed; superseded by the packaged pipeline for normal use:

| Script | What it does |
|---|---|
| `scrape_gpo.py` | Scrape the GPO bulk-data "last modified" timeline → an `.xlsx` |
| `scrape_and_download_gpo.py` | Same, plus download the `STATUTE-N.xml` source files |
| `tag_appropriations.py` | Config-driven appropriations tagging (reads `config.conf`) |

`config.conf` and `data/*.xlsx` (scraped GPO timeline spreadsheets) are kept
here for reference. Note: `config.conf` hardcodes cluster paths under
`/groups/brooksgrp/...`; the standalone scripts read `config.conf` relative to
the current working directory, so run them from inside `legacy/` if you need
those settings.
