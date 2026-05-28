"""Resume a volume's publication step from a `--stop-before-publish` checkpoint.

Reads ``processed_output/scratch/enriched_<vol>.parquet``, applies any
dynamic corrections (approved entries from ``active_corrections.json`` plus
pending proposals from ``pending_corrections.json`` that the operator has
chosen to include via ``--include-pending``), then publishes via the
existing publisher. Manifest provenance is recorded so the volume's output
is tied to the exact rule set that was applied.

Typical use is from the cv-correct Claude Code skill, run *after* the
subagent has had a chance to write proposals to the pending queue.

Usage:
    python apply_corrections_and_publish.py --volume 114
    python apply_corrections_and_publish.py --volume 114 --include-pending
    python apply_corrections_and_publish.py --volume 114 --keep-scratch
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from pipeline.corrections_registry import CorrectionEntry, CorrectionsRegistry  # noqa: E402
from pipeline.publisher import publish  # noqa: E402

DEFAULT_OUTPUT_DIR = _HERE / "processed_output"


def _apply_law_id_rules(df: pd.DataFrame, rules: list[tuple[str, str, str]]) -> int:
    """Apply law-id corrections in place. Returns the number of row mutations."""
    if not rules or df.empty or "LawIdentifier" not in df.columns:
        return 0
    mutations = 0
    title_lower = df["LawTitle"].fillna("").astype(str).str.lower()
    for match_id, match_title, replacement in rules:
        match_title_lower = match_title.lower()
        mask = (
            df["LawIdentifier"].astype(str).str.contains(match_id, regex=False, na=False)
            & title_lower.str.contains(match_title_lower.replace("(", r"\(").replace(")", r"\)"), regex=True, na=False)
        )
        n = int(mask.sum())
        if n > 0:
            df.loc[mask, "LawIdentifier"] = replacement
            mutations += n
    return mutations


def _dedupe_unique_keys(df: pd.DataFrame) -> int:
    """Append a numeric suffix to repeated UniqueKey values so the published
    Excel has no collisions. Deterministic given the row order (which is the
    segmenter's sort order: LawNumber, counter). Returns the count of rows
    whose key was suffixed.
    """
    if "UniqueKey" not in df.columns or df.empty:
        return 0
    cumcount = df.groupby("UniqueKey").cumcount()
    suffix_mask = cumcount > 0
    if not suffix_mask.any():
        return 0
    df.loc[suffix_mask, "UniqueKey"] = (
        df.loc[suffix_mask, "UniqueKey"].astype(str)
        + "-"
        + cumcount[suffix_mask].astype(str)
    )
    return int(suffix_mask.sum())


def _apply_section_number_rules(
    df: pd.DataFrame,
    rules: list[tuple[str, str, str | None, str]],
) -> int:
    """Apply section-number corrections in place. Returns row mutations."""
    if not rules or df.empty or "SectionNumber" not in df.columns:
        return 0
    mutations = 0
    heading_lower = df["SectionName"].fillna("").astype(str).str.lower()
    text_lower = df["Text"].fillna("").astype(str).str.lower()
    law_id = df["LawIdentifier"].astype(str)
    for match_id, match_heading, match_text, replacement in rules:
        mask = (
            law_id.str.contains(match_id, regex=False, na=False)
            & heading_lower.str.contains(match_heading.lower(), regex=False, na=False)
        )
        if match_text is not None:
            mask = mask & text_lower.str.contains(match_text.lower(), regex=False, na=False)
        n = int(mask.sum())
        if n > 0:
            df.loc[mask, "SectionNumber"] = replacement
            mutations += n
    return mutations


def _pending_to_rules(pending: list[CorrectionEntry]):
    """Split pending entries into (law_id_rules, section_number_rules)."""
    law_id_rules: list[tuple[str, str, str]] = []
    section_rules: list[tuple[str, str, str | None, str]] = []
    pending_ids_used: set[int] = set()
    for e in pending:
        if e.status != "pending":
            continue
        if e.type == "law_id":
            law_id_rules.append((
                e.trigger.get("law_id_substring", ""),
                e.trigger.get("title_substring", ""),
                e.correction.get("replace_with_law_id", ""),
            ))
            pending_ids_used.add(e.id)
        elif e.type == "section_number":
            section_rules.append((
                e.trigger.get("law_id_substring", ""),
                e.trigger.get("heading_substring", ""),
                e.trigger.get("text_substring"),
                e.correction.get("replace_with_section_number", ""),
            ))
            pending_ids_used.add(e.id)
    return law_id_rules, section_rules, pending_ids_used


def _cleanup_scratch(output_dir: Path, vol: int) -> None:
    scratch = output_dir / "scratch"
    for name in (f"enriched_{vol}.parquet",
                 f"raw_records_{vol}.parquet",
                 f"segmented_{vol}.parquet"):
        p = scratch / name
        if p.exists():
            p.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--volume", type=int, required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--include-pending", action="store_true",
        help="Apply pending proposals (not just approved active rules). The skill "
             "workflow passes this; manual replays usually don't.",
    )
    parser.add_argument(
        "--force-republish", action="store_true",
        help="Override the publisher's hard-freeze guard. Required if the "
             "volume already has a published main Excel.",
    )
    parser.add_argument(
        "--keep-scratch", action="store_true",
        help="Don't delete the enriched parquet checkpoint after a successful publish.",
    )
    parser.add_argument(
        "--manifest", default=None,
        help="Manifest path (default: <output-dir>/run_manifest.json).",
    )
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("apply_corrections")

    output_dir = Path(args.output_dir).expanduser().resolve()
    manifest_path = Path(args.manifest) if args.manifest else output_dir / "run_manifest.json"

    checkpoint = output_dir / "scratch" / f"enriched_{args.volume}.parquet"
    if not checkpoint.exists():
        log.error(
            "Checkpoint not found: %s. Run `python run_pipeline.py --volumes %d "
            "--stop-before-publish` first.",
            checkpoint, args.volume,
        )
        return 2

    log.info("Loading checkpoint: %s", checkpoint)
    df = pd.read_parquet(checkpoint)
    log.info("Loaded %d rows", len(df))

    registry = CorrectionsRegistry(output_dir)
    registry_hash = registry.registry_hash()

    # Active rules include the static seed already applied at parse time;
    # rules promoted from pending live in active_corrections.json.
    active_law_id_rules = [
        (e.trigger.get("law_id_substring", ""),
         e.trigger.get("title_substring", ""),
         e.correction.get("replace_with_law_id", ""))
        for e in registry.all_active_entries()
        if e.type == "law_id" and e.status == "approved"
    ]
    active_section_rules = [
        (e.trigger.get("law_id_substring", ""),
         e.trigger.get("heading_substring", ""),
         e.trigger.get("text_substring"),
         e.correction.get("replace_with_section_number", ""))
        for e in registry.all_active_entries()
        if e.type == "section_number" and e.status == "approved"
    ]
    active_ids = [e.id for e in registry.all_active_entries() if e.status == "approved"]

    pending_law_id_rules: list = []
    pending_section_rules: list = []
    pending_ids: list[int] = []
    if args.include_pending:
        pl, ps, pids = _pending_to_rules(registry.all_pending_entries())
        pending_law_id_rules, pending_section_rules = pl, ps
        pending_ids = sorted(pids)

    n_law_id = _apply_law_id_rules(df, active_law_id_rules + pending_law_id_rules)
    n_section = _apply_section_number_rules(df, active_section_rules + pending_section_rules)
    log.info(
        "Applied %d active law-id rules + %d active section rules%s; mutated %d law-id cells and %d section cells.",
        len(active_law_id_rules), len(active_section_rules),
        f" (+ {len(pending_law_id_rules)} pending law-id + {len(pending_section_rules)} pending section rules)" if args.include_pending else "",
        n_law_id, n_section,
    )

    n_suffixed = _dedupe_unique_keys(df)
    if n_suffixed:
        log.info(
            "Suffixed %d UniqueKey collision(s) to make the published Excel unique.",
            n_suffixed,
        )

    formatted_time = datetime.now().strftime("%Y-%m-%d-%HH-%MM-%SS")
    try:
        result = publish(
            df,
            output_dir,
            args.volume,
            manifest_path=manifest_path,
            formatted_time=formatted_time,
            force_republish=args.force_republish,
            corrections_applied={
                "active": active_ids,
                "pending": pending_ids,
            },
            corrections_registry_hash=registry_hash,
        )
    except FileExistsError as e:
        log.error("%s", e)
        return 3
    log.info("Published: %s", result["output_path"])

    if not args.keep_scratch:
        _cleanup_scratch(output_dir, args.volume)

    return 0


if __name__ == "__main__":
    sys.exit(main())
