"""Tests for the publish-time LawIdentifier format normalization.

The published ``LawIdentifier`` column must be UNIFORM:
canonical form ``Public Law {congress}–{number}`` with an EN-DASH
(U+2013) separator. This runs as the LAST transform before the Excel is
written, so corrected, legacy, and modern rows all come out identical.
Values that do not match the public-law shape are left UNCHANGED.
"""
import pandas as pd
import pytest

from pipeline.publisher import (
    FINAL_COLUMN_ORDER,
    _normalize_law_identifier_column,
    write_volume_excel,
)

EN = "–"  # en-dash
EM = "—"  # em-dash


@pytest.mark.parametrize(
    "raw, expected",
    [
        (f"Public Law 103{EN}1", f"Public Law 103{EN}1"),    # en-dash -> unchanged
        ("Public Law 103-110", f"Public Law 103{EN}110"),    # hyphen -> en-dash
        (f"Public Law 103{EM}286", f"Public Law 103{EN}286"),  # em-dash -> en-dash
        ("103-53", f"Public Law 103{EN}53"),                 # bare (no prefix) -> prefixed
        ("79-600", f"Public Law 79{EN}600"),                 # legacy bare -> prefixed
        (f"Public Law 103{EN}160", f"Public Law 103{EN}160"),  # already canonical (idempotent)
    ],
)
def test_normalize_rewrites_every_shape(raw, expected):
    df = pd.DataFrame({"LawIdentifier": [raw]})
    out = _normalize_law_identifier_column(df)
    assert out["LawIdentifier"].iloc[0] == expected


@pytest.mark.parametrize(
    "value",
    [
        "",                       # empty string
        "H.R. 1234",              # odd token, not a public-law shape
        "Private Law 86-100",     # different law type, no public-law prefix shape
        "S. Con. Res. 5",
        None,                     # missing value
    ],
)
def test_normalize_leaves_non_matching_unchanged(value):
    df = pd.DataFrame({"LawIdentifier": [value]})
    out = _normalize_law_identifier_column(df)
    assert out["LawIdentifier"].iloc[0] == value


def test_normalize_is_idempotent():
    df = pd.DataFrame({"LawIdentifier": ["103-53", f"Public Law 84-486"]})
    once = _normalize_law_identifier_column(df)
    twice = _normalize_law_identifier_column(once)
    assert list(twice["LawIdentifier"]) == list(once["LawIdentifier"])
    assert list(once["LawIdentifier"]) == [f"Public Law 103{EN}53", f"Public Law 84{EN}486"]


def test_normalize_only_touches_law_identifier_column():
    df = pd.DataFrame(
        {
            "UniqueKey": ["k-1", "k-2"],
            "LawIdentifier": ["84-486", "garbage"],
            "LawTitle": ["A", "B"],
        }
    )
    out = _normalize_law_identifier_column(df)
    # UniqueKey and other columns are untouched
    assert list(out["UniqueKey"]) == ["k-1", "k-2"]
    assert list(out["LawTitle"]) == ["A", "B"]
    # LawIdentifier normalized where it matches, left alone where it doesn't
    assert list(out["LawIdentifier"]) == [f"Public Law 84{EN}486", "garbage"]


def test_normalize_missing_column_is_noop():
    df = pd.DataFrame({"UniqueKey": ["k-1"]})
    out = _normalize_law_identifier_column(df)
    assert list(out.columns) == ["UniqueKey"]
    assert list(out["UniqueKey"]) == ["k-1"]


def _make_minimal_df(law_id) -> pd.DataFrame:
    row = {col: None for col in FINAL_COLUMN_ORDER}
    row.update(
        {
            "UniqueKey": "test-key-0001",
            "KeyVersion": "v0",
            "OriginalOrder": 1,
            "EntryType": "Section",
            "Selection": 0,
            "LawIdentifier": law_id,
            "LawType": "An Act",
            "LawTitle": "Test",
            "ReviewStatus": "N/A",
        }
    )
    return pd.DataFrame([row])


def test_written_excel_has_normalized_law_identifier(tmp_path):
    """End-to-end: the value written to the Excel is the canonical form."""
    df = _make_minimal_df("84-486")
    out_path = write_volume_excel(df, tmp_path, vol=99, formatted_time="run1")
    written = pd.read_excel(out_path, engine="openpyxl")
    assert written["LawIdentifier"].iloc[0] == f"Public Law 84{EN}486"
    # UniqueKey survives untouched
    assert written["UniqueKey"].iloc[0] == "test-key-0001"
