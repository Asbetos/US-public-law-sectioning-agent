"""Tests for the cv-correct prefilter — detection passes and helpers."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

# Load the skill's prefilter module without polluting sys.path.
_SKILL_PREFILTER = Path("/home/G39248410/.claude/skills/cv-correct/prefilter.py")
_spec = importlib.util.spec_from_file_location("cv_correct_prefilter", _SKILL_PREFILTER)
prefilter = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = prefilter
_spec.loader.exec_module(prefilter)


def _seq_entry(xml_index, citable_as, law_number, *, sourceline=100, public=True):
    return {
        "xml_index": xml_index,
        "citable_as": citable_as,
        "sidenote": "",
        "canonical_law_id": citable_as,  # for tests, equate
        "law_number": law_number,
        "is_public": public,
        "congress_session": "79-2",
        "official_title": "test title",
        "sourceline": sourceline,
        "line_end": sourceline + 10,
        "tag_path": "<pLaw>",
        "xml_excerpt": "<pLaw/>",
    }


# ---------- detect_law_number_anomalies ----------

def test_continuous_sequence_no_anomalies():
    seq = [_seq_entry(i, f"PL-{n}", n) for i, n in enumerate(range(1, 11))]
    assert prefilter.detect_law_number_anomalies(seq) == []


def test_out_of_place_detected():
    # 1, 2, 3, 605, 5, 6 → 605 between 3 and 5 is out_of_place
    nums = [1, 2, 3, 605, 5, 6]
    seq = [_seq_entry(i, f"PL-{n}", n) for i, n in enumerate(nums)]
    anomalies = prefilter.detect_law_number_anomalies(seq)
    out_of_place = [a for a in anomalies if a["kind"] == "out_of_place"]
    assert len(out_of_place) >= 1
    assert any(a["suspect_law_number"] == 605 for a in out_of_place)


def test_duplicate_later_occurrence_flagged():
    nums = [1, 2, 3, 4, 3, 5]  # 3 appears twice at index 2 and 4
    seq = [_seq_entry(i, f"PL-{n}", n) for i, n in enumerate(nums)]
    anomalies = prefilter.detect_law_number_anomalies(seq)
    dups = [a for a in anomalies if a["kind"] == "duplicate"]
    assert len(dups) >= 1
    # The later occurrence (xml_index=4) is the suspect
    assert any(a["xml_index"] == 4 for a in dups)


def test_suspect_endpoint_at_start():
    # First number is far off, inner sequence is continuous
    nums = [200, 2, 3, 4, 5]
    seq = [_seq_entry(i, f"PL-{n}", n) for i, n in enumerate(nums)]
    anomalies = prefilter.detect_law_number_anomalies(seq)
    endpoints = [a for a in anomalies if a["kind"] == "suspect_endpoint"]
    assert len(endpoints) >= 1
    assert any(a["suspect_law_number"] == 200 for a in endpoints)


def test_suspect_endpoint_at_end():
    nums = [1, 2, 3, 4, 200]
    seq = [_seq_entry(i, f"PL-{n}", n) for i, n in enumerate(nums)]
    anomalies = prefilter.detect_law_number_anomalies(seq)
    endpoints = [a for a in anomalies if a["kind"] == "suspect_endpoint"]
    assert any(a["suspect_law_number"] == 200 for a in endpoints)


def test_unparseable_flagged():
    seq = [
        _seq_entry(0, "PL-1", 1),
        _seq_entry(1, "garbage", None),
        _seq_entry(2, "PL-3", 3),
    ]
    anomalies = prefilter.detect_law_number_anomalies(seq)
    unparseable = [a for a in anomalies if a["kind"] == "unparseable"]
    assert len(unparseable) == 1
    assert unparseable[0]["xml_index"] == 1


def test_neighbours_included_in_anomalies():
    nums = [1, 2, 3, 605, 5, 6]
    seq = [_seq_entry(i, f"PL-{n}", n) for i, n in enumerate(nums)]
    anomalies = prefilter.detect_law_number_anomalies(seq)
    a = next(a for a in anomalies if a.get("suspect_law_number") == 605)
    neighbour_numbers = {n["law_number"] for n in a["neighbours"]}
    assert {2, 3, 5, 6}.issubset(neighbour_numbers)


def test_public_only_filter():
    seq = [
        _seq_entry(0, "PL-1", 1, public=True),
        _seq_entry(1, "private", 99, public=False),
        _seq_entry(2, "PL-2", 2, public=True),
    ]
    # With public_only=True, the private entry is dropped; the public sequence (1, 2) is continuous.
    assert prefilter.detect_law_number_anomalies(seq, public_only=True) == []


# ---------- detect_unique_key_duplicates ----------

def test_unique_key_no_dups():
    df = pd.DataFrame({"UniqueKey": ["a", "b", "c"], "LawIdentifier": ["x", "y", "z"]})
    assert prefilter.detect_unique_key_duplicates(df) == []


def test_unique_key_dups_grouped():
    df = pd.DataFrame({
        "UniqueKey":     ["a", "a", "b", "c", "c", "c"],
        "LawIdentifier": ["x", "x", "y", "z", "z", "z"],
    })
    groups = prefilter.detect_unique_key_duplicates(df)
    assert len(groups) == 2
    by_key = {g["unique_key"]: g for g in groups}
    assert by_key["a"]["occurrence_count"] == 2
    assert by_key["c"]["occurrence_count"] == 3


def test_unique_key_dups_ignores_nan():
    df = pd.DataFrame({
        "UniqueKey":     [None, None, "k", "k"],
        "LawIdentifier": ["x",  "y",  "z", "z"],
    })
    groups = prefilter.detect_unique_key_duplicates(df)
    assert len(groups) == 1
    assert groups[0]["unique_key"] == "k"


# ---------- _vol_from_xml_path ----------

def test_vol_from_filename():
    assert prefilter._vol_from_xml_path(Path("/x/STATUTE-114.xml")) == 114
    assert prefilter._vol_from_xml_path(Path("STATUTE-60.xml")) == 60
    assert prefilter._vol_from_xml_path(Path("not_a_statute_file.xml")) is None
