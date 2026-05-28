"""Operator CLI to append rows to the local ``AgencyList.xlsx``.

The pipeline reads agencies from ``processed_output/AgencyList.xlsx`` at run
time. This script lets you add new entries between runs without touching
the production lookup file.

Examples::

    # Single agency
    python add_agencies.py --agency "Department of Health and Human Services"

    # Single bureau under an existing agency (the matcher unions both columns,
    # so it's fine to record just the bureau)
    python add_agencies.py --bureau "Bureau of Indian Affairs"

    # Paired agency + bureau in one row
    python add_agencies.py --agency "Department of the Interior" \\
                          --bureau "Bureau of Land Management"

    # Bulk from a CSV with columns Agency,Bureau
    python add_agencies.py --from-csv extra_agencies.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from pipeline.enricher import add_agencies  # noqa: E402

DEFAULT_OUTPUT_DIR = _HERE / "processed_output"


def _entries_from_csv(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        # Accept any column-case; map to the canonical Agency / Bureau names.
        field_map = {name.strip().lower(): name for name in reader.fieldnames}
        agency_key = field_map.get("agency")
        bureau_key = field_map.get("bureau")
        if not agency_key and not bureau_key:
            raise SystemExit(
                f"{csv_path}: expected at least one of 'Agency' or 'Bureau' columns "
                f"(found {reader.fieldnames})"
            )
        out: list[dict] = []
        for row in reader:
            out.append({
                "Agency": row.get(agency_key) if agency_key else None,
                "Bureau": row.get(bureau_key) if bureau_key else None,
            })
        return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Directory containing AgencyList.xlsx (default: processed_output/)")
    parser.add_argument("--agency", action="append", default=[],
                        help="Agency name to add. Can be repeated.")
    parser.add_argument("--bureau", action="append", default=[],
                        help="Bureau name to add. Can be repeated. If used with --agency, "
                             "the i-th --agency is paired with the i-th --bureau (shorter "
                             "list is null-padded).")
    parser.add_argument("--from-csv", type=Path, default=None,
                        help="CSV file with Agency,Bureau columns to bulk-load.")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")
    log = logging.getLogger("add_agencies")

    entries: list[dict] = []
    if args.from_csv:
        entries.extend(_entries_from_csv(args.from_csv))

    # Pair up parallel --agency / --bureau lists; null-pad the shorter side.
    if args.agency or args.bureau:
        n = max(len(args.agency), len(args.bureau))
        agencies = args.agency + [None] * (n - len(args.agency))
        bureaus = args.bureau + [None] * (n - len(args.bureau))
        for a, b in zip(agencies, bureaus):
            entries.append({"Agency": a, "Bureau": b})

    if not entries:
        log.error("Nothing to add. Pass at least one of --agency / --bureau / --from-csv.")
        return 2

    added = add_agencies(args.output_dir, entries)
    skipped = len(entries) - added
    log.info("Added %d new agency rows (skipped %d already present / empty).", added, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
