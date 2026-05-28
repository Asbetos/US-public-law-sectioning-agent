"""Segmentation stage: convert raw records dict to a DataFrame, sort, apply
the SME-review Selection sampling, assign OriginalOrder.

The logic is copied from ``create_xlsx_output_from_json`` in
``Extract_Sections_Divisions_From_XML.py`` but decoupled from file I/O so the
DataFrame can flow through the rest of the pipeline before any Excel write.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

ALL_COLUMNS = [
    "EntryType", "counter", "LawIdentifier", "approvedDate", "LawTitle", "LawType",
    "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
    "SectionName", "Text",
    "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
]

EXCLUDE_SECTION_NAMES = [
    "sense of congress.",
    "sunset.",
    "severability.",
    "short title.",
    "table of contents.",
    "short title; table of contents.",
]

EXCLUDE_JOINT_RES_WORDING = [
    "providing for congressional disapproval under chapter 8 of title 5",
]

DEFAULT_SAMPLE_SIZE = 600
DEFAULT_SEED = 42


def build_dataframe(raw_records: dict) -> pd.DataFrame:
    """Merge Sections + Divisions, tag EntryType, sort by (LawNumber, counter).

    Drops exact-duplicate rows that can arise from quirks in the source XML
    (e.g., the same ``<section>`` element appearing twice for a single law).
    Two rows are considered duplicates if every column except ``counter`` is
    identical. The ``counter`` is an extraction-order index, not content.
    """
    sections_df = pd.DataFrame(raw_records.get("Sections", []))
    divisions_df = pd.DataFrame(raw_records.get("Divisions", []))
    sections_df["EntryType"] = "Section"
    divisions_df["EntryType"] = "Division"
    sections_df = sections_df.reindex(columns=ALL_COLUMNS)
    divisions_df = divisions_df.reindex(columns=ALL_COLUMNS)

    combined = pd.concat([sections_df, divisions_df], ignore_index=True)

    dedup_cols = [c for c in combined.columns if c != "counter"]
    before = len(combined)
    combined = combined.drop_duplicates(subset=dedup_cols, keep="first").reset_index(drop=True)
    if (dropped := before - len(combined)) > 0:
        import logging
        logging.getLogger(__name__).warning(
            "Dropped %d exact-duplicate row(s) at segmentation (source-XML quirk)", dropped
        )

    combined["LawNumber"] = (
        combined["LawIdentifier"].astype(str).str.extract(r"(\d+)$").astype("Int64")
    )
    combined = combined.sort_values(["LawNumber", "counter"]).reset_index(drop=True)
    return combined


def apply_selection_sampling(
    df: pd.DataFrame,
    n: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """Mark Selection=1 on a random sample of eligible entries; assign Order 1..n.

    Eligibility excludes:
      - sections whose SectionName matches one of EXCLUDE_SECTION_NAMES
      - laws whose LawTitle matches the joint-resolution disapproval pattern

    If fewer than ``n`` eligible rows exist, the entire eligible set is sampled
    and a warning is logged via the standard logger.
    """
    np.random.seed(seed)

    excl_names = [x.lower() for x in EXCLUDE_SECTION_NAMES]
    eligible_by_name = ~df["SectionName"].fillna("").str.lower().isin(excl_names)
    joint_res_pattern = "|".join(re.escape(x.lower()) for x in EXCLUDE_JOINT_RES_WORDING)
    eligible_by_title = ~df["LawTitle"].fillna("").str.lower().str.contains(
        joint_res_pattern, regex=True
    )

    eligible = df[eligible_by_name & eligible_by_title]
    sample_size = min(n, len(eligible))

    df = df.copy()
    df["Selection"] = 0
    df["Order"] = pd.NA
    if sample_size > 0:
        sampled_idx = eligible.sample(n=sample_size).index
        df.loc[sampled_idx, "Selection"] = 1
        df.loc[sampled_idx, "Order"] = np.random.permutation(
            np.arange(1, sample_size + 1)
        )

    if sample_size < n:
        import logging
        logging.getLogger(__name__).warning(
            "Selection sample capped: requested %d, eligible %d", n, sample_size
        )
    return df


def assign_original_order(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["OriginalOrder"] = np.arange(1, len(df) + 1)
    return df


def segment(
    raw_records: dict,
    n: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """Full segmentation: build → sample → assign OriginalOrder.

    Drops internal sort-helper columns (``counter``, ``LawNumber``) before
    returning so downstream stages see a clean schema.
    """
    df = build_dataframe(raw_records)
    df = apply_selection_sampling(df, n=n, seed=seed)
    df = assign_original_order(df)
    return df.drop(columns=["counter", "LawNumber"], errors="ignore")
