"""Tests for the hard-freeze guard in pipeline.publisher.publish()."""
import pandas as pd
import pytest

from pipeline.publisher import (
    FINAL_COLUMN_ORDER,
    _existing_main_output,
    publish,
)


def _make_minimal_df() -> pd.DataFrame:
    """A 1-row DataFrame with every column publisher cares about."""
    row = {col: None for col in FINAL_COLUMN_ORDER}
    row.update({
        "UniqueKey": "test-key-0001",
        "KeyVersion": "v0",
        "OriginalOrder": 1,
        "EntryType": "Section",
        "Selection": 0,
        "LawIdentifier": "99-1",
        "LawType": "An Act",
        "LawTitle": "Test",
        "approvedDate": "2026-01-01",
        "IsAppropriation": False,
        "SectionNumber": "Sec. 1.",
        "SectionName": "Test",
        "Text": "Test text",
        "ReviewStatus": "N/A",
    })
    return pd.DataFrame([row])


def test_existing_main_output_returns_none_when_dir_missing(tmp_path):
    assert _existing_main_output(tmp_path, vol=99) is None


def test_existing_main_output_ignores_sme_only(tmp_path):
    vol_dir = tmp_path / "Volume-99"
    vol_dir.mkdir()
    (vol_dir / "STATUTE-99_2026-01-01_SME.xlsx").write_bytes(b"x")
    assert _existing_main_output(tmp_path, vol=99) is None


def test_existing_main_output_finds_main(tmp_path):
    vol_dir = tmp_path / "Volume-99"
    vol_dir.mkdir()
    (vol_dir / "STATUTE-99_2026-01-01.xlsx").write_bytes(b"x")
    found = _existing_main_output(tmp_path, vol=99)
    assert found is not None
    assert found.name == "STATUTE-99_2026-01-01.xlsx"


def test_publish_first_run_succeeds(tmp_path):
    df = _make_minimal_df()
    result = publish(df, tmp_path, vol=99)
    assert "output_path" in result
    assert (tmp_path / "Volume-99").exists()


def test_publish_refuses_second_run_by_default(tmp_path):
    df = _make_minimal_df()
    publish(df, tmp_path, vol=99)
    with pytest.raises(FileExistsError, match="hard freeze"):
        publish(df, tmp_path, vol=99)


def test_publish_force_republish_overrides(tmp_path):
    """force_republish must let a second publish succeed (no FileExistsError)."""
    df = _make_minimal_df()
    publish(df, tmp_path, vol=99, formatted_time="run1")
    # Without force, second call would raise — with force, it returns normally
    result = publish(df, tmp_path, vol=99, formatted_time="run2", force_republish=True)
    assert result["output_path"].endswith("STATUTE-99_run2.xlsx")


def test_publish_records_corrections_provenance(tmp_path):
    df = _make_minimal_df()
    manifest = tmp_path / "manifest.json"
    publish(
        df, tmp_path, vol=99,
        manifest_path=manifest,
        corrections_applied={"active": [4, 7], "pending": [11]},
        corrections_registry_hash="sha256:abc",
    )
    import json
    data = json.loads(manifest.read_text())
    assert data["volumes"]["99"]["corrections_applied"] == {"active": [4, 7], "pending": [11]}
    assert data["volumes"]["99"]["corrections_registry_hash"] == "sha256:abc"


def test_publish_without_provenance_skips_keys(tmp_path):
    df = _make_minimal_df()
    manifest = tmp_path / "manifest.json"
    publish(df, tmp_path, vol=99, manifest_path=manifest)
    import json
    data = json.loads(manifest.read_text())
    entry = data["volumes"]["99"]
    assert "corrections_applied" not in entry
    assert "corrections_registry_hash" not in entry
