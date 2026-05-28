"""Tests for validation.report.ValidationReport."""
import json

from validation.report import ValidationReport


def test_report_minimal_passed():
    r = ValidationReport(vol=114)
    assert r.vol == 114
    assert r.passed == []
    assert r.failed == []
    assert r.warnings == []
    assert r.status == "passed"
    assert r.timestamp  # auto-stamped


def test_report_failed_dominates_warning():
    r = ValidationReport(vol=114, failed=["row count mismatch"], warnings=["some warn"])
    assert r.status == "failed"


def test_report_warning_only():
    r = ValidationReport(vol=114, warnings=["selection size 580 < 600"])
    assert r.status == "warning"


def test_report_to_json_roundtrip():
    r = ValidationReport(vol=114, row_count=3831, law_count=288)
    d = json.loads(r.to_json())
    assert d["vol"] == 114
    assert d["row_count"] == 3831
    assert d["law_count"] == 288
    assert d["status"] == "passed"


def test_report_to_file(tmp_path):
    r = ValidationReport(vol=99, failed=["err"])
    out = tmp_path / "sub" / "report.json"
    r.to_file(out)
    assert out.exists()
    assert json.loads(out.read_text())["status"] == "failed"
