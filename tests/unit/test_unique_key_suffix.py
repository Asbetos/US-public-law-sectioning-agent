"""Test the UniqueKey suffix logic in apply_corrections_and_publish."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

_MODULE_PATH = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/apply_corrections_and_publish.py")
_spec = importlib.util.spec_from_file_location("apply_corrections_module", _MODULE_PATH)
acp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = acp
_spec.loader.exec_module(acp)


def test_dedupe_no_dups_is_noop():
    df = pd.DataFrame({"UniqueKey": ["a", "b", "c"]})
    n = acp._dedupe_unique_keys(df)
    assert n == 0
    assert df["UniqueKey"].tolist() == ["a", "b", "c"]


def test_dedupe_suffixes_repeats():
    df = pd.DataFrame({"UniqueKey": ["k", "k", "k", "m"]})
    n = acp._dedupe_unique_keys(df)
    assert n == 2  # second + third 'k' get suffixed
    assert df["UniqueKey"].tolist() == ["k", "k-1", "k-2", "m"]


def test_dedupe_preserves_first_occurrence():
    df = pd.DataFrame({"UniqueKey": ["k", "a", "k", "k"]})
    acp._dedupe_unique_keys(df)
    # First occurrence of 'k' (position 0) keeps the original key
    assert df["UniqueKey"].iloc[0] == "k"
    assert df["UniqueKey"].iloc[2].startswith("k-")
    assert df["UniqueKey"].iloc[3].startswith("k-")


def test_dedupe_eliminates_all_dups():
    df = pd.DataFrame({"UniqueKey": ["x", "y", "x", "y", "x"]})
    acp._dedupe_unique_keys(df)
    assert df["UniqueKey"].duplicated(keep=False).sum() == 0


def test_dedupe_handles_empty_df():
    df = pd.DataFrame({"UniqueKey": []})
    assert acp._dedupe_unique_keys(df) == 0


def test_dedupe_missing_column_is_noop():
    df = pd.DataFrame({"OtherCol": [1, 2]})
    assert acp._dedupe_unique_keys(df) == 0
