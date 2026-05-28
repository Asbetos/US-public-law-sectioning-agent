"""Tests for the implementation-tracking fields on CorrectionEntry."""
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/corrections_registry.py")
_spec = importlib.util.spec_from_file_location("corrections_registry", _MODULE)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

CorrectionEntry = mod.CorrectionEntry


def _base_entry_dict(**overrides):
    base = {
        "id": 99,
        "type": "other",
        "trigger": {"law_id_substring": "X"},
        "correction": {"description": "do Y"},
        "evidence": {},
        "proposed_at": "2026-05-28T00:00:00",
        "discovered_in_vol": 75,
        "agent_version": "cv-correct@0.1.0",
        "confidence": None,
        "status": "approved",
        "applied_in_runs": [],
        "seen_again_count": 0,
        "reviewer": None,
        "review_note": None,
        "reviewed_at": None,
    }
    base.update(overrides)
    return base


def test_correction_entry_has_implementation_fields():
    e = CorrectionEntry.from_dict(_base_entry_dict())
    assert hasattr(e, "implementation_status")
    assert hasattr(e, "implementation_commit_sha")
    assert hasattr(e, "implementation_attempted_at")
    assert hasattr(e, "implementation_notes")


def test_implementation_status_defaults_pending_for_other_type():
    e = CorrectionEntry.from_dict(_base_entry_dict(type="other", status="approved"))
    assert e.implementation_status == "pending"


def test_implementation_status_defaults_not_required_for_law_id():
    e = CorrectionEntry.from_dict(_base_entry_dict(type="law_id"))
    assert e.implementation_status == "not_required"


def test_implementation_status_defaults_not_required_for_section_number():
    e = CorrectionEntry.from_dict(_base_entry_dict(type="section_number"))
    assert e.implementation_status == "not_required"


def test_existing_dict_implementation_status_is_preserved():
    e = CorrectionEntry.from_dict(_base_entry_dict(
        type="other", implementation_status="implemented",
        implementation_commit_sha="abc123",
    ))
    assert e.implementation_status == "implemented"
    assert e.implementation_commit_sha == "abc123"


def test_to_dict_round_trips_implementation_fields():
    e = CorrectionEntry.from_dict(_base_entry_dict(
        type="other", implementation_status="failed",
        implementation_notes="pytest red on new test",
    ))
    d = e.to_dict()
    assert d["implementation_status"] == "failed"
    assert d["implementation_notes"] == "pytest red on new test"
    e2 = CorrectionEntry.from_dict(d)
    assert e2.implementation_status == "failed"
    assert e2.implementation_notes == "pytest red on new test"
