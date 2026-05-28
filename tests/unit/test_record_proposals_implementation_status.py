"""Verify record_proposals._proposals_to_entries applies type-aware default."""
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/skills/cv-correct/record_proposals.py")
_spec = importlib.util.spec_from_file_location("record_proposals", _MODULE)
rp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rp
_spec.loader.exec_module(rp)


def test_other_proposal_gets_pending_implementation_status():
    """A type='other' proposal must get implementation_status='pending'."""
    proposals = [{
        "type": "other",
        "trigger": {"law_id_substring": "x"},
        "correction": {"description": "do y"},
        "evidence": {},
        "confidence": 0.9,
    }]
    entries = rp._proposals_to_entries(proposals, vol=75, agent_version="t@0")
    assert len(entries) == 1
    assert entries[0].type == "other"
    assert entries[0].implementation_status == "pending"


def test_law_id_proposal_gets_not_required_implementation_status():
    proposals = [{
        "type": "law_id",
        "trigger": {"law_id_substring": "x", "title_substring": "y"},
        "correction": {"replace_with_law_id": "z"},
        "evidence": {},
        "confidence": 0.9,
    }]
    entries = rp._proposals_to_entries(proposals, vol=75, agent_version="t@0")
    assert entries[0].implementation_status == "not_required"


def test_section_number_proposal_gets_not_required_implementation_status():
    proposals = [{
        "type": "section_number",
        "trigger": {"law_id_substring": "x", "heading_substring": "y"},
        "correction": {"replace_with_section_number": "z"},
        "evidence": {},
        "confidence": 0.9,
    }]
    entries = rp._proposals_to_entries(proposals, vol=75, agent_version="t@0")
    assert entries[0].implementation_status == "not_required"
