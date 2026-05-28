"""Tests for the AgencyList.xlsx write-back helper + CLI."""
from pathlib import Path

import pandas as pd
import pytest

from pipeline.enricher import add_agencies, fetch_agency_list


def _seed_agency_file(dir_path: Path, rows: list[dict]) -> Path:
    """Helper: write an AgencyList.xlsx with the given rows."""
    path = dir_path / "AgencyList.xlsx"
    pd.DataFrame(rows, columns=["Agency", "Bureau"]).to_excel(
        path, index=False, engine="openpyxl",
    )
    return path


def test_add_agencies_appends_new_rows(tmp_path):
    _seed_agency_file(tmp_path, [{"Agency": "Department of Commerce", "Bureau": None}])
    n = add_agencies(tmp_path, [
        {"Agency": "Department of Defense", "Bureau": None},
        {"Agency": None, "Bureau": "Bureau of Land Management"},
    ])
    assert n == 2
    df = pd.read_excel(tmp_path / "AgencyList.xlsx")
    assert set(df["Agency"].dropna()) == {"Department of Commerce", "Department of Defense"}
    assert "Bureau of Land Management" in set(df["Bureau"].dropna())


def test_add_agencies_skips_case_insensitive_duplicates(tmp_path):
    _seed_agency_file(tmp_path, [{"Agency": "Department of Commerce", "Bureau": None}])
    n = add_agencies(tmp_path, [
        {"Agency": "DEPARTMENT OF COMMERCE", "Bureau": None},
        {"Agency": "department of commerce", "Bureau": None},
    ])
    assert n == 0
    df = pd.read_excel(tmp_path / "AgencyList.xlsx")
    assert len(df) == 1


def test_add_agencies_skips_empty_rows(tmp_path):
    _seed_agency_file(tmp_path, [{"Agency": "X", "Bureau": None}])
    n = add_agencies(tmp_path, [
        {"Agency": None, "Bureau": None},
        {"Agency": "", "Bureau": ""},
        {"Agency": "   ", "Bureau": "   "},
    ])
    assert n == 0


def test_add_agencies_atomic_write(tmp_path):
    """After a successful add, no .tmp file should be left lying around."""
    _seed_agency_file(tmp_path, [{"Agency": "X", "Bureau": None}])
    add_agencies(tmp_path, [{"Agency": "Y", "Bureau": None}])
    assert not (tmp_path / "AgencyList.xlsx.tmp").exists()


def test_add_agencies_paired_agency_and_bureau_kept_as_one_row(tmp_path):
    _seed_agency_file(tmp_path, [])
    n = add_agencies(tmp_path, [
        {"Agency": "Department of the Interior", "Bureau": "Bureau of Indian Affairs"},
    ])
    assert n == 1
    df = pd.read_excel(tmp_path / "AgencyList.xlsx")
    row = df.iloc[0]
    assert row["Agency"] == "Department of the Interior"
    assert row["Bureau"] == "Bureau of Indian Affairs"


def test_add_agencies_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        add_agencies(tmp_path, [{"Agency": "X"}])


def test_fetch_agency_list_sees_appended_entries(tmp_path):
    """Round-trip: add an entry, then fetch_agency_list returns the new value
    lowercased + unioned with existing."""
    _seed_agency_file(tmp_path, [{"Agency": "Department of Existing", "Bureau": None}])
    add_agencies(tmp_path, [{"Agency": "Department of Brand New", "Bureau": None}])
    items = fetch_agency_list(tmp_path)
    assert "department of existing" in items
    assert "department of brand new" in items
