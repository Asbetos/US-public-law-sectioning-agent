"""Tests for re_publish_after_fix.py - affected-volume identification."""
import json
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/re_publish_after_fix.py")
_spec = importlib.util.spec_from_file_location("repub", _MODULE)
rp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rp
_spec.loader.exec_module(rp)


def _seed_validation(tmp_path, vols_warnings):
    scratch = tmp_path / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    for vol, warnings in vols_warnings.items():
        (scratch / f"validation_report_{vol}.json").write_text(
            json.dumps({"warnings": warnings})
        )
    return scratch


def test_identify_null_num_family_matches_uniquekey_warnings(tmp_path):
    scratch = _seed_validation(tmp_path, {
        "75": [],
        "84": ["Duplicate UniqueKey rows: 12"],
        "88": ["Duplicate UniqueKey rows: 471"],
        "91": ["Distinct LawIdentifier count 350 != 351"],  # diff bug, not dup
    })
    entry = {
        "id": 2, "type": "other",
        "trigger": {"pattern": "SectionNumber is null collapse to identical UniqueKey"},
        "discovered_in_vol": 75,
        "correction": {"description": ""},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=scratch)
    assert sorted(vols) == [75, 84, 88]


def test_identify_container_family_matches_distinct_count_warnings(tmp_path):
    scratch = _seed_validation(tmp_path, {
        "76": ["Distinct LawIdentifier count 484 != public pLaw count 485 (diff -1)"],
        "78": ["Duplicate UniqueKey rows: 22"],  # null-num, not container
        "114": ["Distinct LawIdentifier count 409 != public pLaw count 410 (diff -1)"],
    })
    entry = {
        "id": 3, "type": "other",
        "trigger": {"pattern": "<main> contains <part> elements no top-level <section>"},
        "discovered_in_vol": 75,
        "correction": {"description": ""},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=scratch)
    assert sorted(vols) == [75, 76, 114]


def test_identify_falls_back_to_description_when_pattern_empty(tmp_path):
    scratch = _seed_validation(tmp_path, {
        "84": ["Duplicate UniqueKey rows: 12"],
    })
    entry = {
        "id": 14, "type": "other",
        "trigger": {"pattern": ""},
        "discovered_in_vol": 84,
        "correction": {"description": "Extend the null-section ordinal logic so SectionNumber null entries..."},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=scratch)
    assert 84 in vols  # discovered_in_vol + warning match


def test_identify_returns_discovered_vol_only_when_no_scratch(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()  # empty
    entry = {
        "id": 5, "type": "other",
        "trigger": {"pattern": "sibling <appropriations>"},
        "discovered_in_vol": 78,
        "correction": {"description": ""},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=scratch)
    assert vols == [78]


def test_identify_returns_empty_when_no_match_and_no_discovery_vol(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    entry = {
        "id": 99, "type": "other",
        "trigger": {"pattern": "totally unmatched pattern"},
        "discovered_in_vol": None,
        "correction": {"description": ""},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=scratch)
    assert vols == []


def test_load_entry_returns_none_when_missing(tmp_path):
    (tmp_path / "active_corrections.json").write_text(
        '{"schema_version": 1, "next_id": 100, "entries": [], "rejected": []}')
    e = rp._load_entry(tmp_path, 99)
    assert e is None


def test_load_entry_returns_dict_when_found(tmp_path):
    (tmp_path / "active_corrections.json").write_text(json.dumps({
        "schema_version": 1, "next_id": 100, "entries": [
            {"id": 5, "type": "other", "implementation_status": "implemented",
             "trigger": {}, "correction": {}},
        ], "rejected": [],
    }))
    e = rp._load_entry(tmp_path, 5)
    assert e is not None
    assert e["id"] == 5
