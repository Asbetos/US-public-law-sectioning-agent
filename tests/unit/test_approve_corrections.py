"""Tests for the approve_corrections.py CLI."""
import json

import pytest

import approve_corrections as cli
from pipeline.corrections_registry import CorrectionEntry, CorrectionsRegistry


def _seed_one_pending(out_dir):
    reg = CorrectionsRegistry(out_dir)
    reg.append_pending([
        CorrectionEntry(
            id=0,
            type="law_id",
            trigger={"law_id_substring": "yy-1", "title_substring": "alpha"},
            correction={"replace_with_law_id": "yy-2"},
            evidence={"rule_or_signal": "test"},
            discovered_in_vol=42,
        ),
    ])


def test_main_requires_subcommand(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--output-dir", "/tmp"])


def test_list_pending(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    rc = cli.main(["--output-dir", str(tmp_path), "list"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "PENDING (1)" in captured
    assert "#   1" in captured
    assert "yy-1" in captured


def test_show_pending_entry(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    rc = cli.main(["--output-dir", str(tmp_path), "show", "1"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "Entry #1" in captured
    assert "law_id" in captured
    assert "yy-1" in captured


def test_show_missing_entry_exits_nonzero(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    rc = cli.main(["--output-dir", str(tmp_path), "show", "999"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "No entry" in err


def test_approve_promotes_to_active(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    rc = cli.main([
        "--output-dir", str(tmp_path),
        "approve", "1", "--reviewer", "tester", "--note", "looks good",
    ])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "Approved entry #1" in captured

    # Active file now has the entry; pending file is stamped approved
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    assert len(active["entries"]) == 1
    assert active["entries"][0]["status"] == "approved"
    assert active["entries"][0]["reviewer"] == "tester"


def test_approve_already_approved_fails(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    cli.main(["--output-dir", str(tmp_path), "approve", "1", "--reviewer", "tester"])
    rc = cli.main(["--output-dir", str(tmp_path), "approve", "1", "--reviewer", "tester"])
    assert rc == 1


def test_reject_moves_to_rejected_array(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    rc = cli.main([
        "--output-dir", str(tmp_path),
        "reject", "1", "--reason", "false positive", "--reviewer", "tester",
    ])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "Rejected entry #1" in captured

    pending = json.loads((tmp_path / "pending_corrections.json").read_text())
    assert pending["entries"] == []
    assert len(pending["rejected"]) == 1
    assert pending["rejected"][0]["review_note"] == "false positive"


def test_reject_requires_reason(tmp_path):
    _seed_one_pending(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["--output-dir", str(tmp_path), "reject", "1"])


def test_diff_prints_rule_shape(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    rc = cli.main(["--output-dir", str(tmp_path), "diff", "1"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "LAW_ID_CORRECTIONS" in captured
    assert "yy-1" in captured
    assert "yy-2" in captured


def test_show_after_reject_finds_entry(tmp_path, capsys):
    _seed_one_pending(tmp_path)
    cli.main(["--output-dir", str(tmp_path), "reject", "1", "--reason", "x"])
    rc = cli.main(["--output-dir", str(tmp_path), "show", "1"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "status=rejected" in captured
