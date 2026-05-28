"""Tests for the type=other confirmation + family-batch prompt."""
import json
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/approve_corrections.py")
_spec = importlib.util.spec_from_file_location("approve_corrections", _MODULE)
ac = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ac
_spec.loader.exec_module(ac)


def _make_entry(eid, type_, *, pattern="", description="", impl_status=None, status="pending"):
    if impl_status is None:
        impl_status = "pending" if type_ == "other" else "not_required"
    return {
        "id": eid, "type": type_,
        "trigger": {"law_id_substring": "X", "pattern": pattern},
        "correction": {"description": description},
        "evidence": {},
        "proposed_at": "2026-05-28T00:00:00",
        "discovered_in_vol": 75, "agent_version": "x",
        "confidence": 0.8, "status": status,
        "applied_in_runs": [], "seen_again_count": 0,
        "reviewer": None, "review_note": None, "reviewed_at": None,
        "implementation_status": impl_status,
        "implementation_commit_sha": None,
        "implementation_attempted_at": None,
        "implementation_notes": None,
    }


def _seed(tmp_path, *, pending_entries=None, active_entries=None):
    (tmp_path / "pending_corrections.json").write_text(json.dumps({
        "schema_version": 1, "next_id": 100,
        "entries": pending_entries or [], "rejected": []
    }))
    (tmp_path / "active_corrections.json").write_text(json.dumps({
        "schema_version": 1, "next_id": 100,
        "entries": active_entries or [], "rejected": []
    }))
    (tmp_path / "scratch").mkdir(exist_ok=True)


def test_law_id_does_not_prompt(tmp_path, monkeypatch):
    _seed(tmp_path, pending_entries=[_make_entry(60, "law_id")])
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("no prompt")))
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "60"])
    assert rc == 0


def test_other_single_y_queues(tmp_path, monkeypatch):
    _seed(tmp_path, pending_entries=[_make_entry(50, "other", pattern="unique snowflake")])
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "50"])
    assert rc == 0
    task = json.loads((tmp_path / "scratch" / "coder_task_50.json").read_text())
    assert task["entry_ids"] == [50]
    assert task["family"] == "none"
    assert len(task["registry_entries"]) == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "in_progress"


def test_other_single_n_skips(tmp_path, monkeypatch):
    _seed(tmp_path, pending_entries=[_make_entry(50, "other", pattern="unique")])
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "50"])
    assert rc == 0
    assert not (tmp_path / "scratch" / "coder_task_50.json").exists()
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "pending"


def test_other_family_yes_batches(tmp_path, monkeypatch):
    pending = [
        _make_entry(2, "other", pattern="SectionNumber is null collapse"),
        _make_entry(14, "other", pattern="leading section with no <num>"),
    ]
    _seed(tmp_path, pending_entries=pending)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "14"])
    assert rc == 0
    task = json.loads((tmp_path / "scratch" / "coder_task_14.json").read_text())
    assert sorted(task["entry_ids"]) == [2, 14]
    assert task["family"] == "null-num"
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    pending_f = json.loads((tmp_path / "pending_corrections.json").read_text())
    all_e = {e["id"]: e for e in active["entries"] + pending_f["entries"]}
    assert all_e[2]["implementation_status"] == "in_progress"
    assert all_e[14]["implementation_status"] == "in_progress"


def test_other_family_n_falls_back_to_single(tmp_path, monkeypatch):
    pending = [
        _make_entry(2, "other", pattern="SectionNumber is null collapse"),
        _make_entry(14, "other", pattern="leading section with no <num>"),
    ]
    _seed(tmp_path, pending_entries=pending)
    answers = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "14"])
    assert rc == 0
    task = json.loads((tmp_path / "scratch" / "coder_task_14.json").read_text())
    assert task["entry_ids"] == [14]


def test_other_family_empty_input_defaults_to_y(tmp_path, monkeypatch):
    pending = [
        _make_entry(2, "other", pattern="SectionNumber is null"),
        _make_entry(14, "other", pattern="no <num>"),
    ]
    _seed(tmp_path, pending_entries=pending)
    monkeypatch.setattr("builtins.input", lambda *_: "")  # empty = Y
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "14"])
    assert rc == 0
    task = json.loads((tmp_path / "scratch" / "coder_task_14.json").read_text())
    assert sorted(task["entry_ids"]) == [2, 14]


def test_other_single_empty_input_defaults_to_n(tmp_path, monkeypatch):
    _seed(tmp_path, pending_entries=[_make_entry(50, "other", pattern="unique")])
    monkeypatch.setattr("builtins.input", lambda *_: "")
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "50"])
    assert rc == 0
    assert not (tmp_path / "scratch" / "coder_task_50.json").exists()
