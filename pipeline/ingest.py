"""Ingestion / bootstrap stage.

Responsibilities:
- ``bootstrap_workspace()``: idempotently materialize the local ``processed_output/``
  directory and (optionally) seed lookup files from a source dir. **No lookup
  files are seeded by default** — the pipeline treats local
  ``processed_output/AgencyList.xlsx`` and ``processed_output/DivisionMapping.xlsx``
  as the source of truth and never reads back from production. Callers that
  want a one-time seed must pass ``lookup_files`` explicitly (e.g. via the
  ``seed_lookup_files.py`` operator CLI).
- ``build_manifest()``: walk the source XML dir, record SHA-256 + mtime per
  STATUTE-*.xml, write ``processed_output/run_manifest.json`` atomically.
- ``check_incremental()``: True if a volume's recorded XML hash matches the
  current source AND its declared output file exists AND status == "success".
- ``update_volume_status()``: helper to record run results back into the manifest.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

# Empty by default: the pipeline runner never re-seeds lookup files from
# production. Local copies are authoritative. A one-time seed must be
# explicit (pass ``lookup_files=("AgencyList.xlsx", "DivisionMapping.xlsx")``).
DEFAULT_LOOKUP_FILES: tuple[str, ...] = ()


def bootstrap_workspace(processed_output_dir, source_xml_dir, lookup_files=DEFAULT_LOOKUP_FILES):
    """Create the workspace dirs; optionally seed lookup files from source.

    ``lookup_files`` defaults to ``()`` — no seeding. The pipeline runner
    relies on this default so that production lookup files (which may be
    periodically restored to a fixed baseline by external IT processes)
    cannot revert locally appended rows in
    ``processed_output/AgencyList.xlsx`` or
    ``processed_output/DivisionMapping.xlsx``.

    Seeding is opt-in: the ``seed_lookup_files.py`` operator CLI passes
    the lookup filenames explicitly to copy from source ON FIRST INSTALL.
    Even then, an existing local copy is never overwritten (idempotent).
    """
    out = Path(processed_output_dir)
    src = Path(source_xml_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scratch").mkdir(exist_ok=True)
    copied = []
    for name in lookup_files:
        src_path = src / name
        dst_path = out / name
        if dst_path.exists():
            continue
        if not src_path.exists():
            raise FileNotFoundError(f"Lookup file missing from source: {src_path}")
        shutil.copy2(src_path, dst_path)
        copied.append(name)
    return {"output_dir": str(out), "copied": copied}


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"volumes": {}}
    return json.loads(p.read_text())


def _save_manifest(manifest: dict, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.replace(p)


def build_manifest(xml_dir, manifest_path):
    """Scan source XML dir; record SHA-256 + mtime per STATUTE-*.xml; write atomically.

    If a volume's XML hash has changed since the previous manifest entry, the
    entry's ``status`` is cleared (the existing output is now stale relative to
    the new input). Other fields (``output_path``, etc.) are preserved so the
    operator can still see what was last produced.
    """
    xml_dir = Path(xml_dir)
    manifest = _load_manifest(manifest_path)
    for xml_file in sorted(xml_dir.glob("STATUTE-*.xml")):
        vol = xml_file.stem.replace("STATUTE-", "")
        if not vol.isdigit():
            continue
        entry = manifest["volumes"].setdefault(vol, {})
        new_hash = _sha256(xml_file)
        if entry.get("xml_sha256") and entry["xml_sha256"] != new_hash:
            entry["status"] = "stale"
        entry["xml_path"] = str(xml_file)
        entry["xml_sha256"] = new_hash
        entry["xml_mtime"] = datetime.fromtimestamp(xml_file.stat().st_mtime).isoformat()
    _save_manifest(manifest, manifest_path)
    return manifest


def check_incremental(vol, manifest_path, xml_dir) -> bool:
    """True iff the volume's manifest hash matches the current source XML AND its
    declared output_path exists AND the last status was 'success'."""
    manifest = _load_manifest(manifest_path)
    entry = manifest["volumes"].get(str(vol))
    if not entry:
        return False
    xml_path = Path(xml_dir) / f"STATUTE-{vol}.xml"
    if not xml_path.exists():
        return False
    if _sha256(xml_path) != entry.get("xml_sha256"):
        return False
    if entry.get("status") != "success":
        return False
    out = entry.get("output_path")
    if not out or not Path(out).exists():
        return False
    return True


def update_volume_status(manifest_path, vol, **fields) -> None:
    """Merge ``fields`` into ``vol``'s manifest entry; stamp ``last_run`` to now."""
    manifest = _load_manifest(manifest_path)
    entry = manifest["volumes"].setdefault(str(vol), {})
    entry.update(fields)
    entry["last_run"] = datetime.now().isoformat()
    _save_manifest(manifest, manifest_path)
