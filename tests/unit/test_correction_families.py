"""Tests for the correction-family classifier."""
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/correction_families.py")
_spec = importlib.util.spec_from_file_location("correction_families", _MODULE)
cf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cf
_spec.loader.exec_module(cf)


def _entry(eid, pattern, description=""):
    return {
        "id": eid,
        "type": "other",
        "trigger": {"pattern": pattern},
        "correction": {"description": description},
    }


# ---------- classify() ----------

def test_classify_null_num_family():
    e = _entry(2, "multiple sections within a single pLaw where SectionNumber is null collapse to identical UniqueKey")
    assert cf.classify(e) == "null-num"


def test_classify_null_num_family_outer_section_variant():
    e = _entry(16, "outer <section> that holds only a <heading> and a numbered inner <section>")
    assert cf.classify(e) == "null-num"


def test_classify_null_num_family_unnumbered_opening_variant():
    e = _entry(15, "Within a single pLaw, the opening <section class=\"inline\"> carrying the 'That ...' enacting paragraph")
    assert cf.classify(e) == "null-num"


def test_classify_top_level_container_part():
    e = _entry(3, "<main> contains <part> elements (multi-part Act) or bare <subsection> elements")
    assert cf.classify(e) == "top-level-container"


def test_classify_top_level_container_title():
    e = _entry(7, "<main> contains <title> elements at the top level with no top-level <section>")
    assert cf.classify(e) == "top-level-container"


def test_classify_top_level_container_chapter():
    e = _entry(11, "<main> contains <chapter> elements at the top level with no top-level <section>")
    assert cf.classify(e) == "top-level-container"


def test_classify_top_level_container_quoted():
    e = _entry(17, "<main> contains <quotedContent> directly as its body holder")
    assert cf.classify(e) == "top-level-container"


def test_classify_sibling_appropriations():
    e = _entry(5, "Within a single pLaw, two or more sibling <appropriations> elements")
    assert cf.classify(e) == "sibling-appropriations"


def test_classify_sibling_level():
    e = _entry(13, "Two sibling <level> elements within a single <title>")
    assert cf.classify(e) == "sibling-level"


def test_classify_none_for_unmatched():
    e = _entry(99, "some pattern that doesn't match any family")
    assert cf.classify(e) == "none"


def test_classify_none_for_law_id_type():
    e = {"id": 4, "type": "law_id", "trigger": {"pattern": ""}}
    assert cf.classify(e) == "none"


def test_classify_handles_missing_pattern():
    e = {"id": 50, "type": "other", "trigger": {}}
    assert cf.classify(e) == "none"


def test_classify_falls_back_to_description():
    """If trigger.pattern is empty, fall back to correction.description."""
    e = {
        "id": 99,
        "type": "other",
        "trigger": {"pattern": ""},
        "correction": {"description": "Teach the extractor's section walker to handle pLaws whose <main> has zero top-level <section> children."},
    }
    assert cf.classify(e) == "top-level-container"


# ---------- family_members() ----------

def test_family_members_groups_by_family():
    entries = [
        _entry(2,  "SectionNumber is null"),
        _entry(3,  "<main> contains <part>"),
        _entry(14, "null <num>"),
        _entry(7,  "<main> contains <title>"),
        _entry(5,  "sibling <appropriations>"),
    ]
    groups = cf.family_members(entries)
    assert sorted(groups["null-num"]) == [2, 14]
    assert sorted(groups["top-level-container"]) == [3, 7]
    assert groups["sibling-appropriations"] == [5]


def test_family_members_filters_to_pending_implementation_status_if_asked():
    """When given pending_only=True, only entries with implementation_status='pending'
    are included in the groups."""
    entries = [
        {**_entry(2, "null <num>"), "implementation_status": "pending"},
        {**_entry(14, "null <num>"), "implementation_status": "implemented"},  # already done
        {**_entry(15, "null <num>"), "implementation_status": "pending"},
    ]
    groups = cf.family_members(entries, pending_only=True)
    assert sorted(groups["null-num"]) == [2, 15]  # 14 excluded
