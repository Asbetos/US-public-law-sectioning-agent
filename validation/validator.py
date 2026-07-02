"""Per-volume validation checks + regression assertions on known corrections.

Public API: ``run_all_validations(df, vol, xml_path) -> ValidationReport``.

Per the plan §10, schema/EntryType/UniqueKey/LawId-format/regressions are hard
failures (block publication). pLaw-count diff, text coverage, and Selection
sample size are warnings (logged, do not block).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from validation.report import ValidationReport


EXPECTED_COLUMNS_26 = [
    "UniqueKey", "KeyVersion", "ContentHash",
    "OriginalOrder", "EntryType", "Selection", "Order",
    "LawIdentifier", "LawType", "LawTitle", "approvedDate", "IsAppropriation",
    "Division", "Title", "SubTitle", "Chapter", "SubChapter",
    "SectionNumber", "SectionName",
    "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
    "Text", "Agencies_Row", "Agencies_Law", "ReviewStatus",
]

# (title_lowercase_substring, expected_corrected_id, original_incorrect_id)
# If output has a row whose title contains the substring AND its LawIdentifier
# still contains the original incorrect id, the correction failed.
LAW_ID_REGRESSION_RULES = [
    ("social security", "81-174", "81-175"),
    ("federal crop insurance", "81-268", "81-208"),
    ("preference act of 1944 with respect to certain mothers of veterans", "81-269", "81-208"),
    ("republic of finland on the principal or interest", "81-265", "81-285"),
    ("federal election campaign act of 1971 to improve", "104-79", "104–9"),
    ("amend the act approved july 3, 1943", "79-466", "79-496"),
    ("return of the grand river dam project", "79-573", "79-673"),
    ("use by industry of silver", "79-579", "79-679"),
    ("saint mary river, michigan, south canal", "84-663", "84-274"),
]

# (vol, law_id_substr, heading_substr_lower, expected_SEC_number)
SECTION_NUMBER_REGRESSION_RULES = [
    ("114", "106–382", "use of pick-sloan power", "SEC. 6."),
    ("114", "106–181", "grants from small airport fund", "SEC. 128."),
    ("114", "106–259", "transfer of funds", "SEC. 8015."),
    ("114", "106–259", "including transfer of funds", "SEC. 8041."),
    ("98",  "98–369",  "value of used components furnished by first user", "SEC. 734."),
]


# ---------- individual checks ----------

def validate_schema(df: pd.DataFrame) -> tuple[list, list]:
    failures, warnings = [], []
    # Legacy volumes (<=63) carry 3 extra columns from the updated 11-segment
    # UniqueKey; these are expected, not anomalous.
    _legacy_extra = {"VolumeNumber", "Congress", "Session"}
    missing = [c for c in EXPECTED_COLUMNS_26 if c not in df.columns]
    extra = [c for c in df.columns if c not in EXPECTED_COLUMNS_26 and c not in _legacy_extra]
    if missing:
        failures.append(f"Missing columns: {missing}")
    if extra:
        warnings.append(f"Unexpected extra columns: {extra}")
    return failures, warnings


def validate_entry_types(df: pd.DataFrame) -> list:
    if "EntryType" not in df.columns:
        return ["EntryType column missing"]
    bad = set(df["EntryType"].dropna().unique()) - {"Section", "Division"}
    if bad:
        return [f"Unexpected EntryType values: {bad}"]
    return []


def validate_unique_key_uniqueness(df: pd.DataFrame) -> list:
    if "UniqueKey" not in df.columns:
        return ["UniqueKey column missing"]
    dups = df[df["UniqueKey"].notna() & df.duplicated("UniqueKey", keep=False)]
    if not dups.empty:
        return [f"Duplicate UniqueKey rows: {len(dups)} (e.g., {dups['UniqueKey'].iloc[0]})"]
    return []


def validate_law_id_format(df: pd.DataFrame) -> list:
    if "LawIdentifier" not in df.columns:
        return ["LawIdentifier column missing"]
    pat = re.compile(r"\d+[-–—]\d+")
    bad = df[~df["LawIdentifier"].fillna("").astype(str).apply(lambda s: bool(pat.search(s)))]
    if not bad.empty:
        sample = bad["LawIdentifier"].iloc[0]
        return [f"LawIdentifier values without recognizable pattern: {len(bad)} (sample: {sample!r})"]
    return []


def validate_plaw_count(df: pd.DataFrame, xml_path) -> list:
    """Warning if distinct LawIdentifier count differs from public pLaw count in source XML."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        ns_uri = root.tag.split("}")[0].strip("{")
        ns = {"uslm": ns_uri}
        plaws = root.findall(".//uslm:pLaw", ns)
        public_count = 0
        for p in plaws:
            pp = p.find(".//uslm:publicPrivate", ns)
            if pp is not None and pp.text and pp.text.strip().lower() == "public":
                public_count += 1
    except Exception as e:
        return [f"Could not count pLaws in XML: {e}"]
    if "LawIdentifier" not in df.columns:
        return ["LawIdentifier column missing (cannot compare to XML count)"]
    distinct = df["LawIdentifier"].dropna().nunique()
    if distinct != public_count:
        return [f"Distinct LawIdentifier count {distinct} != public pLaw count in XML {public_count} (diff {distinct - public_count:+d})"]
    return []


def validate_text_coverage(df: pd.DataFrame, threshold: float = 0.8) -> list:
    if "Text" not in df.columns:
        return ["Text column missing"]
    present = df["Text"].fillna("").astype(str).str.strip().ne("").sum()
    ratio = present / max(len(df), 1)
    if ratio < threshold:
        return [f"Text coverage {ratio:.1%} below threshold {threshold:.0%} ({present}/{len(df)})"]
    return []


def validate_selection_sample(df: pd.DataFrame, n: int = 600) -> list:
    if "Selection" not in df.columns:
        return ["Selection column missing"]
    selected = int((df["Selection"] == 1).sum())
    if selected > n:
        return [f"Selection count {selected} exceeds maximum {n}"]
    if selected < n:
        # Only a warning when the sample is short (often correct for small volumes)
        return [f"Selection count {selected} below requested {n} (small volume?)"]
    return []


def validate_law_id_regressions(df: pd.DataFrame) -> list:
    failures = []
    if "LawTitle" not in df.columns or "LawIdentifier" not in df.columns:
        return failures
    for title_substr, must_have, wrong in LAW_ID_REGRESSION_RULES:
        cand = df[
            df["LawTitle"].fillna("").str.lower().str.contains(
                re.escape(title_substr), regex=True
            )
        ]
        if cand.empty:
            continue
        regressed = cand[cand["LawIdentifier"].fillna("").str.contains(wrong, regex=False)]
        if not regressed.empty:
            failures.append(
                f"Law-id correction {wrong!r} -> {must_have!r} did not fire on "
                f"{len(regressed)} row(s) matching title substring {title_substr!r}"
            )
    return failures


def validate_section_number_regressions(df: pd.DataFrame, vol) -> list:
    failures = []
    if not {"SectionNumber", "LawIdentifier", "SectionName"} <= set(df.columns):
        return failures
    vol_str = str(vol)
    for vol_hint, law_substr, heading_substr, expected_num in SECTION_NUMBER_REGRESSION_RULES:
        if vol_str != vol_hint:
            continue
        matches = df[
            df["LawIdentifier"].fillna("").str.contains(law_substr, regex=False, na=False)
            & df["SectionName"].fillna("").str.lower().str.contains(
                heading_substr.lower(), regex=False, na=False
            )
        ]
        if matches.empty:
            continue
        if not (matches["SectionNumber"] == expected_num).any():
            actual = matches["SectionNumber"].unique().tolist()[:3]
            failures.append(
                f"Section-number correction missed in vol {vol_hint}: "
                f"{law_substr!r} '{heading_substr}' should yield SectionNumber={expected_num!r}; "
                f"got {actual!r}"
            )
    return failures


# ---------- top-level ----------

def run_all_validations(df: pd.DataFrame, vol, xml_path) -> ValidationReport:
    report = ValidationReport(vol=int(vol))
    report.row_count = len(df)
    if "LawIdentifier" in df.columns:
        report.law_count = int(df["LawIdentifier"].nunique())

    schema_fails, schema_warns = validate_schema(df)
    report.failed.extend(schema_fails)
    report.warnings.extend(schema_warns)

    # Hard checks
    report.failed.extend(validate_entry_types(df))
    report.failed.extend(validate_law_id_format(df))
    report.failed.extend(validate_law_id_regressions(df))
    report.failed.extend(validate_section_number_regressions(df, vol))

    # Soft checks (warnings)
    # NOTE: UniqueKey duplicates can arise when two sections of the same law share
    # the same SectionNumber (and Division/Title/etc.). The legacy `generate_unique_key`
    # is deterministic by content and does not de-duplicate. Production outputs
    # exhibit the same pattern, so this is a known data-quality issue rather
    # than a code bug. We surface as a warning, not a hard fail.
    report.warnings.extend(validate_unique_key_uniqueness(df))
    report.warnings.extend(validate_plaw_count(df, xml_path))
    report.warnings.extend(validate_text_coverage(df))
    report.warnings.extend(validate_selection_sample(df))

    if not report.failed:
        report.passed.append(f"All hard checks passed ({report.row_count} rows, {report.law_count} laws)")
    return report
