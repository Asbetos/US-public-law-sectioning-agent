"""One-time seed of local lookup files from the production source dir.

The pipeline treats ``processed_output/AgencyList.xlsx`` and
``processed_output/DivisionMapping.xlsx`` as the source of truth and never
reads back from production. New installs need to seed those files once:

    python seed_lookup_files.py

Re-running is safe — existing local files are NEVER overwritten. To force a
re-seed, delete the local file first (only do this if you have backed up
any local additions).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from pipeline.ingest import bootstrap_workspace  # noqa: E402

DEFAULT_OUTPUT_DIR = _HERE / "processed_output"
DEFAULT_SOURCE_DIR = Path("/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06")
LOOKUP_FILES = ("AgencyList.xlsx", "DivisionMapping.xlsx")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--source-xml-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")
    log = logging.getLogger("seed_lookup_files")

    result = bootstrap_workspace(args.output_dir, args.source_xml_dir, lookup_files=LOOKUP_FILES)
    if result["copied"]:
        log.info("Seeded: %s", ", ".join(result["copied"]))
    else:
        log.info("All lookup files already present locally; nothing to seed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
