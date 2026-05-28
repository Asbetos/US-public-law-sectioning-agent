"""CLI: re-publish volumes affected by an implemented correction."""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Pattern-keyword -> validation-warning-keyword map. All comparisons are
# lower-cased. The left list contains substrings matched against the entry's
# trigger.pattern (or correction.description fallback); the right list contains
# substrings matched against each volume's validation warnings.
_PATTERN_TO_WARNING_KEYWORDS = [
    # Null-SectionNumber family (#2, #14, #15, #16)
    (["sectionnumber is null", "outer <section>", "unnumbered opening",
      "no <num>", "without appropriate num", "lacking <num>"],
     ["duplicate uniquekey rows"]),
    # No-top-level-<section> family (#3, #7, #11, #17)
    (["no top-level <section>", "<main> contains <part>", "<main> contains <title>",
      "<main> contains <chapter>", "<main> contains <quotedContent>",
      "zero top-level <section>", "bare <subsection>"],
     ["distinct lawidentifier count"]),
    # Sibling appropriations (#5)
    (["sibling <appropriations>"], ["duplicate uniquekey rows"]),
    # Sibling <level> (#13)
    (["sibling <level>"], ["duplicate uniquekey rows"]),
]


def _identify_affected_volumes(entry, *, scratch_dir):
    """Identify volumes affected by an entry.

    Walks ``scratch_dir`` for ``validation_report_<N>.json`` files whose
    warnings array contains any of the entry's mapped warning keywords. Always
    includes ``entry['discovered_in_vol']`` if numeric.
    """
    pattern = (entry.get("trigger", {}).get("pattern") or "").lower()
    if not pattern:
        pattern = (entry.get("correction", {}).get("description") or "").lower()

    needles: list[str] = []
    for pat_keys, warn_keys in _PATTERN_TO_WARNING_KEYWORDS:
        if any(pk.lower() in pattern for pk in pat_keys):
            needles.extend(wk.lower() for wk in warn_keys)

    matched: set[int] = set()

    disc = entry.get("discovered_in_vol")
    if disc is not None:
        try:
            matched.add(int(disc))
        except (TypeError, ValueError):
            pass

    if needles and scratch_dir.exists():
        for report in scratch_dir.glob("validation_report_*.json"):
            stem_tail = report.stem.split("_")[-1]
            try:
                vol = int(stem_tail)
            except ValueError:
                continue
            try:
                d = json.loads(report.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            warnings = d.get("warnings", []) or d.get("validation_warnings", [])
            if not isinstance(warnings, list):
                continue
            text = " ".join(str(w) for w in warnings).lower()
            if any(n in text for n in needles):
                matched.add(vol)

    return sorted(matched)


def _load_entry(output_dir, entry_id):
    """Return the entry dict from active_corrections.json or None."""
    path = Path(output_dir) / "active_corrections.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    for e in data.get("entries", []) or []:
        if e.get("id") == entry_id:
            return e
    return None


def _clear_volume_dir(vol_dir: Path) -> None:
    """Remove all files (and the directory itself) for a given volume."""
    if not vol_dir.exists():
        return
    for child in vol_dir.iterdir():
        if child.is_dir():
            # nested subdirs: best-effort recursive cleanup
            for sub in child.rglob("*"):
                if sub.is_file():
                    sub.unlink()
            for sub in sorted(
                (p for p in child.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts), reverse=True,
            ):
                sub.rmdir()
            child.rmdir()
        else:
            child.unlink()
    vol_dir.rmdir()


def _clear_manifest_entry(manifest_path: Path, vol: int) -> None:
    """Remove status/output/sme/last_run fields from manifest entry for vol."""
    if not manifest_path.exists():
        return
    try:
        m = json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        return
    entry = (m.get("volumes") or {}).get(str(vol))
    if not entry:
        return
    for k in ("output_path", "output_sha256", "sme_path", "status", "last_run"):
        entry.pop(k, None)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(json.dumps(m, indent=2, sort_keys=True))
    tmp.replace(manifest_path)


def _republish_volume(vol, output_dir, source_xml_dir):
    log = logging.getLogger("re-publish")
    output_dir = Path(output_dir)
    source_xml_dir = Path(source_xml_dir)

    vol_dir = output_dir / f"Volume-{vol}"
    try:
        _clear_volume_dir(vol_dir)
    except OSError as exc:
        log.error("Failed to clear %s: %s", vol_dir, exc)
        return False

    _clear_manifest_entry(output_dir / "run_manifest.json", vol)

    rc = subprocess.call(
        [
            "python", "run_pipeline.py", "--volumes", str(vol),
            "--stop-before-publish",
            "--source-xml-dir", str(source_xml_dir),
            "--output-dir", str(output_dir),
        ],
        cwd=str(_HERE),
    )
    if rc != 0:
        log.error("run_pipeline failed for vol %d (rc=%d)", vol, rc)
        return False

    rc = subprocess.call(
        [
            "python", "apply_corrections_and_publish.py",
            "--volume", str(vol), "--include-pending",
            "--output-dir", str(output_dir),
        ],
        cwd=str(_HERE),
    )
    if rc != 0:
        log.error("apply_corrections_and_publish failed for vol %d (rc=%d)", vol, rc)
        return False

    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entry", type=int, required=True,
                        help="active_corrections.json entry id to re-publish")
    parser.add_argument("--output-dir", default=str(_HERE / "processed_output"))
    parser.add_argument(
        "--source-xml-dir",
        default="/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06",
    )
    parser.add_argument("--yes", action="store_true",
                        help="skip interactive confirmation")
    parser.add_argument("--dry-run", action="store_true",
                        help="print plan and exit without re-publishing")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")
    log = logging.getLogger("re-publish")

    output_dir = Path(args.output_dir).resolve()
    entry = _load_entry(output_dir, args.entry)
    if not entry:
        log.error("Entry #%d not in active_corrections.json", args.entry)
        return 2

    status = entry.get("implementation_status")
    if status not in ("implemented", "manual_override"):
        log.error(
            "Entry #%d has implementation_status=%r; expected 'implemented' or 'manual_override'",
            args.entry, status,
        )
        return 2

    vols = _identify_affected_volumes(entry, scratch_dir=output_dir / "scratch")
    if not vols:
        log.info("No affected volumes for entry #%d.", args.entry)
        return 0

    print(f"\nEntry #{args.entry}: affected volumes: {vols}")
    if args.dry_run:
        print("(dry-run; nothing re-published)")
        return 0

    if not args.yes:
        try:
            ans = input(f"\nRe-publish these {len(vols)} volumes? [y/N]: ").strip().lower()
        except EOFError:
            ans = ""
        if ans != "y":
            print("Aborted.")
            return 1

    failed = []
    for v in vols:
        log.info("Re-publishing vol %d...", v)
        if not _republish_volume(v, output_dir, Path(args.source_xml_dir)):
            failed.append(v)

    if failed:
        log.error("Failed: %s", failed)
        return 1

    log.info("All %d volumes re-published.", len(vols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
