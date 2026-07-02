"""Tests for skills/cv-coder/finalize_implementation.py."""
import json
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/skills/cv-coder/finalize_implementation.py")
_spec = importlib.util.spec_from_file_location("finalize_implementation", _MODULE)
fi = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fi
_spec.loader.exec_module(fi)


def _seed_response(tmp_path, response_obj, task_id=50):
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    (scratch / f"coder_response_{task_id}.json").write_text(json.dumps(response_obj))
    return scratch / f"coder_response_{task_id}.json"


def _seed_registry(tmp_path, entry_ids=(50,)):
    """Create active + pending registry files with given entry_ids as type=other in_progress."""
    active = {"schema_version": 1, "next_id": 100, "entries": [
        {
            "id": eid, "type": "other",
            "trigger": {}, "correction": {}, "evidence": {},
            "proposed_at": "2026-05-28T00:00:00",
            "discovered_in_vol": 75, "agent_version": "x",
            "confidence": 0.8, "status": "approved",
            "applied_in_runs": [], "seen_again_count": 0,
            "reviewer": None, "review_note": None, "reviewed_at": None,
            "implementation_status": "in_progress",
            "implementation_commit_sha": None,
            "implementation_attempted_at": "2026-05-28T00:00:01",
            "implementation_notes": None,
        } for eid in entry_ids
    ], "rejected": []}
    (tmp_path / "active_corrections.json").write_text(json.dumps(active))
    (tmp_path / "pending_corrections.json").write_text(
        '{"schema_version": 1, "next_id": 100, "entries": [], "rejected": []}')
    # Task JSON
    (tmp_path / "scratch").mkdir(exist_ok=True)
    (tmp_path / "scratch" / f"coder_task_{entry_ids[0]}.json").write_text(json.dumps({
        "task_id": entry_ids[0], "entry_ids": list(entry_ids), "family": "null-num",
        "queued_at": "2026-05-28T00:00:00", "approver": "test",
        "registry_entries": [], "context_files": [], "constraints": [],
    }))


def test_success_path_commits_and_marks_implemented(tmp_path):
    resp = _seed_response(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py", "tests/unit/test_new.py"],
        "tests_added": ["test_new_thing"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "added walk_part", "notes": "",
    })
    _seed_registry(tmp_path, entry_ids=(50,))
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "117 passed")), \
         patch.object(fi, "_git_commit_and_capture_sha", return_value="abc123"), \
         patch.object(fi, "_invoke_republish", return_value=True):
        rc = fi.main(["--task-id", "50",
                      "--response", str(resp),
                      "--output-dir", str(tmp_path)])
    assert rc == 0
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "implemented"
    assert e["implementation_commit_sha"] == "abc123"


def test_multi_entry_batch_updates_all_entries(tmp_path):
    resp = _seed_response(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py", "tests/unit/test_new.py"],
        "tests_added": ["test_a", "test_b"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "fused null-num fix", "notes": "",
    }, task_id=2)
    _seed_registry(tmp_path, entry_ids=(2, 14, 15, 16))
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "ok")), \
         patch.object(fi, "_git_commit_and_capture_sha", return_value="deadbeef"), \
         patch.object(fi, "_invoke_republish", return_value=True):
        rc = fi.main(["--task-id", "2", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 0
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    for eid in (2, 14, 15, 16):
        e = next(x for x in active["entries"] if x["id"] == eid)
        assert e["implementation_status"] == "implemented"
        assert e["implementation_commit_sha"] == "deadbeef"


def test_coder_status_failed_marks_failed_and_reverts(tmp_path):
    resp = _seed_response(tmp_path, {"status": "failed", "files_modified": ["parser/uslm_parser.py"],
                                      "notes": "couldn't get the test red"})
    _seed_registry(tmp_path, entry_ids=(50,))
    revert_called = []
    with patch.object(fi, "_git_revert_files", side_effect=lambda f, repo_root=None: revert_called.extend(f)):
        rc = fi.main(["--task-id", "50", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 1
    assert "parser/uslm_parser.py" in revert_called
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "failed"


def test_unparseable_response_marks_failed(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    resp = scratch / "coder_response_50.json"
    resp.write_text("this is not json at all")
    _seed_registry(tmp_path, entry_ids=(50,))
    rc = fi.main(["--task-id", "50", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "failed"


def test_pytest_gate_red_marks_failed(tmp_path):
    resp = _seed_response(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py"],
        "tests_added": ["test_x"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "lies"},
        "diff_summary": "x", "notes": "",
    })
    _seed_registry(tmp_path, entry_ids=(50,))
    with patch.object(fi, "_run_pytest_gate", return_value=(False, "FAILED tests/unit/test_old.py")), \
         patch.object(fi, "_git_revert_files", return_value=None):
        rc = fi.main(["--task-id", "50", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "failed"


def test_scope_violation_marks_failed(tmp_path):
    resp = _seed_response(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py", "settings.json"],
        "tests_added": ["test_x"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "x", "notes": "",
    })
    _seed_registry(tmp_path, entry_ids=(50,))
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "ok")), \
         patch.object(fi, "_git_revert_files", return_value=None):
        rc = fi.main(["--task-id", "50", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "failed"
    assert "settings.json" in e["implementation_notes"]


def test_no_new_tests_marks_failed(tmp_path):
    resp = _seed_response(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py"],
        "tests_added": [],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "x", "notes": "",
    })
    _seed_registry(tmp_path, entry_ids=(50,))
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "ok")), \
         patch.object(fi, "_git_revert_files", return_value=None):
        rc = fi.main(["--task-id", "50", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "failed"
    assert "no new tests" in e["implementation_notes"].lower()


def test_republish_failure_does_not_revert(tmp_path):
    """If commit lands but republish fails, the entry stays implemented; warning only."""
    resp = _seed_response(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py", "tests/unit/test_new.py"],
        "tests_added": ["test_x"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "x", "notes": "",
    })
    _seed_registry(tmp_path, entry_ids=(50,))
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "ok")), \
         patch.object(fi, "_git_commit_and_capture_sha", return_value="abc"), \
         patch.object(fi, "_invoke_republish", return_value=False):
        rc = fi.main(["--task-id", "50", "--response", str(resp), "--output-dir", str(tmp_path)])
    assert rc == 0  # commit landed; republish failure is a warning, not a hard failure
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = next(x for x in active["entries"] if x["id"] == 50)
    assert e["implementation_status"] == "implemented"
