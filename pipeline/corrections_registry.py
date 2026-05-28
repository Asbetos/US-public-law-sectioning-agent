"""Corrections registry — single source of truth for the corrections lookup.

Merges:
- Python "seed" tables from ``law_id_corrections.py`` (``LAW_ID_CORRECTIONS`` and
  ``SECTION_NUMBER_CORRECTIONS``). Hand-edited; treated as read-only here.
- Approved entries promoted from the pending queue, stored in
  ``processed_output/active_corrections.json``.

The combined ACTIVE set is what the Claude Code subagent is told about ("these
are already fixed; don't re-propose them"), and what is hashed into
``run_manifest.json`` per volume so future operators can detect drift.

The PENDING queue (``processed_output/pending_corrections.json``) is an
append-only proposal log written by the corrector and consumed by the
human-approval CLI. Dedupes on ``(type, trigger, correction)``; duplicate
discoveries bump a ``seen_again_count`` on the existing entry.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_CODE_DIR = str(Path("/home/G39248410/citizen_voice/Code").resolve())
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

# Seed tables (hand-edited in law_id_corrections.py).
from law_id_corrections import (  # noqa: E402
    LAW_ID_CORRECTIONS,
    SECTION_NUMBER_CORRECTIONS,
)

SCHEMA_VERSION = 1


# ---------- entry shape ----------

@dataclass
class CorrectionEntry:
    """One proposed (or approved) correction.

    See PLAN.md §Data Contracts for the on-disk shape this maps to.
    """
    id: int
    type: str                                       # "law_id" | "section_number" | "other"
    trigger: dict[str, Any]                         # what to match
    correction: dict[str, Any]                      # the fix
    evidence: dict[str, Any] = field(default_factory=dict)
    proposed_at: str = ""
    discovered_in_vol: int | None = None
    agent_version: str | None = None
    confidence: float | None = None
    status: str = "pending"                         # pending | approved | rejected | superseded
    reviewer: str | None = None
    review_note: str | None = None
    reviewed_at: str | None = None
    applied_in_runs: list[dict[str, Any]] = field(default_factory=list)
    seen_again_count: int = 0
    # Implementation-tracking fields (cv-coder agent)
    implementation_status: str = "not_required"     # not_required | pending | in_progress | implemented | failed | manual_override
    implementation_commit_sha: str | None = None
    implementation_attempted_at: str | None = None
    implementation_notes: str | None = None

    def dedup_key(self) -> tuple[str, str, str]:
        """Two entries with the same key are considered the same proposal."""
        return (
            self.type,
            json.dumps(self.trigger, sort_keys=True),
            json.dumps(self.correction, sort_keys=True),
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CorrectionEntry":
        """Construct a CorrectionEntry from a plain dict (e.g. from JSON).

        Handles missing keys with sensible defaults, including the
        implementation-tracking fields added for the cv-coder agent.
        """
        ptype = d.get("type", "other")
        default_impl_status = "pending" if ptype == "other" else "not_required"
        return cls(
            id=d["id"],
            type=ptype,
            trigger=d.get("trigger", {}),
            correction=d.get("correction", {}),
            evidence=d.get("evidence", {}),
            proposed_at=d.get("proposed_at", ""),
            discovered_in_vol=d.get("discovered_in_vol"),
            agent_version=d.get("agent_version"),
            confidence=d.get("confidence"),
            status=d.get("status", "pending"),
            reviewer=d.get("reviewer"),
            review_note=d.get("review_note"),
            reviewed_at=d.get("reviewed_at"),
            applied_in_runs=d.get("applied_in_runs", []),
            seen_again_count=d.get("seen_again_count", 0),
            implementation_status=d.get("implementation_status", default_impl_status),
            implementation_commit_sha=d.get("implementation_commit_sha"),
            implementation_attempted_at=d.get("implementation_attempted_at"),
            implementation_notes=d.get("implementation_notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON storage."""
        return {
            "id": self.id,
            "type": self.type,
            "trigger": self.trigger,
            "correction": self.correction,
            "evidence": self.evidence,
            "proposed_at": self.proposed_at,
            "discovered_in_vol": self.discovered_in_vol,
            "agent_version": self.agent_version,
            "confidence": self.confidence,
            "status": self.status,
            "reviewer": self.reviewer,
            "review_note": self.review_note,
            "reviewed_at": self.reviewed_at,
            "applied_in_runs": self.applied_in_runs,
            "seen_again_count": self.seen_again_count,
            "implementation_status": self.implementation_status,
            "implementation_commit_sha": self.implementation_commit_sha,
            "implementation_attempted_at": self.implementation_attempted_at,
            "implementation_notes": self.implementation_notes,
        }


# ---------- on-disk file shape ----------

@dataclass
class _RegistryFile:
    schema_version: int = SCHEMA_VERSION
    next_id: int = 1
    entries: list[CorrectionEntry] = field(default_factory=list)
    rejected: list[CorrectionEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "next_id": self.next_id,
            "entries": [e.to_dict() for e in self.entries],
            "rejected": [e.to_dict() for e in self.rejected],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_RegistryFile":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            next_id=data.get("next_id", 1),
            entries=[CorrectionEntry.from_dict(e) for e in data.get("entries", [])],
            rejected=[CorrectionEntry.from_dict(e) for e in data.get("rejected", [])],
        )


# ---------- helpers ----------

def _load_file(path: Path) -> _RegistryFile:
    if not path.exists():
        return _RegistryFile()
    return _RegistryFile.from_dict(json.loads(path.read_text()))


def _save_file_atomic(file_data: _RegistryFile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(file_data.to_dict(), indent=2, sort_keys=True))
    tmp.replace(path)


def _seed_law_id_rules_canonical() -> list[tuple[str, str, str]]:
    """Seed list in deterministic order, for hashing."""
    return sorted(tuple(r) for r in LAW_ID_CORRECTIONS)


def _seed_section_number_rules_canonical() -> list[tuple[str, str, str, str]]:
    """Seed list in deterministic order, for hashing."""
    return sorted(
        (r[0], r[1], r[2] or "", r[3]) for r in SECTION_NUMBER_CORRECTIONS
    )


# ---------- public API ----------

class CorrectionsRegistry:
    """Read + write the corrections registry files in a workspace.

    Lazy-loads both files on first access. After mutations, the on-disk file
    is rewritten atomically (temp + rename).
    """

    def __init__(self, processed_output_dir):
        self._out = Path(processed_output_dir)
        self._active_path = self._out / "active_corrections.json"
        self._pending_path = self._out / "pending_corrections.json"
        self._active: _RegistryFile | None = None
        self._pending: _RegistryFile | None = None

    # ---- properties ----

    @property
    def active_path(self) -> Path:
        return self._active_path

    @property
    def pending_path(self) -> Path:
        return self._pending_path

    @property
    def active(self) -> _RegistryFile:
        if self._active is None:
            self._active = _load_file(self._active_path)
        return self._active

    @property
    def pending(self) -> _RegistryFile:
        if self._pending is None:
            self._pending = _load_file(self._pending_path)
        return self._pending

    # ---- rule lookup (for the LLM + manifest hash) ----

    def active_law_id_rules(self) -> list[tuple[str, str, str]]:
        """Combined seed + approved law-ID rules in the tuple format used by
        ``apply_law_id_corrections``."""
        rules = list(LAW_ID_CORRECTIONS)
        for e in self.active.entries:
            if e.status == "approved" and e.type == "law_id":
                rules.append((
                    e.trigger.get("law_id_substring", ""),
                    e.trigger.get("title_substring", ""),
                    e.correction.get("replace_with_law_id", ""),
                ))
        return rules

    def active_section_number_rules(self) -> list[tuple[str, str, str | None, str]]:
        """Combined seed + approved section-number rules in the tuple format
        used by ``apply_section_number_correction``."""
        rules = list(SECTION_NUMBER_CORRECTIONS)
        for e in self.active.entries:
            if e.status == "approved" and e.type == "section_number":
                rules.append((
                    e.trigger.get("law_id_substring", ""),
                    e.trigger.get("heading_substring", ""),
                    e.trigger.get("text_substring", None),
                    e.correction.get("replace_with_section_number", ""),
                ))
        return rules

    def registry_hash(self) -> str:
        """SHA-256 hex of the merged ACTIVE rule set, in canonical order.

        Recorded per volume in ``run_manifest.json`` so future operators can
        detect when a volume was processed against a different correction set
        than is currently active.
        """
        h = hashlib.sha256()
        for rule in sorted(self.active_law_id_rules()):
            h.update(json.dumps(rule, sort_keys=True).encode("utf-8"))
        h.update(b"|sep|")
        # Section rules contain Optional[str] — normalize for sort
        normalized = sorted(
            (r[0], r[1], r[2] or "", r[3]) for r in self.active_section_number_rules()
        )
        for rule in normalized:
            h.update(json.dumps(rule, sort_keys=True).encode("utf-8"))
        return h.hexdigest()

    # ---- pending queue ----

    def all_pending_entries(self) -> list[CorrectionEntry]:
        return list(self.pending.entries)

    def all_active_entries(self) -> list[CorrectionEntry]:
        return list(self.active.entries)

    def find_in_pending(self, entry_id: int) -> CorrectionEntry | None:
        for e in self.pending.entries:
            if e.id == entry_id:
                return e
        return None

    def append_pending(self, new_entries: list[CorrectionEntry]) -> int:
        """Append new proposals, deduping by ``(type, trigger, correction)``.

        Duplicate proposals bump ``seen_again_count`` on the existing entry
        and record the new ``applied_in_runs`` entry. Returns the count of
        *novel* entries appended (not the count seen-again).
        """
        if not new_entries:
            return 0
        pending = self.pending  # ensure loaded
        existing_by_key: dict[tuple[str, str, str], CorrectionEntry] = {
            e.dedup_key(): e for e in pending.entries
        }
        novel = 0
        for entry in new_entries:
            key = entry.dedup_key()
            if key in existing_by_key:
                existing = existing_by_key[key]
                existing.seen_again_count += 1
                for run in entry.applied_in_runs:
                    if run not in existing.applied_in_runs:
                        existing.applied_in_runs.append(run)
                continue
            entry.id = pending.next_id
            pending.next_id += 1
            if not entry.proposed_at:
                entry.proposed_at = datetime.now().isoformat()
            entry.status = "pending"
            pending.entries.append(entry)
            existing_by_key[key] = entry
            novel += 1
        _save_file_atomic(pending, self._pending_path)
        return novel

    def promote_to_active(
        self, entry_id: int, reviewer: str, note: str | None = None
    ) -> CorrectionEntry:
        """Move a pending entry to active. The same entry is preserved on
        both sides, but the pending copy is stamped ``status="approved"`` so
        the audit trail stays intact."""
        pending = self.pending
        active = self.active

        entry = self.find_in_pending(entry_id)
        if entry is None:
            raise ValueError(f"No pending entry with id {entry_id}")
        if entry.status != "pending":
            raise ValueError(
                f"Entry {entry_id} is {entry.status!r}; only pending entries can be promoted"
            )

        entry.status = "approved"
        entry.reviewer = reviewer
        entry.review_note = note
        entry.reviewed_at = datetime.now().isoformat()

        # Append a copy to the active side
        active_copy = CorrectionEntry(**asdict(entry))
        active.entries.append(active_copy)

        _save_file_atomic(pending, self._pending_path)
        _save_file_atomic(active, self._active_path)
        return active_copy

    def reject_pending(
        self, entry_id: int, reviewer: str, reason: str
    ) -> CorrectionEntry:
        """Move a pending entry into the rejected array. Preserved for audit;
        not loaded into the active rule set."""
        pending = self.pending
        entry = self.find_in_pending(entry_id)
        if entry is None:
            raise ValueError(f"No pending entry with id {entry_id}")
        if entry.status != "pending":
            raise ValueError(
                f"Entry {entry_id} is {entry.status!r}; only pending entries can be rejected"
            )

        entry.status = "rejected"
        entry.reviewer = reviewer
        entry.review_note = reason
        entry.reviewed_at = datetime.now().isoformat()

        pending.entries.remove(entry)
        pending.rejected.append(entry)
        _save_file_atomic(pending, self._pending_path)
        return entry

    # ---- implementation tracking ----

    def mark_in_progress(self, entry_ids: list[int]) -> None:
        """Flip one or more entries' ``implementation_status`` to ``in_progress``.

        Stamps ``implementation_attempted_at`` to ``datetime.now().isoformat()`` for
        each affected entry. Searches BOTH ``active_corrections.json`` and
        ``pending_corrections.json`` so family-batch operations (where the
        just-approved entry has been promoted to active but its siblings are still
        in pending) work correctly. Saves both files atomically when changed.
        Silently skips IDs not found in either file.
        """
        if not entry_ids:
            return
        target = set(entry_ids)
        now = datetime.now().isoformat()
        active = self.active
        pending = self.pending
        changed_active = False
        changed_pending = False
        for e in active.entries:
            if e.id in target:
                e.implementation_status = "in_progress"
                e.implementation_attempted_at = now
                changed_active = True
        for e in pending.entries:
            if e.id in target:
                e.implementation_status = "in_progress"
                e.implementation_attempted_at = now
                changed_pending = True
        if changed_active:
            _save_file_atomic(active, self._active_path)
        if changed_pending:
            _save_file_atomic(pending, self._pending_path)

    # ---- migration helpers ----

    def migrate_implementation_status(self) -> int:
        """Backfill the implementation_status field on existing on-disk entries.

        For each entry in active_corrections.json AND pending_corrections.json
        whose underlying dict lacks an 'implementation_status' key, write a
        default ('pending' for type=other; 'not_required' otherwise) and zero
        the three companion tracking fields. Saves atomically. Returns the
        count of entries actually updated. Idempotent — running twice is a
        no-op."""
        updated = 0
        for path in (self._active_path, self._pending_path):
            if not path.exists():
                continue
            data = json.loads(path.read_text())
            for entry in data.get("entries", []) + data.get("rejected", []):
                if "implementation_status" not in entry:
                    default = "pending" if entry.get("type") == "other" else "not_required"
                    entry["implementation_status"] = default
                    entry["implementation_commit_sha"] = None
                    entry["implementation_attempted_at"] = None
                    entry["implementation_notes"] = None
                    updated += 1
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            tmp.replace(path)
        return updated

    # ---- bootstrap ----

    @staticmethod
    def bootstrap_files(processed_output_dir) -> dict[str, str]:
        """Create empty ``active_corrections.json`` and
        ``pending_corrections.json`` if they don't exist yet. Returns a dict
        ``{path: action}`` where action is ``"created"`` or ``"existed"``."""
        out = Path(processed_output_dir)
        out.mkdir(parents=True, exist_ok=True)
        result: dict[str, str] = {}
        for name in ("active_corrections.json", "pending_corrections.json"):
            path = out / name
            if path.exists():
                result[str(path)] = "existed"
            else:
                _save_file_atomic(_RegistryFile(), path)
                result[str(path)] = "created"
        return result
