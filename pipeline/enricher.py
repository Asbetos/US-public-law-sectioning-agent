"""Enrichment stage: agency tagging, appropriations flag, content hash, unique key.

Wraps ``post_process.add_grouped_agencies`` (which has working substring-match
logic) and ``generate_id_keys.generate_unique_key`` (per-row), but re-implements
the DivisionMapping I/O so it targets the **local** ``processed_output/`` copy
and never writes to ``/groups/brooksgrp/``.
"""
from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# The original extractor modules now live in this repo under legacy/.
_LEGACY_DIR = str(Path(__file__).resolve().parents[1] / "legacy")
if _LEGACY_DIR not in sys.path:
    sys.path.insert(0, _LEGACY_DIR)

# Reuse battle-tested logic from the legacy modules.
from post_process import add_grouped_agencies  # noqa: E402

import generate_id_keys  # noqa: E402  (we need to mutate its module-level state)
from generate_id_keys import generate_unique_key  # noqa: E402

logger = logging.getLogger(__name__)

TEXT_COLUMNS = [
    "Text",
    "DivisionHeadingLevel1",
    "DivisionHeadingLevel2",
    "DivisionHeadingLevel3",
]


def fetch_agency_list(processed_output_dir) -> list:
    """Load lowercase Agency + Bureau names from the LOCAL AgencyList.xlsx.

    Uses Python sets to avoid numpy's mixed-type sort error when pandas leaves
    NaN values intermixed with strings.
    """
    path = Path(processed_output_dir) / "AgencyList.xlsx"
    if not path.exists():
        raise FileNotFoundError(
            f"AgencyList.xlsx missing: {path}. Seed it once with "
            f"`python seed_lookup_files.py` (production -> local), then "
            f"any future edits stay local."
        )
    sheet = pd.read_excel(path)

    def _clean(col: str) -> set[str]:
        return {
            s for s in sheet[col].dropna().astype(str).str.lower().tolist()
            if s and s != "nan"
        }

    return sorted(_clean("Agency") | _clean("Bureau"))


def add_agencies(
    processed_output_dir,
    new_entries: list[dict],
) -> int:
    """Append new agency / bureau rows to the LOCAL AgencyList.xlsx.

    ``new_entries`` is a list of dicts like
    ``[{"Agency": "Department of X", "Bureau": None}, ...]``. Either field
    may be ``None`` (or absent / empty); rows where both are empty are
    skipped. Duplicate rows — case-insensitive match on the (Agency, Bureau)
    pair against existing rows — are skipped.

    Mirrors :func:`add_unique_keys`'s DivisionMapping pattern: load → extend
    in memory → atomic write-back (tmp + rename) so a crash mid-write
    cannot corrupt the file.

    Returns the number of rows actually appended.
    """
    path = Path(processed_output_dir) / "AgencyList.xlsx"
    if not path.exists():
        raise FileNotFoundError(
            f"AgencyList.xlsx missing: {path}. Seed it once with "
            f"`python seed_lookup_files.py` before adding entries."
        )

    existing = pd.read_excel(path)
    # Normalise column presence; older files may lack one of the two columns.
    for col in ("Agency", "Bureau"):
        if col not in existing.columns:
            existing[col] = pd.NA

    def _norm(value) -> str:
        if value is None:
            return ""
        s = str(value).strip()
        return "" if s.lower() in ("", "nan") else s.casefold()

    existing_keys: set[tuple[str, str]] = {
        (_norm(a), _norm(b))
        for a, b in zip(existing["Agency"].tolist(), existing["Bureau"].tolist())
    }

    rows_to_add: list[dict] = []
    for entry in new_entries:
        agency = entry.get("Agency") if isinstance(entry, dict) else None
        bureau = entry.get("Bureau") if isinstance(entry, dict) else None
        key = (_norm(agency), _norm(bureau))
        if key == ("", ""):
            continue
        if key in existing_keys:
            continue
        existing_keys.add(key)
        rows_to_add.append({
            "Agency": agency if _norm(agency) else None,
            "Bureau": bureau if _norm(bureau) else None,
        })

    if not rows_to_add:
        return 0

    out_df = pd.concat([existing, pd.DataFrame(rows_to_add)], ignore_index=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    out_df.to_excel(tmp, index=False, engine="openpyxl")
    tmp.replace(path)
    return len(rows_to_add)


def add_agency_tags(df: pd.DataFrame, agency_list: list) -> pd.DataFrame:
    """Wrap post_process.add_grouped_agencies with our text_columns convention."""
    return add_grouped_agencies(
        df,
        group_col="LawIdentifier",
        text_cols=TEXT_COLUMNS,
        agency_list=agency_list,
    )


def add_appropriations_flag(df: pd.DataFrame) -> pd.DataFrame:
    """``IsAppropriation = True`` for laws containing any Division-type entry."""
    appr_laws = df.loc[df["EntryType"] == "Division", "LawIdentifier"].unique()
    df = df.copy()
    df["IsAppropriation"] = df["LawIdentifier"].isin(appr_laws)
    return df


def add_content_hash(df: pd.DataFrame) -> pd.DataFrame:
    """SHA-256 hex of sorted-concatenated Text per LawIdentifier; same value on every row of that law."""
    def hash_group(group: pd.Series) -> str | None:
        texts = sorted(str(t) for t in group.dropna() if str(t).strip())
        if not texts:
            return None
        return hashlib.sha256("".join(texts).encode("utf-8")).hexdigest()

    hashes = df.groupby("LawIdentifier")["Text"].apply(hash_group).to_dict()
    df = df.copy()
    df["ContentHash"] = df["LawIdentifier"].map(hashes)
    return df


def _load_division_mapping(path: Path) -> dict:
    if not path.exists():
        return {}
    sheet = pd.read_excel(path, engine="openpyxl")
    return dict(zip(sheet["Text_Heading"].astype(str).str.lower(), sheet["Mapping_ID"]))


def _save_division_mapping_atomic(mapping: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    out = pd.DataFrame(list(mapping.items()), columns=["Text_Heading", "Mapping_ID"])
    out.to_excel(tmp, index=False, engine="openpyxl")
    tmp.replace(path)


def add_unique_keys(
    df: pd.DataFrame,
    division_mapping_path,
    vol=None,
    source_xml_dir=None,
    version: str = "BaseRun",
    write_mapping: bool = True,
) -> pd.DataFrame:
    """Compute UniqueKey per row using the LOCAL DivisionMapping.xlsx.

    Loads the mapping from ``division_mapping_path``, extends it with any new
    headings discovered in ``df``, sets the module-level ``division_mapper_json``
    so ``generate_id_keys.generate_unique_key`` can read it, then applies the
    key generation row-wise.

    If ``write_mapping=True`` (default), the updated mapping is written back to
    ``division_mapping_path`` atomically. The pipeline runner can set this to
    False per-volume and instead write once at the very end of the full run.
    """
    mapping_path = Path(division_mapping_path)
    mapping = _load_division_mapping(mapping_path)
    headings: set[str] = set()
    for col in ("DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3"):
        for v in df[col].dropna().tolist():
            s = str(v).strip().lower()
            if s and s != "nan":
                headings.add(s)
    for h in sorted(headings):
        if h not in mapping:
            mapping[h] = len(mapping) + 1

    if write_mapping:
        _save_division_mapping_atomic(mapping, mapping_path)

    generate_id_keys.division_mapper_json = mapping  # consumed by generate_unique_key

    df = df.copy()
    if vol is not None and int(vol) <= 64:
        # Legacy volumes (<=64, incl. vol 64 whose public-law number lives in the
        # sidenote and whose docNumber is the chapter): updated 11-segment key with
        # per-row Congress/Session
        # (derived from approvedDate) so laws sharing a number across sessions
        # in a single volume stay distinct. Adds VolumeNumber/Congress/Session.
        df["VolumeNumber"] = int(vol)
        if "Congress" not in df.columns or "Session" not in df.columns:
            cs_path = Path(source_xml_dir) / "Congress_Session_Dates.csv"
            congress_df = pd.read_csv(cs_path)
            cs = generate_id_keys.map_approved_date_to_congress(df["approvedDate"], congress_df)

            def _clean_session(x):
                if pd.isna(x):
                    return pd.NA
                s = str(x).strip()
                try:
                    return str(int(float(s)))       # 1.0 / "2" -> "1" / "2"
                except (ValueError, TypeError):
                    return s                          # special session label: S1, S2

            df["Congress"] = pd.array(
                [int(c) if pd.notna(c) else pd.NA for c in cs["Congress"]], dtype="Int64"
            )
            df["Session"] = [_clean_session(x) for x in cs["Session"]]
        # Normalize approvedDate to yyyy-mm-dd to match the modern/original
        # pipeline output (legacy XML stores it as "Month DD, YYYY" text).
        # Unparseable values are left as-is rather than dropped.
        _parsed_dates = generate_id_keys.clean_date_col(df["approvedDate"])
        df["approvedDate"] = [
            p.strftime("%Y-%m-%d") if pd.notna(p) else o
            for p, o in zip(_parsed_dates, df["approvedDate"])
        ]
        df["UniqueKey"] = df.apply(generate_id_keys.generate_unique_key_legacy, axis=1)
    else:
        df["UniqueKey"] = df.apply(generate_unique_key, axis=1)
    df["KeyVersion"] = version
    return df


def enrich(
    df: pd.DataFrame,
    processed_output_dir,
    vol=None,
    source_xml_dir=None,
    version: str = "BaseRun",
    write_mapping: bool = True,
) -> pd.DataFrame:
    """Run the full enrichment chain: agency tags → appr flag → content hash → unique keys.

    ``vol`` + ``source_xml_dir`` enable the legacy (<=63) updated 11-segment key
    with per-row Congress/Session derived from ``Congress_Session_Dates.csv``.
    """
    out_dir = Path(processed_output_dir)
    agency_list = fetch_agency_list(out_dir)
    df = add_agency_tags(df, agency_list)
    df = add_appropriations_flag(df)
    df = add_content_hash(df)
    df = add_unique_keys(
        df,
        division_mapping_path=out_dir / "DivisionMapping.xlsx",
        vol=vol,
        source_xml_dir=source_xml_dir,
        version=version,
        write_mapping=write_mapping,
    )
    return df
