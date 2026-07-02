"""CLI runner for the citizen_voice statutes pipeline.

Usage:
    python run_pipeline.py --volumes 70,114
    python run_pipeline.py --volumes 37-137
    python run_pipeline.py --volumes 114 --force
    python run_pipeline.py --volumes 67 --dry-run

The runner never writes to ``/groups/brooksgrp/``. A safety guard rejects any
output dir that resolves under that prefix.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Make sibling packages + the in-repo legacy/ extractor modules importable regardless of CWD.
_HERE = Path(__file__).resolve().parent
_LEGACY_DIR = _HERE / "legacy"  # original extractor modules, now vendored in this repo
for p in (str(_HERE), str(_LEGACY_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from parser.uslm_parser import extract_public_law_from_uslm  # noqa: E402
from pipeline.ingest import (  # noqa: E402
    bootstrap_workspace,
    build_manifest,
    check_incremental,
    update_volume_status,
)
from pipeline.segmenter import segment  # noqa: E402
from pipeline.enricher import enrich  # noqa: E402
from pipeline.publisher import publish, _check_safe_output  # noqa: E402
from validation.validator import run_all_validations  # noqa: E402

DEFAULT_SOURCE_XML_DIR = "/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06"
DEFAULT_OUTPUT_DIR = str(_HERE / "processed_output")
DEFAULT_KEEP_SCRATCH = False


def parse_volumes(spec: str) -> list[int]:
    """Parse '37-137' or '70,71,114' into a sorted list of ints. Rejects vols <37 (out of scope)."""
    if not spec:
        return []
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    rejected = sorted(v for v in out if v < 37)
    if rejected:
        raise ValueError(f"Volumes <37 are out of scope; rejected: {rejected}")
    return sorted(out)


def process_volume(
    vol: int,
    *,
    source_xml_dir: str,
    output_dir: str,
    manifest_path: Path,
    formatted_time: str,
    force: bool = False,
    stop_before_publish: bool = False,
) -> dict:
    """Run all stages for one volume. Returns a status dict; never raises."""
    log = logging.getLogger(f"vol{vol}")
    xml_path = Path(source_xml_dir) / f"STATUTE-{vol}.xml"

    if not xml_path.exists():
        log.error("XML not found at %s", xml_path)
        update_volume_status(manifest_path, vol, status="missing_xml")
        return {"vol": vol, "status": "missing_xml"}

    if not force and check_incremental(vol, manifest_path, source_xml_dir):
        log.info("Manifest current; skipping (use --force to re-run)")
        return {"vol": vol, "status": "skipped"}

    t0 = time.time()

    try:
        log.info("Parsing %s", xml_path.name)
        raw_records = extract_public_law_from_uslm(str(xml_path), str(vol))
    except Exception:
        log.exception("Extraction failed")
        update_volume_status(manifest_path, vol, status="parse_failed")
        return {"vol": vol, "status": "parse_failed"}

    try:
        log.info("Segmenting (%d sections, %d divisions)",
                 len(raw_records.get("Sections", [])), len(raw_records.get("Divisions", [])))
        df = segment(raw_records)
        log.info("Enriching (%d rows)", len(df))
        df = enrich(df, output_dir, vol=vol, source_xml_dir=source_xml_dir, version=formatted_time)
    except Exception:
        log.exception("Segmentation/enrichment failed")
        update_volume_status(manifest_path, vol, status="enrich_failed")
        return {"vol": vol, "status": "enrich_failed"}

    # Add ReviewStatus before validation so the validator sees all 26 columns.
    # Publisher safety-net (_ensure_review_status) preserves this if already set.
    if "ReviewStatus" not in df.columns:
        df["ReviewStatus"] = df["Selection"].apply(lambda s: "Pending" if int(s) == 1 else "N/A")

    log.info("Validating")
    report = run_all_validations(df, vol, str(xml_path))
    report_path = Path(output_dir) / "scratch" / f"validation_report_{vol}.json"
    report.to_file(report_path)

    if report.warnings:
        for w in report.warnings:
            log.warning("  warn: %s", w)

    if report.status == "failed":
        for f in report.failed:
            log.error("  fail: %s", f)
        update_volume_status(
            manifest_path, vol,
            status="validate_failed",
            validation_report=str(report_path),
        )
        return {"vol": vol, "status": "validate_failed", "failures": report.failed}

    if stop_before_publish:
        checkpoint = Path(output_dir) / "scratch" / f"enriched_{vol}.parquet"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(checkpoint, index=False)
        elapsed = time.time() - t0
        log.info(
            "STOPPED before publish in %.1fs (%d rows, %d laws) -> %s",
            elapsed, report.row_count, report.law_count, checkpoint,
        )
        update_volume_status(
            manifest_path, vol,
            status="ready_for_publish",
            checkpoint_path=str(checkpoint),
            validation_report=str(report_path),
        )
        return {
            "vol": vol,
            "status": "ready_for_publish",
            "elapsed": elapsed,
            "checkpoint_path": str(checkpoint),
            "validation_report": str(report_path),
        }

    try:
        log.info("Publishing")
        publish_result = publish(
            df, output_dir, vol,
            manifest_path=manifest_path,
            formatted_time=formatted_time,
            force_republish=force,
        )
    except Exception:
        log.exception("Publication failed")
        update_volume_status(manifest_path, vol, status="publish_failed")
        return {"vol": vol, "status": "publish_failed"}

    elapsed = time.time() - t0
    log.info("DONE in %.1fs (%d rows, %d laws) -> %s",
             elapsed, report.row_count, report.law_count, publish_result["output_path"])
    return {"vol": vol, "status": "success", "elapsed": elapsed, **publish_result}


def cleanup_scratch(output_dir: str, vol: int, keep: bool) -> None:
    """Per stakeholder decision §15.10, scratch parquet for a volume is removed after success."""
    if keep:
        return
    scratch_dir = Path(output_dir) / "scratch"
    for pat in (f"raw_records_{vol}.parquet",
                f"segmented_{vol}.parquet",
                f"enriched_{vol}.parquet"):
        p = scratch_dir / pat
        if p.exists():
            p.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Citizen Voice statutes pipeline runner")
    parser.add_argument("--volumes", required=True,
                        help="Comma list or range, e.g. '37-137' or '70,71,114'. Vols <37 rejected.")
    parser.add_argument("--source-xml-dir", default=DEFAULT_SOURCE_XML_DIR,
                        help="Read-only source XML dir (default: production XML dir).")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help="Local processed_output dir (must not be under /groups/brooksgrp/).")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if manifest shows volume is current.")
    parser.add_argument("--keep-scratch", action="store_true",
                        help="Keep intermediate parquet files after a successful run.")
    parser.add_argument("--stop-before-publish", action="store_true",
                        help="Run stages 1-5 (parse/segment/enrich/validate) then "
                             "write the enriched DataFrame to "
                             "processed_output/scratch/enriched_<vol>.parquet "
                             "and exit. Used by the cv-correct skill so a Claude "
                             "Code subagent can inspect the data and propose "
                             "corrections before publication.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the volume list and exit.")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("run_pipeline")

    try:
        _check_safe_output(args.output_dir)
    except PermissionError as e:
        log.error("%s", e)
        return 2

    try:
        volumes = parse_volumes(args.volumes)
    except ValueError as e:
        log.error("%s", e)
        return 2

    log.info("Volumes to process: %s", volumes)

    if args.dry_run:
        return 0

    bootstrap_workspace(args.output_dir, args.source_xml_dir)
    manifest_path = Path(args.output_dir) / "run_manifest.json"
    log.info("Refreshing manifest at %s", manifest_path)
    build_manifest(args.source_xml_dir, manifest_path)

    formatted_time = datetime.now().strftime("%Y-%m-%d-%HH-%MM-%SS")
    results: list[dict] = []
    for vol in volumes:
        r = process_volume(
            vol,
            source_xml_dir=args.source_xml_dir,
            output_dir=args.output_dir,
            manifest_path=manifest_path,
            formatted_time=formatted_time,
            force=args.force,
            stop_before_publish=args.stop_before_publish,
        )
        results.append(r)
        if r["status"] == "success":
            cleanup_scratch(args.output_dir, vol, keep=args.keep_scratch)

    # Summary
    log.info("=== run summary ===")
    by_status: dict[str, list[int]] = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["vol"])
    for status in sorted(by_status):
        vs = by_status[status]
        log.info("  %-18s %3d vols  %s", status, len(vs),
                 (str(vs[:10]) + (" ..." if len(vs) > 10 else "")))

    return 0 if not by_status.get("validate_failed") and not by_status.get("parse_failed") else 1


if __name__ == "__main__":
    sys.exit(main())
