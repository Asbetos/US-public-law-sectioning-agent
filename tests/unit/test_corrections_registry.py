"""Tests for pipeline.corrections_registry."""
import json
from pathlib import Path

import pytest

from pipeline.corrections_registry import (
    CorrectionEntry,
    CorrectionsRegistry,
    SCHEMA_VERSION,
)


# ---------- helpers ----------

def _law_id_entry(law_substring: str, title_substring: str, replacement: str) -> CorrectionEntry:
    return CorrectionEntry(
        id=0,
        type="law_id",
        trigger={"law_id_substring": law_substring, "title_substring": title_substring},
        correction={"replace_with_law_id": replacement},
        evidence={"rule_or_signal": "test"},
    )


def _section_entry(law_substring: str, heading: str, new_num: str) -> CorrectionEntry:
    return CorrectionEntry(
        id=0,
        type="section_number",
        trigger={"law_id_substring": law_substring, "heading_substring": heading, "text_substring": None},
        correction={"replace_with_section_number": new_num},
        evidence={},
    )


# ---------- bootstrap ----------

def test_bootstrap_creates_missing_files(tmp_path):
    result = CorrectionsRegistry.bootstrap_files(tmp_path)
    assert (tmp_path / "active_corrections.json").exists()
    assert (tmp_path / "pending_corrections.json").exists()
    assert all(v == "created" for v in result.values())

    # Files should parse and be schema-version-stamped
    data = json.loads((tmp_path / "active_corrections.json").read_text())
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["entries"] == []
    assert data["rejected"] == []


def test_bootstrap_idempotent(tmp_path):
    CorrectionsRegistry.bootstrap_files(tmp_path)
    # mutate one file so we can prove the second call leaves it alone
    (tmp_path / "active_corrections.json").write_text('{"sentinel": true}')
    result = CorrectionsRegistry.bootstrap_files(tmp_path)
    assert result[str(tmp_path / "active_corrections.json")] == "existed"
    # File untouched
    assert json.loads((tmp_path / "active_corrections.json").read_text()) == {"sentinel": True}


# ---------- empty registry ----------

def test_load_empty_registry(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    assert reg.all_pending_entries() == []
    assert reg.all_active_entries() == []


def test_active_law_id_rules_returns_seed_when_no_approved(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    seed = reg.active_law_id_rules()
    # Seed has 9 entries (from law_id_corrections.LAW_ID_CORRECTIONS)
    assert len(seed) == 9
    # Includes the famous 81-175 → 81-174 social-security one
    assert any(r == ("81-175", "social security", "81-174") for r in seed)


def test_active_section_number_rules_returns_seed(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    seed = reg.active_section_number_rules()
    assert len(seed) == 5
    assert any(r[0] == "98–369" and r[3] == "SEC. 734." for r in seed)


# ---------- append_pending ----------

def test_append_pending_assigns_ids(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    n = reg.append_pending([
        _law_id_entry("xx-1", "alpha", "xx-2"),
        _law_id_entry("yy-1", "beta", "yy-2"),
    ])
    assert n == 2
    entries = reg.all_pending_entries()
    assert [e.id for e in entries] == [1, 2]
    assert all(e.status == "pending" for e in entries)
    assert all(e.proposed_at != "" for e in entries)


def test_append_pending_dedupe_bumps_seen_again(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    reg.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])
    # Same shape again (different id, but identical trigger/correction)
    n = reg.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])
    assert n == 0
    [entry] = reg.all_pending_entries()
    assert entry.seen_again_count == 1


def test_append_pending_persists_across_instances(tmp_path):
    reg1 = CorrectionsRegistry(tmp_path)
    reg1.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])

    reg2 = CorrectionsRegistry(tmp_path)
    [entry] = reg2.all_pending_entries()
    assert entry.trigger["law_id_substring"] == "xx-1"
    assert entry.id == 1


# ---------- promote_to_active ----------

def test_promote_to_active_moves_entry(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    reg.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])

    promoted = reg.promote_to_active(entry_id=1, reviewer="G39248410", note="OK")

    assert promoted.status == "approved"
    assert promoted.reviewer == "G39248410"
    assert promoted.review_note == "OK"
    assert promoted.reviewed_at is not None

    # Pending entry is stamped approved (preserved for audit)
    [pending_entry] = reg.all_pending_entries()
    assert pending_entry.status == "approved"

    # Active side has it too
    [active_entry] = reg.all_active_entries()
    assert active_entry.trigger == promoted.trigger


def test_promote_appears_in_active_rules(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    reg.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])
    reg.promote_to_active(entry_id=1, reviewer="r")

    # Fresh instance — exercises the load path
    reg2 = CorrectionsRegistry(tmp_path)
    assert ("xx-1", "alpha", "xx-2") in reg2.active_law_id_rules()


def test_promote_unknown_id_raises(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    with pytest.raises(ValueError, match="No pending entry"):
        reg.promote_to_active(entry_id=999, reviewer="r")


def test_promote_already_approved_raises(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    reg.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])
    reg.promote_to_active(entry_id=1, reviewer="r")
    with pytest.raises(ValueError, match="only pending entries"):
        reg.promote_to_active(entry_id=1, reviewer="r")


# ---------- reject_pending ----------

def test_reject_moves_to_rejected_array(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    reg.append_pending([_law_id_entry("xx-1", "alpha", "xx-2")])

    rejected = reg.reject_pending(entry_id=1, reviewer="r", reason="false positive")
    assert rejected.status == "rejected"

    # Removed from pending.entries, added to pending.rejected
    assert reg.all_pending_entries() == []
    reg2 = CorrectionsRegistry(tmp_path)
    raw = json.loads((tmp_path / "pending_corrections.json").read_text())
    assert len(raw["rejected"]) == 1
    assert raw["rejected"][0]["review_note"] == "false positive"


def test_reject_unknown_id_raises(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    with pytest.raises(ValueError):
        reg.reject_pending(entry_id=999, reviewer="r", reason="x")


# ---------- registry_hash ----------

def test_registry_hash_stable_when_no_changes(tmp_path):
    reg1 = CorrectionsRegistry(tmp_path)
    h1 = reg1.registry_hash()
    reg2 = CorrectionsRegistry(tmp_path)
    h2 = reg2.registry_hash()
    assert h1 == h2


def test_registry_hash_changes_when_active_grows(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    before = reg.registry_hash()

    reg.append_pending([_law_id_entry("zz-1", "novel", "zz-9")])
    reg.promote_to_active(entry_id=1, reviewer="r")

    # New instance forces a fresh read of active_corrections.json
    after = CorrectionsRegistry(tmp_path).registry_hash()
    assert before != after


def test_registry_hash_unaffected_by_pending(tmp_path):
    """Pending entries don't enter the ACTIVE rule set; the hash must not move."""
    reg = CorrectionsRegistry(tmp_path)
    before = reg.registry_hash()
    reg.append_pending([_law_id_entry("zz-1", "novel", "zz-9")])
    after = CorrectionsRegistry(tmp_path).registry_hash()
    assert before == after


# ---------- section_number type ----------

def test_section_number_entry_round_trip(tmp_path):
    reg = CorrectionsRegistry(tmp_path)
    reg.append_pending([_section_entry("106–382", "USE OF PICK-SLOAN POWER", "SEC. 6.")])
    reg.promote_to_active(entry_id=1, reviewer="r")

    rules = CorrectionsRegistry(tmp_path).active_section_number_rules()
    assert any(r[0] == "106–382" and r[3] == "SEC. 6." for r in rules)
