"""Tests for pipeline.ingest."""
import json

from pipeline.ingest import (
    bootstrap_workspace,
    build_manifest,
    check_incremental,
    update_volume_status,
)


def test_bootstrap_workspace_no_lookup_seeding_by_default(tmp_path):
    """Default: only creates dirs; does NOT seed lookup files from src.

    The pipeline runner relies on this so production lookup files cannot
    revert local appended rows.
    """
    out = tmp_path / "out"
    src = tmp_path / "src"
    src.mkdir()
    (src / "AgencyList.xlsx").write_bytes(b"agency-bytes")
    (src / "DivisionMapping.xlsx").write_bytes(b"div-bytes")

    result = bootstrap_workspace(out, src)
    assert out.exists()
    assert (out / "scratch").exists()
    assert not (out / "AgencyList.xlsx").exists()
    assert not (out / "DivisionMapping.xlsx").exists()
    assert result["copied"] == []


def test_bootstrap_workspace_explicit_lookup_seeding(tmp_path):
    """Opt-in seeding via the lookup_files kwarg (used by seed_lookup_files.py)."""
    out = tmp_path / "out"
    src = tmp_path / "src"
    src.mkdir()
    (src / "AgencyList.xlsx").write_bytes(b"agency-bytes")
    (src / "DivisionMapping.xlsx").write_bytes(b"div-bytes")

    result = bootstrap_workspace(
        out, src, lookup_files=("AgencyList.xlsx", "DivisionMapping.xlsx"),
    )
    assert (out / "AgencyList.xlsx").read_bytes() == b"agency-bytes"
    assert (out / "DivisionMapping.xlsx").read_bytes() == b"div-bytes"
    assert set(result["copied"]) == {"AgencyList.xlsx", "DivisionMapping.xlsx"}


def test_bootstrap_workspace_idempotent_preserves_local_edits(tmp_path):
    out = tmp_path / "out"
    src = tmp_path / "src"
    src.mkdir()
    (src / "AgencyList.xlsx").write_bytes(b"agency-bytes")

    lookup = ("AgencyList.xlsx",)
    bootstrap_workspace(out, src, lookup_files=lookup)
    (out / "AgencyList.xlsx").write_bytes(b"local-edits")
    result = bootstrap_workspace(out, src, lookup_files=lookup)

    assert (out / "AgencyList.xlsx").read_bytes() == b"local-edits"
    assert result["copied"] == []


def test_bootstrap_workspace_missing_source_raises_when_seeding(tmp_path):
    out = tmp_path / "out"
    src = tmp_path / "src"
    src.mkdir()  # missing the requested file
    import pytest
    with pytest.raises(FileNotFoundError):
        bootstrap_workspace(out, src, lookup_files=("AgencyList.xlsx",))


def test_build_manifest_skips_non_volume_files(tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "STATUTE-1.xml").write_bytes(b"<x/>")
    (xml_dir / "STATUTE-2.xml").write_bytes(b"<y/>")
    (xml_dir / "STATUTE-abc.xml").write_bytes(b"<z/>")  # non-numeric -> skip
    (xml_dir / "notes.txt").write_text("ignore")        # non-XML -> skip

    manifest = build_manifest(xml_dir, tmp_path / "manifest.json")
    assert set(manifest["volumes"].keys()) == {"1", "2"}
    for v in manifest["volumes"].values():
        assert "xml_sha256" in v
        assert "xml_mtime" in v


def test_check_incremental_lifecycle(tmp_path):
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "STATUTE-1.xml").write_bytes(b"<x/>")
    manifest_path = tmp_path / "manifest.json"

    build_manifest(xml_dir, manifest_path)
    # No output declared yet
    assert not check_incremental("1", manifest_path, xml_dir)

    # Declare success + output
    output_path = tmp_path / "out.xlsx"
    output_path.write_bytes(b"x")
    update_volume_status(manifest_path, "1", status="success", output_path=str(output_path))
    assert check_incremental("1", manifest_path, xml_dir)

    # Mutate source XML -> hash differs -> incremental fails
    (xml_dir / "STATUTE-1.xml").write_bytes(b"<changed/>")
    build_manifest(xml_dir, manifest_path)
    # build_manifest doesn't reset status, but the hash changed
    assert not check_incremental("1", manifest_path, xml_dir)


def test_update_volume_status_stamps_last_run(tmp_path):
    manifest_path = tmp_path / "m.json"
    update_volume_status(manifest_path, "5", status="failed")
    data = json.loads(manifest_path.read_text())
    assert data["volumes"]["5"]["status"] == "failed"
    assert "last_run" in data["volumes"]["5"]
