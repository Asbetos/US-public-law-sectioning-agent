"""Manifest honesty: a type=other entry with implementation_status='pending'
must NOT be listed in corrections_applied.active."""
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/apply_corrections_and_publish.py")
_spec = importlib.util.spec_from_file_location("acp_mod", _MODULE)
acp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = acp
_spec.loader.exec_module(acp)


class _FakeEntry:
    def __init__(self, id, type, status, implementation_status):
        self.id = id
        self.type = type
        self.status = status
        self.implementation_status = implementation_status


def test_filter_includes_law_id_rules():
    entries = [_FakeEntry(4, "law_id", "approved", "not_required")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == [4]


def test_filter_includes_implemented_other():
    entries = [_FakeEntry(2, "other", "approved", "implemented")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == [2]


def test_filter_excludes_pending_other():
    entries = [_FakeEntry(3, "other", "approved", "pending")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == []


def test_filter_excludes_failed_other():
    entries = [_FakeEntry(5, "other", "approved", "failed")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == []


def test_filter_excludes_unapproved():
    entries = [_FakeEntry(7, "law_id", "rejected", "not_required")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == []


def test_filter_includes_manual_override_other():
    entries = [_FakeEntry(8, "other", "approved", "manual_override")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == [8]


def test_filter_includes_in_progress_excluded():
    """An entry mid-implementation should NOT be reported as applied yet."""
    entries = [_FakeEntry(9, "other", "approved", "in_progress")]
    out = acp._filter_active_ids_for_manifest(entries)
    assert out == []
