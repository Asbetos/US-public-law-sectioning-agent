"""Publication stage: write the 26-column Excel; update manifest.

A safety guard refuses any output path under ``/groups/brooksgrp/``. Production
directories there are read-only to this pipeline.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd

_FORBIDDEN_PREFIX = "/groups/brooksgrp/"

FINAL_COLUMN_ORDER = [
    "UniqueKey",
    "KeyVersion",
    "ContentHash",
    "OriginalOrder",
    "EntryType",
    "Selection",
    "Order",
    "LawIdentifier",
    "LawType",
    "LawTitle",
    "approvedDate",
    "IsAppropriation",
    "Division",
    "Title",
    "SubTitle",
    "Chapter",
    "SubChapter",
    "SectionNumber",
    "SectionName",
    "DivisionHeadingLevel1",
    "DivisionHeadingLevel2",
    "DivisionHeadingLevel3",
    "Text",
    "Agencies_Row",
    "Agencies_Law",
    "ReviewStatus",
]


def _check_safe_output(path) -> None:
    """Refuse any path under /groups/brooksgrp/. Resolves symlinks first."""
    resolved = str(Path(path).expanduser().resolve())
    if resolved.startswith(_FORBIDDEN_PREFIX) or resolved == _FORBIDDEN_PREFIX.rstrip("/"):
        raise PermissionError(
            f"Refusing to write under {_FORBIDDEN_PREFIX} (resolved: {resolved}). "
            f"This pipeline writes only to local processed_output/."
        )


def _existing_main_output(output_dir, vol) -> Path | None:
    """Return the path of an already-published main Excel for this volume,
    or None if none exists. The SME view alone is not enough to count as
    published; we look for the 26-col main file."""
    vol_dir = Path(output_dir) / f"Volume-{vol}"
    if not vol_dir.is_dir():
        return None
    for path in sorted(vol_dir.glob(f"STATUTE-{vol}_*.xlsx")):
        if path.name.endswith("_SME.xlsx"):
            continue
        return path
    return None


def _ensure_review_status(df: pd.DataFrame) -> pd.DataFrame:
    """Add ReviewStatus if missing: 'Pending' for Selection==1, 'N/A' otherwise."""
    if "ReviewStatus" in df.columns:
        return df
    df = df.copy()
    df["ReviewStatus"] = df["Selection"].apply(lambda s: "Pending" if int(s) == 1 else "N/A")
    return df


def _ensure_column_order(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex to the canonical 26-column order; missing columns become NaN."""
    return df.reindex(columns=FINAL_COLUMN_ORDER)


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_volume_excel(
    df: pd.DataFrame,
    output_dir,
    vol,
    formatted_time: str | None = None,
) -> Path:
    """Write the full 26-column Excel for one volume, atomically.

    Returns the resolved output path.
    """
    output_dir = Path(output_dir)
    _check_safe_output(output_dir)
    if formatted_time is None:
        formatted_time = datetime.now().strftime("%d-%m-%Y-%HH-%MM-%SS")

    df = _ensure_review_status(df)
    df = _ensure_column_order(df)

    out_dir = output_dir / f"Volume-{vol}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"STATUTE-{vol}_{formatted_time}.xlsx"
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    df.to_excel(tmp, index=False, engine="openpyxl")
    tmp.replace(out_path)
    return out_path


def write_sme_view(
    df: pd.DataFrame,
    output_dir,
    vol,
    formatted_time: str | None = None,
) -> Path:
    """Write the SME view: only Selection==1 rows, sorted by Order."""
    output_dir = Path(output_dir)
    _check_safe_output(output_dir)
    if formatted_time is None:
        formatted_time = datetime.now().strftime("%d-%m-%Y-%HH-%MM-%SS")

    df = _ensure_review_status(df)
    df = _ensure_column_order(df)
    sme_df = df.loc[df["Selection"] == 1].sort_values("Order")

    out_dir = output_dir / f"Volume-{vol}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"STATUTE-{vol}_{formatted_time}_SME.xlsx"
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    sme_df.to_excel(tmp, index=False, engine="openpyxl")
    tmp.replace(out_path)
    return out_path


def publish(
    df: pd.DataFrame,
    output_dir,
    vol,
    manifest_path=None,
    formatted_time: str | None = None,
    *,
    force_republish: bool = False,
    corrections_applied: dict | None = None,
    corrections_registry_hash: str | None = None,
) -> dict:
    """Write the volume Excel; update manifest if a path is given.

    Refuses to write if a main Excel for this volume already exists
    (``hard freeze`` per PLAN §15.7), unless ``force_republish=True``. To
    intentionally replace a published volume, delete its Volume-N directory
    and its ``run_manifest.json`` entry, then re-run.

    ``corrections_applied`` and ``corrections_registry_hash`` are recorded
    into the manifest entry when present (manifest provenance per PLAN
    §Data Contracts).

    Returns ``{'output_path', 'output_sha256'}``. The legacy SME view
    (Selection==1 rows only) is no longer generated — operator preference,
    one canonical Excel per publish.
    """
    output_dir = Path(output_dir)
    _check_safe_output(output_dir)
    if formatted_time is None:
        formatted_time = datetime.now().strftime("%d-%m-%Y-%HH-%MM-%SS")

    existing = _existing_main_output(output_dir, vol)
    if existing is not None and not force_republish:
        raise FileExistsError(
            f"Volume {vol} already has a published output ({existing}). "
            "Refusing to overwrite (hard freeze). To republish, delete the "
            f"Volume-{vol} directory + its run_manifest.json entry, then re-run."
        )

    out_path = write_volume_excel(df, output_dir, vol, formatted_time)
    out_sha = _sha256_file(out_path)

    result = {
        "output_path": str(out_path),
        "output_sha256": out_sha,
    }

    if manifest_path is not None:
        from pipeline.ingest import update_volume_status
        extras: dict = {
            "output_path": str(out_path),
            "output_sha256": out_sha,
            "status": "success",
        }
        if corrections_applied is not None:
            extras["corrections_applied"] = corrections_applied
        if corrections_registry_hash is not None:
            extras["corrections_registry_hash"] = corrections_registry_hash
        update_volume_status(manifest_path, vol, **extras)
    return result
