# cv-coder Autonomous Coding Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap where approved `type: "other"` corrections describe extractor-code changes but no actor implements them. Add an autonomous Claude Code subagent (the "cv-coder") that — once the operator approves a correction AND confirms auto-implementation — writes a failing regression test, implements the fix in `parser/uslm_parser.py`, runs the full test suite, and reports a structured result for human-gated commit.

**Architecture:** Three integration layers:

1. **Registry honesty** — extend `CorrectionEntry` with `implementation_status` + tracking fields; fix `apply_corrections_and_publish.py` so it stops listing un-implemented `type: "other"` entries as "applied" in the manifest.
2. **Approval-time confirmation** — extend `approve_corrections.py approve <id>` with a confirmation prompt for `type: "other"` entries that queues a coder task to `processed_output/scratch/coder_task_<id>.json`.
3. **cv-coder skill** — new Claude Code skill at `skills/cv-coder/` that reads a queued task, dispatches an Opus subagent (TDD-disciplined, scope-guarded, `ultrathink`), parses the structured JSON response, gates on a green `pytest`, then either commits the fix to a feature branch (human reviews + merges) or marks the entry `implementation_status = "failed"`.

The orchestrator lives in the operator's Claude Code session. The coder runs as a dispatched subagent. The CLI handles bookkeeping for terminal-only operators; the skill handles end-to-end inside Claude Code.

**Tech Stack:** Python 3.11.6, `dataclasses`, `pandas`, `lxml`, `pytest`, `openpyxl`, `git`, Claude Code `Agent` tool with `model: opus` + `ultrathink` reasoning directive.

---

## REVISION SHEET (2026-05-28, operator decisions)

The original draft asked four design questions. Operator answered:

1. **Direct-to-main commits, no human merge gate.** The cv-coder skill does NOT create a feature branch. The coder makes its edits in the main working tree but **does NOT commit**. The finalize helper's pytest gate is the only safety net — if it passes, finalize commits to main; if it fails, finalize runs `git checkout -- <modified files>` to revert and the entry is marked `failed`.
2. **Auto-chain re-publish.** After finalize marks the entry(ies) `implemented`, it automatically invokes `re_publish_after_fix.py --entry <id> --yes` for the primary entry. No second confirmation prompt.
3. **Batch mode for grouped refinements.** A new helper `pipeline/correction_families.py` classifies entries into families by `trigger.pattern` keywords:
   - `null-num`: #2, #14, #15, #16
   - `top-level-container`: #3, #7, #11, #17
   - `sibling-appropriations`: #5
   - `sibling-level`: #13
   - `none`: anything that doesn't match a family
   `approve_corrections.py` detects family eligibility at approve-time and offers to batch all pending family members into ONE coder task. The task JSON carries an `entry_ids` list (multiple). The coder writes ONE fused diff covering all entries. Finalize updates all entries' status together.
4. **Feature branches (moot under direct-to-main).** Use ordinary git branches if any branching ever happens. Currently nothing creates branches.

These supersede conflicting instructions in tasks 4, 5, 6, 7 below. Tasks 1, 2, 3, 8-11 are unchanged. **Task 3b is new** (correction_families helper); subsequent task numbers shift by 1.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `skills/cv-coder/SKILL.md` | Orchestration playbook: load task JSON, dispatch coder subagent, run finalize helper |
| `skills/cv-coder/system_prompt.md` | The coder's instructions — TDD discipline, scope guards, output schema |
| `skills/cv-coder/finalize_implementation.py` | Parses coder JSON, runs final `pytest` gate, updates registry status, prints diff for human review |
| `re_publish_after_fix.py` | CLI: given an implemented correction id, identifies affected volumes (via validation-report scan) and re-publishes them |
| `tests/unit/test_correction_entry_implementation_fields.py` | Unit tests for the new `CorrectionEntry` fields + migration semantics |
| `tests/unit/test_approve_corrections_other_confirmation.py` | Unit tests for the approval-time confirmation prompt + task-queue side effect |
| `tests/unit/test_finalize_implementation.py` | Unit tests for the post-coder helper (parse, gate, status update) |
| `tests/unit/test_apply_corrections_implementation_filter.py` | Unit tests for the manifest-honesty filter |
| `tests/unit/test_re_publish_after_fix.py` | Unit tests for the re-publish CLI's affected-volume identification |

### Modified files

| Path | Change |
|---|---|
| `pipeline/corrections_registry.py:CorrectionEntry` | Add four implementation fields; backfill on `from_dict`; new helper `mark_implementation_*` methods |
| `approve_corrections.py:_cmd_approve` | After promotion, prompt for auto-implementation if `type == "other"`; write coder task JSON; set `implementation_status = "in_progress"` |
| `apply_corrections_and_publish.py:main` | Filter `corrections_applied.active` so it lists only IDs where `implementation_status in ("not_required", "implemented")` |
| `README.md` | New section: "cv-coder workflow" with the end-to-end approval → implement → re-publish sequence |

### One-shot migration

| Path | One-shot operation |
|---|---|
| `processed_output/active_corrections.json` | Backfill `implementation_status` field on all 16 existing entries: `not_required` for `law_id`/`section_number`; `pending` for the 10 existing `other` entries |

---

## Task 1: Add four implementation-tracking fields to `CorrectionEntry`

**Files:**
- Modify: `pipeline/corrections_registry.py`
- Test: `tests/unit/test_correction_entry_implementation_fields.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_correction_entry_implementation_fields.py`:

```python
"""Tests for the implementation-tracking fields on CorrectionEntry."""
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/pipeline/corrections_registry.py")
_spec = importlib.util.spec_from_file_location("corrections_registry", _MODULE)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

CorrectionEntry = mod.CorrectionEntry


def _base_entry_dict(**overrides):
    base = {
        "id": 99,
        "type": "other",
        "trigger": {"law_id_substring": "X"},
        "correction": {"description": "do Y"},
        "evidence": {},
        "proposed_at": "2026-05-28T00:00:00",
        "discovered_in_vol": 75,
        "agent_version": "cv-correct@0.1.0",
        "confidence": None,
        "status": "approved",
        "applied_in_runs": [],
        "seen_again_count": 0,
        "reviewer": None,
        "review_note": None,
        "reviewed_at": None,
    }
    base.update(overrides)
    return base


def test_correction_entry_has_implementation_fields():
    e = CorrectionEntry.from_dict(_base_entry_dict())
    assert hasattr(e, "implementation_status")
    assert hasattr(e, "implementation_commit_sha")
    assert hasattr(e, "implementation_attempted_at")
    assert hasattr(e, "implementation_notes")


def test_implementation_status_defaults_pending_for_other_type():
    e = CorrectionEntry.from_dict(_base_entry_dict(type="other", status="approved"))
    assert e.implementation_status == "pending"


def test_implementation_status_defaults_not_required_for_law_id():
    e = CorrectionEntry.from_dict(_base_entry_dict(type="law_id"))
    assert e.implementation_status == "not_required"


def test_implementation_status_defaults_not_required_for_section_number():
    e = CorrectionEntry.from_dict(_base_entry_dict(type="section_number"))
    assert e.implementation_status == "not_required"


def test_existing_dict_implementation_status_is_preserved():
    e = CorrectionEntry.from_dict(_base_entry_dict(
        type="other", implementation_status="implemented",
        implementation_commit_sha="abc123",
    ))
    assert e.implementation_status == "implemented"
    assert e.implementation_commit_sha == "abc123"


def test_to_dict_round_trips_implementation_fields():
    e = CorrectionEntry.from_dict(_base_entry_dict(
        type="other", implementation_status="failed",
        implementation_notes="pytest red on new test",
    ))
    d = e.to_dict()
    assert d["implementation_status"] == "failed"
    assert d["implementation_notes"] == "pytest red on new test"
    e2 = CorrectionEntry.from_dict(d)
    assert e2.implementation_status == "failed"
    assert e2.implementation_notes == "pytest red on new test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline && source /home/G39248410/citizen_voice/venv/bin/activate && python -m pytest tests/unit/test_correction_entry_implementation_fields.py -v`
Expected: FAIL — `AttributeError: 'CorrectionEntry' object has no attribute 'implementation_status'`

- [ ] **Step 3: Add the four fields + defaults to `CorrectionEntry`**

In `pipeline/corrections_registry.py`, locate the `@dataclass` declaration of `CorrectionEntry`. Add the four new fields with `field(default=...)`. Update the `from_dict` classmethod to read them with defaults. Update the `to_dict` method to write them.

```python
# In the CorrectionEntry dataclass declaration, add after the existing fields:
implementation_status: str = "not_required"      # not_required | pending | in_progress | implemented | failed | manual_override
implementation_commit_sha: str | None = None
implementation_attempted_at: str | None = None
implementation_notes: str | None = None

# In from_dict, after constructing the kwargs from `d`, add:
ptype = d.get("type")
default_impl = "pending" if ptype == "other" else "not_required"
kwargs["implementation_status"] = d.get("implementation_status", default_impl)
kwargs["implementation_commit_sha"] = d.get("implementation_commit_sha")
kwargs["implementation_attempted_at"] = d.get("implementation_attempted_at")
kwargs["implementation_notes"] = d.get("implementation_notes")

# In to_dict, add these to the returned dict:
"implementation_status": self.implementation_status,
"implementation_commit_sha": self.implementation_commit_sha,
"implementation_attempted_at": self.implementation_attempted_at,
"implementation_notes": self.implementation_notes,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_correction_entry_implementation_fields.py -v`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Run full suite to verify no regressions**

Run: `python -m pytest tests/ -x`
Expected: PASS — full count (was 103) is now 108.

- [ ] **Step 6: Commit**

```bash
git add pipeline/corrections_registry.py tests/unit/test_correction_entry_implementation_fields.py
git commit -m "Add implementation-tracking fields to CorrectionEntry

Fields: implementation_status (not_required|pending|in_progress|implemented|
failed|manual_override), implementation_commit_sha, implementation_attempted_at,
implementation_notes. Defaults: 'pending' for type=other approved entries,
'not_required' for law_id and section_number (which are auto-applied by the
publisher already). Backwards-compatible round-trip on existing JSON."
```

---

## Task 2: Backfill helper for the live registry + run the one-shot migration

**Files:**
- Modify: `pipeline/corrections_registry.py` (add `migrate_implementation_status` method)
- Test: `tests/unit/test_correction_entry_implementation_fields.py` (extend)
- One-shot: `processed_output/active_corrections.json`, `processed_output/pending_corrections.json`

- [ ] **Step 1: Add backfill test**

Append to `tests/unit/test_correction_entry_implementation_fields.py`:

```python
def test_registry_migrate_implementation_status_backfills(tmp_path):
    CorrectionsRegistry = mod.CorrectionsRegistry
    # Seed both files WITHOUT the new field
    active = tmp_path / "active_corrections.json"
    active.write_text("""
    {"schema_version": 1, "next_id": 5, "entries": [
      {"id": 1, "type": "law_id", "trigger": {}, "correction": {},
       "evidence": {}, "proposed_at": "2026-01-01T00:00:00",
       "discovered_in_vol": 60, "agent_version": "x", "confidence": null,
       "status": "approved", "applied_in_runs": [], "seen_again_count": 0,
       "reviewer": null, "review_note": null, "reviewed_at": null},
      {"id": 2, "type": "other", "trigger": {}, "correction": {},
       "evidence": {}, "proposed_at": "2026-01-01T00:00:00",
       "discovered_in_vol": 75, "agent_version": "x", "confidence": null,
       "status": "approved", "applied_in_runs": [], "seen_again_count": 0,
       "reviewer": null, "review_note": null, "reviewed_at": null}
    ], "rejected": []}
    """)
    pending = tmp_path / "pending_corrections.json"
    pending.write_text('{"schema_version": 1, "next_id": 5, "entries": [], "rejected": []}')

    r = CorrectionsRegistry(tmp_path)
    n = r.migrate_implementation_status()
    assert n == 2  # both active entries needed a default written

    # Re-read and verify file content has the new field
    import json
    d = json.loads(active.read_text())
    by_id = {e["id"]: e for e in d["entries"]}
    assert by_id[1]["implementation_status"] == "not_required"
    assert by_id[2]["implementation_status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_correction_entry_implementation_fields.py::test_registry_migrate_implementation_status_backfills -v`
Expected: FAIL — `AttributeError: 'CorrectionsRegistry' object has no attribute 'migrate_implementation_status'`

- [ ] **Step 3: Add `migrate_implementation_status` method**

In `pipeline/corrections_registry.py`, add to the `CorrectionsRegistry` class:

```python
def migrate_implementation_status(self) -> int:
    """Backfill the implementation_status field on existing entries.

    For each entry in active_corrections.json AND pending_corrections.json
    whose underlying dict lacks an 'implementation_status' key, write a
    default ('pending' for type=other; 'not_required' otherwise). Saves
    atomically. Returns the count of entries actually updated."""
    import json
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
        # atomic write
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
    return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_correction_entry_implementation_fields.py -v`
Expected: PASS — 6 tests pass.

- [ ] **Step 5: Back up + migrate the live registry**

```bash
cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline
cp processed_output/active_corrections.json processed_output/active_corrections.json.pre-impl-migration
cp processed_output/pending_corrections.json processed_output/pending_corrections.json.pre-impl-migration
source /home/G39248410/citizen_voice/venv/bin/activate
python -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from pipeline.corrections_registry import CorrectionsRegistry
r = CorrectionsRegistry(Path('processed_output'))
n = r.migrate_implementation_status()
print(f'Backfilled {n} entries.')"
```

Expected output: `Backfilled 32 entries.` (16 active + 16 pending mirrors).

- [ ] **Step 6: Verify the live registry**

Run:
```bash
python -c "
import json
d = json.load(open('processed_output/active_corrections.json'))
for e in d['entries']:
    print(f\"  #{e['id']:>3}  type={e['type']:<14}  status={e['status']}  implementation_status={e['implementation_status']}\")"
```

Expected: 16 lines. IDs 4, 12, 18 (law_id) and IDs 19, 20, 21 (section_number) show `implementation_status=not_required`. IDs 2, 3, 5, 7, 11, 13, 14, 15, 16, 17 (other) show `implementation_status=pending`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/corrections_registry.py tests/unit/test_correction_entry_implementation_fields.py \
        processed_output/active_corrections.json processed_output/pending_corrections.json \
        processed_output/active_corrections.json.pre-impl-migration \
        processed_output/pending_corrections.json.pre-impl-migration
git commit -m "Backfill implementation_status on existing registry entries

Migration helper CorrectionsRegistry.migrate_implementation_status() walks
both active_corrections.json and pending_corrections.json and writes a
default implementation_status field where missing: 'pending' for type=other,
'not_required' for type in (law_id, section_number). Ran the one-shot
migration on the live registry: 10 type=other entries now show 'pending',
6 data-rule entries show 'not_required'. Pre-migration backups saved."
```

---

## Task 3: Filter manifest's `corrections_applied.active` by implementation status

**Files:**
- Modify: `apply_corrections_and_publish.py` (around line 205, the `active_ids` assignment)
- Test: `tests/unit/test_apply_corrections_implementation_filter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_apply_corrections_implementation_filter.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_apply_corrections_implementation_filter.py -v`
Expected: FAIL — `AttributeError: module 'acp_mod' has no attribute '_filter_active_ids_for_manifest'`

- [ ] **Step 3: Add the filter helper + wire it in**

In `apply_corrections_and_publish.py`, add a new top-level function and replace the existing `active_ids = [...]` line.

Add helper (near the other private helpers):

```python
def _filter_active_ids_for_manifest(entries) -> list[int]:
    """Return IDs to report in manifest.corrections_applied.active.

    Honesty rule: a type=other entry with implementation_status='pending' or
    'failed' is approved-but-not-yet-implemented. The publisher does NOT
    auto-apply such entries to the DataFrame (only law_id and section_number
    rules are auto-applied). Including 'pending' entries in the manifest
    would falsely claim they were applied. So we filter."""
    APPLIED_STATES = ("not_required", "implemented", "manual_override")
    return [
        e.id for e in entries
        if e.status == "approved"
        and getattr(e, "implementation_status", "not_required") in APPLIED_STATES
    ]
```

Modify the existing line in `main()` (was at ~205):

```python
# OLD:
# active_ids = [e.id for e in registry.all_active_entries() if e.status == "approved"]
# NEW:
active_ids = _filter_active_ids_for_manifest(registry.all_active_entries())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_apply_corrections_implementation_filter.py -v`
Expected: PASS — 6 tests pass.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -x`
Expected: PASS — full count is now 114 (was 108 after Task 1).

- [ ] **Step 6: Commit**

```bash
git add apply_corrections_and_publish.py tests/unit/test_apply_corrections_implementation_filter.py
git commit -m "Manifest honesty: filter corrections_applied.active by impl status

A type=other entry with implementation_status='pending' or 'failed' is
approved-but-not-implemented; the publisher does not auto-apply such
entries to the DataFrame. Listing them in the manifest would falsely
claim they were applied. New _filter_active_ids_for_manifest only
admits IDs whose entry has implementation_status in (not_required,
implemented, manual_override)."
```

---

## Task 4: Confirmation prompt + coder-task queue in `approve_corrections.py`

**Files:**
- Modify: `approve_corrections.py` (the `_cmd_approve` function)
- Test: `tests/unit/test_approve_corrections_other_confirmation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_approve_corrections_other_confirmation.py`:

```python
"""Tests for the type=other confirmation prompt + coder task queuing."""
import json
import importlib.util
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/approve_corrections.py")
_spec = importlib.util.spec_from_file_location("approve_corrections", _MODULE)
ac = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ac
_spec.loader.exec_module(ac)


def _seed_pending_other(tmp_path) -> Path:
    """Write a pending_corrections.json with one type=other entry and
    an empty active_corrections.json. Returns processed_output_dir."""
    pending = {
        "schema_version": 1, "next_id": 100, "entries": [{
            "id": 50, "type": "other",
            "trigger": {"law_id_substring": "X"},
            "correction": {"description": "do Y"},
            "evidence": {},
            "proposed_at": "2026-05-28T00:00:00",
            "discovered_in_vol": 84, "agent_version": "cv-correct@0.1.0",
            "confidence": 0.8, "status": "pending",
            "applied_in_runs": [], "seen_again_count": 0,
            "reviewer": None, "review_note": None, "reviewed_at": None,
            "implementation_status": "pending",
            "implementation_commit_sha": None,
            "implementation_attempted_at": None,
            "implementation_notes": None,
        }], "rejected": []
    }
    (tmp_path / "pending_corrections.json").write_text(json.dumps(pending))
    (tmp_path / "active_corrections.json").write_text(
        '{"schema_version": 1, "next_id": 100, "entries": [], "rejected": []}'
    )
    (tmp_path / "scratch").mkdir()
    return tmp_path


def test_approve_other_with_y_queues_task(tmp_path, monkeypatch, capsys):
    out_dir = _seed_pending_other(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    rc = ac.main(["--output-dir", str(out_dir), "approve", "50", "--note", "ok"])
    assert rc == 0

    # Coder task written
    task_path = out_dir / "scratch" / "coder_task_50.json"
    assert task_path.exists()
    task = json.loads(task_path.read_text())
    assert task["entry_id"] == 50
    assert task["registry_entry"]["correction"]["description"] == "do Y"

    # Entry's implementation_status is now in_progress
    active = json.loads((out_dir / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "in_progress"
    assert e["implementation_attempted_at"] is not None

    # Stdout points operator to the next step
    out = capsys.readouterr().out
    assert "coder_task_50.json" in out
    assert "cv-coder" in out.lower()


def test_approve_other_with_n_skips_queue(tmp_path, monkeypatch):
    out_dir = _seed_pending_other(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    rc = ac.main(["--output-dir", str(out_dir), "approve", "50"])
    assert rc == 0

    # No coder task written
    assert not (out_dir / "scratch" / "coder_task_50.json").exists()

    # Entry's implementation_status stays at 'pending'
    active = json.loads((out_dir / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "pending"


def test_approve_law_id_does_not_prompt(tmp_path, monkeypatch):
    # Seed a law_id entry instead; confirm that input() is never called
    pending = {
        "schema_version": 1, "next_id": 100, "entries": [{
            "id": 60, "type": "law_id",
            "trigger": {"law_id_substring": "x", "title_substring": "y"},
            "correction": {"replace_with_law_id": "z"},
            "evidence": {}, "proposed_at": "2026-05-28T00:00:00",
            "discovered_in_vol": 60, "agent_version": "x", "confidence": 0.9,
            "status": "pending", "applied_in_runs": [], "seen_again_count": 0,
            "reviewer": None, "review_note": None, "reviewed_at": None,
            "implementation_status": "not_required",
            "implementation_commit_sha": None,
            "implementation_attempted_at": None,
            "implementation_notes": None,
        }], "rejected": []
    }
    (tmp_path / "pending_corrections.json").write_text(json.dumps(pending))
    (tmp_path / "active_corrections.json").write_text(
        '{"schema_version": 1, "next_id": 100, "entries": [], "rejected": []}'
    )

    def _no_input(*_):
        raise AssertionError("approve should not prompt for law_id")
    monkeypatch.setattr("builtins.input", _no_input)
    rc = ac.main(["--output-dir", str(tmp_path), "approve", "60"])
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_approve_corrections_other_confirmation.py -v`
Expected: FAIL — coder task file is not created.

- [ ] **Step 3: Modify `_cmd_approve` to prompt + queue**

In `approve_corrections.py`, locate `_cmd_approve` (or whichever function the `approve` subcommand dispatches to). After the existing `registry.promote_to_active(...)` call, add the conditional confirmation + task queue:

```python
# In _cmd_approve, after promote_to_active succeeds and you have the promoted entry `e`:
if e.type == "other":
    answer = input(
        f"\n⚙ Entry #{e.id} is type='other' — it describes an extractor-code change.\n"
        f"  Auto-implement now via the cv-coder agent? [y/N]: "
    ).strip().lower()
    if answer == "y":
        _queue_coder_task(args.output_dir, e, reviewer=registry._current_reviewer())
        print(
            f"\n  cv-coder task queued at "
            f"{Path(args.output_dir) / 'scratch' / f'coder_task_{e.id}.json'}\n"
            f"  In your Claude Code session, invoke the cv-coder skill:\n"
            f"    \"implement correction {e.id} with cv-coder\"\n"
            f"  (or in a terminal, the task can be picked up later — it persists.)"
        )

# New helper at module level:
def _queue_coder_task(output_dir, entry, *, reviewer: str) -> None:
    from datetime import datetime
    import json
    scratch = Path(output_dir) / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    task = {
        "task_id": entry.id,
        "entry_id": entry.id,
        "queued_at": datetime.now().isoformat(),
        "approver": reviewer,
        "registry_entry": entry.to_dict(),
        "context_files": [
            "parser/uslm_parser.py",
            "tests/unit/test_uslm_parser.py",
        ],
        "constraints": [
            "Add at least one regression test in tests/unit/ that fails on the OLD code and passes on the NEW code.",
            "Do not modify pipeline/corrections_registry.py, run_pipeline.py, processed_output/*, settings, CI, or .gitignore.",
            "Do not delete or rename existing tests.",
            "All edits must be confined to parser/, pipeline/, and tests/.",
            "Run `pytest tests/ -x` as a final gate. Report status='failed' if any pre-existing test breaks."
        ]
    }
    task_path = scratch / f"coder_task_{entry.id}.json"
    task_path.write_text(json.dumps(task, indent=2))
    # Flip the entry's implementation_status to in_progress
    entry.implementation_status = "in_progress"
    entry.implementation_attempted_at = datetime.now().isoformat()
```

Then re-save the active registry after mutating `entry.implementation_status`. Find where `promote_to_active` saves and add a `registry.save()` call (or directly mutate via a new `mark_in_progress(id)` method on the registry — that's cleaner. Add this method to `CorrectionsRegistry`):

```python
# Add to pipeline/corrections_registry.py:CorrectionsRegistry
def mark_in_progress(self, entry_id: int) -> None:
    """Flip an active entry's implementation_status to in_progress + stamp time."""
    from datetime import datetime
    self._load_active_if_needed()
    for i, e in enumerate(self._active["entries"]):
        if e["id"] == entry_id:
            e["implementation_status"] = "in_progress"
            e["implementation_attempted_at"] = datetime.now().isoformat()
            break
    self._save_active()
```

Update `_queue_coder_task` in `approve_corrections.py` to call `registry.mark_in_progress(entry.id)` instead of mutating `entry` directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_approve_corrections_other_confirmation.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -x`
Expected: PASS — full count is now 117.

- [ ] **Step 6: Commit**

```bash
git add approve_corrections.py pipeline/corrections_registry.py \
        tests/unit/test_approve_corrections_other_confirmation.py
git commit -m "approve_corrections: prompt + queue coder task for type=other

After promoting a type=other entry to active, prompt the operator: 'Auto-
implement now via the cv-coder agent? [y/N]'. On 'y', write a queued task
JSON to scratch/coder_task_<id>.json containing the full entry, the
context-file list, and the scope constraints, then flip the entry's
implementation_status to 'in_progress' via CorrectionsRegistry.mark_in_progress.
The cv-coder skill (next task) consumes the queued task. Law-id and
section-number entries skip the prompt entirely."
```

---

## Task 5: Scaffold the cv-coder skill — SKILL.md

**Files:**
- Create: `skills/cv-coder/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

Create `skills/cv-coder/SKILL.md` with this exact content:

```markdown
---
name: cv-coder
description: |
  Pick up a queued cv-coder task (`processed_output/scratch/coder_task_<id>.json`)
  and dispatch an Opus subagent to implement the approved type=other correction
  by editing parser code in parser/uslm_parser.py, writing a failing
  regression test first, running the full pytest suite, and reporting back a
  structured JSON result. Use when the operator says "implement correction
  <id> with cv-coder", "/cv-coder implement <id>", "run the coder agent on
  task <id>", or when they confirm auto-implementation during an
  approve_corrections.py approval.
---

# cv-coder Skill

This skill is the Claude Code orchestrator for implementing approved
`type: "other"` extractor-code corrections.

## Trigger

The operator invokes this skill after running `approve_corrections.py approve <id>`
with `y` to the auto-implement confirmation, OR by directly saying
"implement correction N with cv-coder" inside a Claude Code session.

## Per-task workflow

### Step 1 — Load the queued task

Read `processed_output/scratch/coder_task_<N>.json`. If missing, abort and
tell the operator to run `python approve_corrections.py approve <N>` first.

### Step 2 — Create a feature branch (worktree-isolated)

```bash
git checkout -b cv-coder-impl-<N>
```

This keeps the main branch clean. If the coder's diff is bad, the branch is
discarded; main is untouched.

### Step 3 — Dispatch the coder subagent

Read `skills/cv-coder/system_prompt.md`. Embed the task JSON. Dispatch the
`Agent` tool:

```
subagent_type: general-purpose
model: opus
description: "cv-coder: implement correction #<N>"
prompt: <the filled system_prompt.md + the task body + the reasoning directive>
```

**Always pass `model: opus`** — the coder's job (reading the parser,
designing a test that captures the bug from a plain-language description,
implementing the fix without regressions) requires the strongest available
model. Do not substitute Sonnet or Haiku.

The reasoning directive (append verbatim to the prompt):

> Think very hard about the change. Before writing any production code:
> (1) read parser/uslm_parser.py in full and identify the function(s) the
> fix must touch; (2) write a minimal XML fixture in your new test that
> exercises the bug from the affected_examples; (3) write a failing test
> that asserts the expected post-fix output; (4) verify the test fails
> against the current code via `pytest tests/<your_new_test>.py::<name>`;
> (5) implement the minimal change; (6) verify the new test passes AND the
> full suite (`pytest tests/ -x`) is green. If you cannot meet all six
> conditions, return status="failed" or status="needs_human" with a clear
> reason. ultrathink.

### Step 4 — Save the subagent's response

Write the subagent's text response to
`processed_output/scratch/coder_response_<N>.json` for audit.

### Step 5 — Run the finalize helper

```bash
python skills/cv-coder/finalize_implementation.py \
    --task-id <N> \
    --response processed_output/scratch/coder_response_<N>.json \
    --output-dir processed_output \
    --branch cv-coder-impl-<N>
```

The helper:
- Parses the coder's JSON
- Verifies status == "success"
- Verifies `pytest tests/ -x` still passes (final gate)
- Verifies the diff only touches parser/, pipeline/, tests/
- Verifies at least one new test was added
- Captures the commit SHA on the feature branch
- Updates the registry entry's implementation_status to "implemented" (success)
  or "failed" (any gate failed)

### Step 6 — Present the diff for human review

After finalize succeeds:

```bash
git log --oneline cv-coder-impl-<N> ^main
git diff main..cv-coder-impl-<N>
```

Echo the diff to the operator. Wait for their confirmation:

> Merge cv-coder-impl-<N> into main? [y/N]

On `y`:
```bash
git checkout main && git merge --no-ff cv-coder-impl-<N> -m "Merge cv-coder fix for correction #<N>"
```

On `N`: leave the branch in place for the operator to inspect. The
registry still shows `implementation_status="implemented"` and the commit
SHA, but the branch hasn't been merged. The operator can run
`git branch -D cv-coder-impl-<N>` to discard, or merge manually later.

### Step 7 — Tell the operator about affected volumes

After merge, suggest the re-publish step:

> Correction #<N>'s fix is now in main. To re-publish the affected volumes:
>
>   python re_publish_after_fix.py --entry <N>

## Failure modes

| Failure | Behavior |
|---|---|
| Task file missing | Abort; tell operator to run `approve_corrections.py approve <N>` |
| Subagent times out / errors | finalize_implementation marks entry "failed"; branch preserved for inspection |
| Subagent's JSON unparseable | finalize_implementation marks entry "failed"; raw response in scratch |
| Pytest red on subagent's branch | finalize_implementation marks "failed"; branch preserved |
| Subagent modified disallowed files | finalize_implementation marks "failed"; branch preserved |
| Subagent returned status="needs_human" | finalize_implementation marks "failed"; surface the explanation |

The branch is ALWAYS preserved on failure so the operator can read the
attempt. To discard: `git branch -D cv-coder-impl-<N>`.

## Hard prohibitions

- Never dispatch without `model: opus` — the cost savings of weaker models
  are dwarfed by the cost of broken parser code mutating real published data
- Never merge to main without the human confirmation in Step 6
- Never modify the registry's `implementation_status` outside the finalize
  helper — keep all state changes in one place
- Never skip the final pytest gate — the subagent's "I'm done" claim is
  unverified until the orchestrator's `pytest tests/ -x` is green
```

- [ ] **Step 2: Verify the SKILL.md is readable + has the trigger phrase**

Run:
```bash
head -10 skills/cv-coder/SKILL.md
grep -c "implement correction" skills/cv-coder/SKILL.md
```

Expected: First command shows the frontmatter; second prints `2` or higher (the trigger phrase appears in description + workflow).

- [ ] **Step 3: Commit**

```bash
git add skills/cv-coder/SKILL.md
git commit -m "Add cv-coder skill orchestration playbook (SKILL.md)

Per-task seven-step workflow: load queued task -> create feature branch ->
dispatch Opus subagent with ultrathink directive -> save response ->
finalize gate (pytest + scope + new-test) -> human merge confirm ->
suggest re-publish. Branch-per-fix isolation keeps main clean on
failure. Hard prohibitions: never weaken the model, never merge
without human confirm, never bypass the pytest gate."
```

---

## Task 6: cv-coder skill — system_prompt.md

**Files:**
- Create: `skills/cv-coder/system_prompt.md`

- [ ] **Step 1: Write system_prompt.md**

Create `skills/cv-coder/system_prompt.md`:

```markdown
# cv-coder subagent — system prompt (per-task)

> **Template the orchestrator embeds in each Agent dispatch.** Fill the
> placeholders at the bottom, then send.

You are implementing an approved `type: "other"` correction from the
citizen_voice U.S. Statutes-at-Large pipeline. Your job is to read the
plain-language description, identify the parser code that needs to change,
write a failing regression test FIRST, implement the fix, and verify the
full test suite is green.

## Background

The pipeline parses USLM XML (`STATUTE-N.xml` from GPO) into a per-section
DataFrame. The extractor lives in `parser/uslm_parser.py`. Each volume's
pLaws (`<pLaw>` elements) are walked, sections enumerated, and rows emitted
with a deterministic `UniqueKey` derived from the section's position. A
class of bugs — silently-dropped pLaws, null SectionNumbers collapsing to
identical UniqueKeys — are what `type: "other"` corrections describe.

The full task JSON the orchestrator passes you contains:

- `registry_entry.correction.description` — plain-English description of
  the required change (the human-readable spec).
- `registry_entry.correction.affected_examples` — concrete pLaw / line
  references in real XML you can use to drive your fixture design.
- `registry_entry.trigger.pattern` — a one-line signature of the XML
  pattern the fix addresses.
- `context_files` — the files most likely to need editing.
- `constraints` — the hard scope rules you must obey.

## TDD discipline — non-negotiable

1. **Read `parser/uslm_parser.py` in full.** Do not just grep for the
   relevant function — read the entire file. The walker functions are
   small but interact; you need the whole picture.
2. **Read the existing tests** in `tests/unit/test_*.py` that touch the
   parser. Match the style (fixture construction, naming).
3. **Write a failing regression test FIRST.** Build a minimal XML fixture
   in-test (a literal multi-line string) that exercises ONE of the
   `affected_examples`. The test must:
   - Assert the post-fix expected behavior (e.g. "PL X-Y produces N rows
     with sequential ordinals 1, 2, 3").
   - Fail on the current code (because the fix isn't in yet).
4. **Verify the test fails.** Run:
   `pytest tests/unit/<your_new_test_file>.py::<your_test_name> -v`
   Confirm: FAIL (not ERROR — a fixture problem doesn't count as the
   regression test failing for the right reason).
5. **Implement the minimal change** in `parser/uslm_parser.py`. The smaller
   the diff, the better. Do not refactor unrelated code.
6. **Verify the new test passes.** Run the same `pytest` command.
   Confirm: PASS.
7. **Run the full suite.** `pytest tests/ -x`. Every existing test must
   still pass. If any pre-existing test fails, your change is regressive —
   return `status: "failed"`.

## Scope guard — files you may touch

| Path | May edit? |
|---|---|
| `parser/uslm_parser.py` | ✅ Yes — the primary target |
| `parser/appr_parser.py`, `parser/law_id_utils.py` | ✅ Yes — if directly relevant |
| `pipeline/segmenter.py`, `pipeline/enricher.py`, `pipeline/publisher.py` | ✅ Yes — only if the description explicitly requires it |
| `tests/unit/*.py` | ✅ Yes — create new test files, edit existing tests is allowed only to ADD assertions, never to remove or weaken |
| `pipeline/corrections_registry.py`, `apply_corrections_and_publish.py`, `approve_corrections.py` | ❌ NO — these are orchestration; not your concern |
| `run_pipeline.py`, `seed_lookup_files.py`, `add_agencies.py` | ❌ NO |
| `processed_output/*`, `*.json`, `*.xlsx` | ❌ NO — runtime state |
| `settings.json`, `.gitignore`, CI files, `pyproject.toml`, `requirements.txt` | ❌ NO |

If your fix would require touching a forbidden file, do not proceed.
Return `status: "needs_human"` with an explanation pointing at the file
and what change is needed.

## Output schema — JSON only

Return **a single JSON object** at the end of your response. Free-form text
before or after is allowed (the orchestrator extracts the first valid
JSON blob), but the JSON must be present and parseable.

```json
{
  "status": "success" | "failed" | "needs_human",
  "files_modified": ["parser/uslm_parser.py", "tests/unit/test_NEW.py"],
  "tests_added": ["test_walk_part_containers_emits_rows_per_section"],
  "test_results": {
    "new_test_initially_red": true,
    "new_test_now_green": true,
    "full_suite_pass": true,
    "pytest_summary": "117 passed in 0.81s"
  },
  "diff_summary": "Added handle_part_containers(elem) in uslm_parser.py; extended walk_sections to invoke it when <main> has no direct <section> child. New test fixtures: minimal <pLaw> with <main><part>...",
  "notes": "Used minimal fixture for PL 87-195 shape. Did not generalize to <chapter> (that's correction #11)."
}
```

If `status != "success"`, fill `notes` with the specific blocker.

## Per-task payload (filled by the orchestrator)

You are implementing correction #{TASK_ID}.

REGISTRY ENTRY:
```json
{REGISTRY_ENTRY_JSON}
```

CONTEXT FILES (paths to read first):
```
{CONTEXT_FILES_LIST}
```

CONSTRAINTS (re-read before each commit):
```
{CONSTRAINTS_LIST}
```

## Reasoning directive

Think very hard about the change. Before writing any production code:

(1) read `parser/uslm_parser.py` in full and identify the function(s) the
fix must touch;

(2) write a minimal XML fixture in your new test that exercises the bug
from the `affected_examples`;

(3) write a failing test that asserts the expected post-fix output;

(4) verify the test fails against the current code via
`pytest tests/<your_new_test>.py::<name>`;

(5) implement the minimal change;

(6) verify the new test passes AND the full suite (`pytest tests/ -x`)
is green.

If you cannot meet all six conditions, return `status="failed"` or
`status="needs_human"` with a clear reason. ultrathink.
```

- [ ] **Step 2: Verify the prompt is well-formed**

Run:
```bash
grep -c "ultrathink" skills/cv-coder/system_prompt.md
grep -c "status.*success" skills/cv-coder/system_prompt.md
```

Expected: First `1`, second `1` (the schema example).

- [ ] **Step 3: Commit**

```bash
git add skills/cv-coder/system_prompt.md
git commit -m "Add cv-coder system_prompt.md (TDD + scope + JSON output schema)

Embeds the task body and instructs the Opus subagent to: read the parser
in full, write a failing regression test FIRST, implement the minimal
fix, gate on the full pytest suite. Scope-guard table forbids editing
registry / orchestration / CI / settings. Output is a single JSON
object with status + files + test_results + diff_summary."
```

---

## Task 7: cv-coder skill — finalize_implementation.py

**Files:**
- Create: `skills/cv-coder/finalize_implementation.py`
- Test: `tests/unit/test_finalize_implementation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_finalize_implementation.py`:

```python
"""Tests for the post-coder finalize helper."""
import json
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/skills/cv-coder/finalize_implementation.py")
_spec = importlib.util.spec_from_file_location("finalize_implementation", _MODULE)
fi = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fi
_spec.loader.exec_module(fi)


def _seed(tmp_path, response_obj, task_id=50):
    (tmp_path / "scratch").mkdir(exist_ok=True)
    resp_path = tmp_path / "scratch" / f"coder_response_{task_id}.json"
    resp_path.write_text(json.dumps(response_obj))
    # Seed an active entry the helper can update
    active = {"schema_version": 1, "next_id": 100, "entries": [{
        "id": task_id, "type": "other",
        "trigger": {}, "correction": {}, "evidence": {},
        "proposed_at": "2026-05-28T00:00:00", "discovered_in_vol": 84,
        "agent_version": "x", "confidence": 0.8, "status": "approved",
        "applied_in_runs": [], "seen_again_count": 0,
        "reviewer": None, "review_note": None, "reviewed_at": None,
        "implementation_status": "in_progress",
        "implementation_commit_sha": None,
        "implementation_attempted_at": "2026-05-28T00:00:01",
        "implementation_notes": None,
    }], "rejected": []}
    (tmp_path / "active_corrections.json").write_text(json.dumps(active))
    (tmp_path / "pending_corrections.json").write_text(
        '{"schema_version": 1, "next_id": 100, "entries": [], "rejected": []}'
    )
    return resp_path


def test_finalize_success_marks_implemented(tmp_path):
    """A clean coder response + green pytest gate -> status=implemented."""
    resp_path = _seed(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py", "tests/unit/test_new.py"],
        "tests_added": ["test_new_thing"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "117 passed"},
        "diff_summary": "added walk_part",
        "notes": "ok",
    })
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "117 passed")), \
         patch.object(fi, "_assert_scope_clean", return_value=True), \
         patch.object(fi, "_git_capture_head_sha", return_value="abc123"):
        rc = fi.main([
            "--task-id", "50",
            "--response", str(resp_path),
            "--output-dir", str(tmp_path),
            "--branch", "cv-coder-impl-50",
        ])
    assert rc == 0
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "implemented"
    assert e["implementation_commit_sha"] == "abc123"


def test_finalize_failed_status_marks_failed(tmp_path):
    """Coder explicitly returned status=failed -> entry.implementation_status=failed."""
    resp_path = _seed(tmp_path, {
        "status": "failed",
        "notes": "couldn't get the test red",
    })
    rc = fi.main([
        "--task-id", "50",
        "--response", str(resp_path),
        "--output-dir", str(tmp_path),
        "--branch", "cv-coder-impl-50",
    ])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "failed"
    assert "couldn't get the test red" in e["implementation_notes"]


def test_finalize_unparseable_response_marks_failed(tmp_path):
    """Garbage in the response file -> failed + clear notes."""
    (tmp_path / "scratch").mkdir(exist_ok=True)
    resp_path = tmp_path / "scratch" / "coder_response_50.json"
    resp_path.write_text("this is not json")
    (tmp_path / "active_corrections.json").write_text(json.dumps({
        "schema_version": 1, "next_id": 100, "entries": [{
            "id": 50, "type": "other",
            "trigger": {}, "correction": {}, "evidence": {},
            "proposed_at": "2026-05-28T00:00:00", "discovered_in_vol": 84,
            "agent_version": "x", "confidence": 0.8, "status": "approved",
            "applied_in_runs": [], "seen_again_count": 0,
            "reviewer": None, "review_note": None, "reviewed_at": None,
            "implementation_status": "in_progress",
            "implementation_commit_sha": None,
            "implementation_attempted_at": "2026-05-28T00:00:01",
            "implementation_notes": None,
        }], "rejected": []
    }))
    (tmp_path / "pending_corrections.json").write_text(
        '{"schema_version": 1, "next_id": 100, "entries": [], "rejected": []}'
    )
    rc = fi.main([
        "--task-id", "50",
        "--response", str(resp_path),
        "--output-dir", str(tmp_path),
        "--branch", "cv-coder-impl-50",
    ])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "failed"


def test_finalize_pytest_gate_red_marks_failed(tmp_path):
    """Coder says success but real pytest fails -> failed."""
    resp_path = _seed(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py"],
        "tests_added": ["test_x"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "x",
        "notes": "",
    })
    with patch.object(fi, "_run_pytest_gate", return_value=(False, "FAILED tests/unit/test_old.py")), \
         patch.object(fi, "_assert_scope_clean", return_value=True), \
         patch.object(fi, "_git_capture_head_sha", return_value="abc"):
        rc = fi.main([
            "--task-id", "50",
            "--response", str(resp_path),
            "--output-dir", str(tmp_path),
            "--branch", "cv-coder-impl-50",
        ])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "failed"
    assert "FAILED tests/unit/test_old.py" in e["implementation_notes"]


def test_finalize_scope_violation_marks_failed(tmp_path):
    """Coder modified a forbidden file -> failed."""
    resp_path = _seed(tmp_path, {
        "status": "success",
        "files_modified": ["parser/uslm_parser.py", "settings.json"],
        "tests_added": ["test_x"],
        "test_results": {"full_suite_pass": True, "pytest_summary": "ok"},
        "diff_summary": "x", "notes": "",
    })
    with patch.object(fi, "_run_pytest_gate", return_value=(True, "ok")), \
         patch.object(fi, "_git_capture_head_sha", return_value="abc"):
        # _assert_scope_clean uses files_modified from the response
        rc = fi.main([
            "--task-id", "50",
            "--response", str(resp_path),
            "--output-dir", str(tmp_path),
            "--branch", "cv-coder-impl-50",
        ])
    assert rc == 1
    active = json.loads((tmp_path / "active_corrections.json").read_text())
    e = active["entries"][0]
    assert e["implementation_status"] == "failed"
    assert "settings.json" in e["implementation_notes"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_finalize_implementation.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `finalize_implementation.py`**

Create `skills/cv-coder/finalize_implementation.py`:

```python
"""Post-coder finalize helper.

Runs after the cv-coder subagent returns. Parses its JSON response, runs a
final pytest gate, verifies the diff only touched allowed paths, captures
the feature-branch HEAD SHA, and updates the registry entry's
implementation_status to 'implemented' or 'failed'.

Exit code 0 on success-with-implemented-status; 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Files the coder is allowed to touch (prefixes).
_ALLOWED_PREFIXES = ("parser/", "pipeline/", "tests/")
# Files explicitly forbidden even if they appear under an allowed prefix.
_FORBIDDEN_FILES = (
    "pipeline/corrections_registry.py",
)

logger = logging.getLogger("cv-coder.finalize")


def _load_response(path: Path) -> dict | None:
    """Tolerant JSON extraction from the coder's response file."""
    if not path.exists():
        return None
    raw = path.read_text().strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try fenced code block
    m = re.search(r"```(?:json)?\s*(\{.+?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # First balanced { ... }
    depth = 0
    start = raw.find("{")
    if start < 0:
        return None
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _run_pytest_gate(repo_root: Path) -> tuple[bool, str]:
    """Run `pytest tests/ -x`; return (passed, summary_or_error)."""
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-x", "--tb=short"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=600,
    )
    summary = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, summary[-2000:]  # last 2000 chars


def _assert_scope_clean(files_modified: list[str]) -> tuple[bool, str | None]:
    """All files must be under an allowed prefix and not in the forbidden list."""
    for f in files_modified:
        if f in _FORBIDDEN_FILES:
            return False, f"forbidden file modified: {f}"
        if not any(f.startswith(p) for p in _ALLOWED_PREFIXES):
            return False, f"out-of-scope file modified: {f}"
    return True, None


def _git_capture_head_sha(branch: str, repo_root: Path) -> str | None:
    """Capture the HEAD SHA of the given branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", branch],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _update_entry_status(
    output_dir: Path,
    entry_id: int,
    new_status: str,
    *,
    commit_sha: str | None = None,
    notes: str | None = None,
) -> None:
    """Atomically update one entry's implementation_status in active_corrections.json."""
    path = output_dir / "active_corrections.json"
    data = json.loads(path.read_text())
    found = False
    for e in data.get("entries", []):
        if e["id"] == entry_id:
            e["implementation_status"] = new_status
            if commit_sha is not None:
                e["implementation_commit_sha"] = commit_sha
            if notes is not None:
                e["implementation_notes"] = notes
            found = True
            break
    if not found:
        logger.error("Entry #%d not found in active_corrections.json", entry_id)
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--branch", type=str, required=True)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    resp = _load_response(args.response)
    if resp is None:
        _update_entry_status(
            args.output_dir, args.task_id, "failed",
            notes=f"coder response could not be parsed from {args.response}",
        )
        logger.error("Unparseable coder response at %s", args.response)
        return 1

    status = resp.get("status")
    if status != "success":
        notes = f"coder returned status={status!r}; notes: {resp.get('notes', '')}"
        _update_entry_status(args.output_dir, args.task_id, "failed", notes=notes)
        logger.error("Coder did not succeed: %s", notes)
        return 1

    files_modified = resp.get("files_modified", [])
    scope_ok, scope_err = _assert_scope_clean(files_modified)
    if not scope_ok:
        _update_entry_status(
            args.output_dir, args.task_id, "failed",
            notes=f"scope violation: {scope_err}",
        )
        logger.error("Scope violation: %s", scope_err)
        return 1

    if not resp.get("tests_added"):
        _update_entry_status(
            args.output_dir, args.task_id, "failed",
            notes="no new tests reported by the coder (TDD gate)",
        )
        logger.error("Coder reported no tests added")
        return 1

    pytest_ok, pytest_summary = _run_pytest_gate(_REPO_ROOT)
    if not pytest_ok:
        _update_entry_status(
            args.output_dir, args.task_id, "failed",
            notes=f"pytest gate red: {pytest_summary}",
        )
        logger.error("Pytest gate failed")
        return 1

    sha = _git_capture_head_sha(args.branch, _REPO_ROOT)
    _update_entry_status(
        args.output_dir, args.task_id, "implemented",
        commit_sha=sha,
        notes=f"implemented on branch {args.branch}; {resp.get('diff_summary', '')}",
    )
    logger.info("Correction #%d marked implemented (sha=%s).", args.task_id, sha)
    print(f"\n✓ Entry #{args.task_id} implementation_status=implemented")
    print(f"  Branch: {args.branch}")
    print(f"  Commit: {sha}")
    print(f"  Pytest: {pytest_summary.splitlines()[-1] if pytest_summary else 'green'}")
    print(f"\n  Next: review the diff and merge to main when ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_finalize_implementation.py -v`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -x`
Expected: PASS — full count is now 122.

- [ ] **Step 6: Commit**

```bash
git add skills/cv-coder/finalize_implementation.py tests/unit/test_finalize_implementation.py
git commit -m "Add cv-coder finalize_implementation.py + tests

Post-coder helper: parses the subagent's JSON, runs the final pytest gate,
verifies all modified files are under parser/, pipeline/, or tests/ (and
none are in the explicit forbidden list), captures the feature-branch
HEAD SHA, and writes implementation_status to the active registry entry.
Exit 0 on implemented; exit 1 on any gate failure (with notes recording
the specific blocker)."
```

---

## Task 8: Re-publish CLI — `re_publish_after_fix.py`

**Files:**
- Create: `re_publish_after_fix.py`
- Test: `tests/unit/test_re_publish_after_fix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_re_publish_after_fix.py`:

```python
"""Tests for re_publish_after_fix.py — affected-volume identification."""
import json
import importlib.util
import sys
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/re_publish_after_fix.py")
_spec = importlib.util.spec_from_file_location("repub", _MODULE)
rp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rp
_spec.loader.exec_module(rp)


def test_identify_affected_volumes_for_null_section_pattern(tmp_path):
    """An entry whose trigger.pattern mentions 'SectionNumber is null' should
    match volumes whose validation report contains 'Duplicate UniqueKey rows'."""
    # Seed minimal validation reports
    (tmp_path / "scratch").mkdir()
    for vol, warnings in [
        ("75", []),  # clean
        ("84", ["Duplicate UniqueKey rows: 12"]),
        ("88", ["Duplicate UniqueKey rows: 471"]),
        ("91", ["Distinct LawIdentifier count 350 != 351"]),
    ]:
        (tmp_path / "scratch" / f"validation_report_{vol}.json").write_text(
            json.dumps({"warnings": warnings})
        )
    entry = {
        "id": 2, "type": "other",
        "trigger": {"pattern": "SectionNumber is null collapse to identical UniqueKey"},
        "discovered_in_vol": 75,
        "correction": {"affected_examples": []},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=tmp_path / "scratch")
    assert sorted(vols) == [84, 88]


def test_identify_affected_volumes_for_dropped_plaw_pattern(tmp_path):
    """An entry whose trigger.pattern mentions <main> containing <part> / no <section>
    should match volumes whose validation report contains the LawIdentifier-mismatch warning."""
    (tmp_path / "scratch").mkdir()
    for vol, warnings in [
        ("76", ["Distinct LawIdentifier count 484 != public pLaw count 485 (diff -1)"]),
        ("78", ["Duplicate UniqueKey rows: 22"]),  # this one shouldn't match
        ("114", ["Distinct LawIdentifier count 409 != public pLaw count 410 (diff -1)"]),
    ]:
        (tmp_path / "scratch" / f"validation_report_{vol}.json").write_text(
            json.dumps({"warnings": warnings})
        )
    entry = {
        "id": 3, "type": "other",
        "trigger": {"pattern": "<main> contains <part> elements no top-level <section>"},
        "discovered_in_vol": 75,
        "correction": {"affected_examples": []},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=tmp_path / "scratch")
    assert sorted(vols) == [76, 114]


def test_identify_handles_missing_scratch_dir(tmp_path):
    """If scratch is empty, only the discovered_in_vol is returned."""
    (tmp_path / "scratch").mkdir()
    entry = {
        "id": 5, "type": "other",
        "trigger": {"pattern": "anything"},
        "discovered_in_vol": 78,
        "correction": {"affected_examples": []},
    }
    vols = rp._identify_affected_volumes(entry, scratch_dir=tmp_path / "scratch")
    assert vols == [78]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_re_publish_after_fix.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `re_publish_after_fix.py`**

Create `re_publish_after_fix.py`:

```python
"""CLI: re-publish volumes affected by a freshly-implemented correction.

After the cv-coder merges a fix to main, the volumes whose validation
reports surfaced that bug pattern should be re-processed so their
published Excels reflect the corrected extractor output. This script
identifies the affected volumes from the validation-report warnings,
prompts for confirmation, then loops `run_pipeline.py --volumes N
--stop-before-publish` + `apply_corrections_and_publish.py --volume N`
for each.

Usage::

    python re_publish_after_fix.py --entry 2
    python re_publish_after_fix.py --entry 2 --yes        # skip prompt
    python re_publish_after_fix.py --entry 2 --dry-run    # print plan
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

# Coarse mapping from trigger.pattern keywords to the validation-warning
# signature that indicates the same bug surfaced in another volume.
_PATTERN_TO_WARNING_KEYWORDS = [
    # Null-SectionNumber family (#2, #14, #15, #16)
    (["SectionNumber is null", "outer <section> wraps", "unnumbered opening"],
     ["Duplicate UniqueKey rows"]),
    # No-top-level-<section> family (#3, #7, #11, #17)
    (["no top-level <section>", "<main> contains <part>", "<main> contains <title>",
      "<main> contains <chapter>", "<main> contains <quotedContent>",
      "zero top-level <section>"],
     ["Distinct LawIdentifier count"]),
    # Sibling appropriations (#5)
    (["sibling <appropriations>"],
     ["Duplicate UniqueKey rows"]),
    # Sibling <level> (#13)
    (["sibling <level>"],
     ["Duplicate UniqueKey rows"]),
]


def _identify_affected_volumes(entry: dict, *, scratch_dir: Path) -> list[int]:
    """Walk validation_report_*.json files, return vols whose warnings match
    the entry's trigger.pattern via the keyword map."""
    pattern = (entry.get("trigger", {}).get("pattern") or "").lower()
    warning_needles: list[str] = []
    for pattern_keys, warning_keys in _PATTERN_TO_WARNING_KEYWORDS:
        if any(pk.lower() in pattern for pk in pattern_keys):
            warning_needles.extend(wk.lower() for wk in warning_keys)
    matched: set[int] = set()
    # Always include the discovery vol
    if entry.get("discovered_in_vol"):
        try:
            matched.add(int(entry["discovered_in_vol"]))
        except (TypeError, ValueError):
            pass
    if not warning_needles:
        return sorted(matched)
    for report in scratch_dir.glob("validation_report_*.json"):
        try:
            vol = int(report.stem.split("_")[-1])
        except ValueError:
            continue
        try:
            d = json.loads(report.read_text())
        except json.JSONDecodeError:
            continue
        warnings = d.get("warnings", []) or d.get("validation_warnings", [])
        text = " ".join(warnings).lower()
        if any(needle in text for needle in warning_needles):
            matched.add(vol)
    return sorted(matched)


def _load_entry(output_dir: Path, entry_id: int) -> dict | None:
    active = json.loads((output_dir / "active_corrections.json").read_text())
    for e in active.get("entries", []):
        if e["id"] == entry_id:
            return e
    return None


def _republish_volume(vol: int, output_dir: Path, source_xml_dir: Path) -> bool:
    """Delete vol's Excel + manifest entry, then re-run + re-publish.

    Returns True on success."""
    log = logging.getLogger("re-publish")

    # 1. Delete existing volume directory
    vol_dir = output_dir / f"Volume-{vol}"
    if vol_dir.exists():
        log.info("Removing %s", vol_dir)
        for f in vol_dir.iterdir():
            f.unlink()
        vol_dir.rmdir()

    # 2. Clear manifest entry's status so it's not skipped
    manifest_path = output_dir / "run_manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        entry = m.get("volumes", {}).get(str(vol))
        if entry:
            for k in ("output_path", "output_sha256", "sme_path", "status", "last_run"):
                entry.pop(k, None)
        tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        tmp.write_text(json.dumps(m, indent=2, sort_keys=True))
        tmp.replace(manifest_path)

    # 3. Re-run + re-publish
    rc = subprocess.call([
        "python", "run_pipeline.py",
        "--volumes", str(vol),
        "--stop-before-publish",
        "--source-xml-dir", str(source_xml_dir),
        "--output-dir", str(output_dir),
    ], cwd=str(_HERE))
    if rc != 0:
        log.error("run_pipeline failed for vol %d (rc=%d)", vol, rc)
        return False

    rc = subprocess.call([
        "python", "apply_corrections_and_publish.py",
        "--volume", str(vol),
        "--include-pending",
        "--output-dir", str(output_dir),
    ], cwd=str(_HERE))
    if rc != 0:
        log.error("apply_corrections_and_publish failed for vol %d (rc=%d)", vol, rc)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entry", type=int, required=True)
    parser.add_argument("--output-dir", default=str(_HERE / "processed_output"))
    parser.add_argument("--source-xml-dir",
                        default="/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan; don't execute")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")
    log = logging.getLogger("re-publish")

    output_dir = Path(args.output_dir).resolve()
    entry = _load_entry(output_dir, args.entry)
    if not entry:
        log.error("Entry #%d not found in active_corrections.json", args.entry)
        return 2
    if entry.get("implementation_status") != "implemented":
        log.error("Entry #%d has implementation_status=%r; expected 'implemented'.",
                  args.entry, entry.get("implementation_status"))
        return 2

    vols = _identify_affected_volumes(entry, scratch_dir=output_dir / "scratch")
    if not vols:
        log.info("No affected volumes identified for entry #%d.", args.entry)
        return 0

    print(f"\nEntry #{args.entry}: '{entry.get('correction', {}).get('description', '')[:80]}...'")
    print(f"  Affected volumes: {vols}")
    if args.dry_run:
        print("  (dry-run; nothing re-published)")
        return 0
    if not args.yes:
        answer = input(f"\nRe-publish these {len(vols)} volumes? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return 1

    failed: list[int] = []
    for v in vols:
        log.info("Re-publishing volume %d...", v)
        ok = _republish_volume(v, output_dir, Path(args.source_xml_dir))
        if not ok:
            failed.append(v)

    if failed:
        log.error("Failed to re-publish: %s", failed)
        return 1
    log.info("All %d volumes re-published.", len(vols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_re_publish_after_fix.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -x`
Expected: PASS — full count is now 125.

- [ ] **Step 6: Commit**

```bash
git add re_publish_after_fix.py tests/unit/test_re_publish_after_fix.py
git commit -m "Add re_publish_after_fix.py CLI

Given an implemented correction id, identifies affected volumes by
matching the entry's trigger.pattern against validation_report_*.json
warnings via a keyword map (null-SectionNumber family -> 'Duplicate
UniqueKey rows', no-top-level-section family -> 'Distinct LawIdentifier
count'). Prompts for confirmation, then loops: delete Volume-N excel,
clear manifest entry, re-run pipeline --stop-before-publish, run
apply_corrections_and_publish. Supports --dry-run and --yes."
```

---

## Task 9: End-to-end smoke test — drive correction #5 through the full workflow

**Files:**
- No new code. Just exercise the wiring with a real end-to-end run.

This task is intentionally a manual / observational smoke test rather than
an automated one — the cv-coder subagent's output is non-deterministic and
the full workflow involves an interactive Claude Code session.

**Pick correction #5** (sibling-appropriations) because it has the narrowest
scope (only vol 78), small description, and clear test fixture.

- [ ] **Step 1: Verify pre-state**

```bash
source /home/G39248410/citizen_voice/venv/bin/activate
cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline
python -c "
import json
d = json.load(open('processed_output/active_corrections.json'))
e = next(e for e in d['entries'] if e['id'] == 5)
print(f'#5 status={e[\"status\"]}  impl_status={e[\"implementation_status\"]}')
"
```

Expected: `#5 status=approved  impl_status=pending`

- [ ] **Step 2: Queue the coder task**

```bash
python approve_corrections.py approve 5
```

At the `Auto-implement now via the cv-coder agent? [y/N]:` prompt, type
`y`. Expected: task queued at `scratch/coder_task_5.json`; entry status
flips to `in_progress`.

Verify:
```bash
ls processed_output/scratch/coder_task_5.json
python -c "
import json
d = json.load(open('processed_output/active_corrections.json'))
e = next(e for e in d['entries'] if e['id'] == 5)
print(f'#5 impl_status={e[\"implementation_status\"]}  attempted_at={e[\"implementation_attempted_at\"]}')
"
```

Expected: file exists; impl_status=in_progress; attempted_at is set.

- [ ] **Step 3: In a Claude Code session, invoke the cv-coder skill**

Open a Claude Code session in the repo. Say:

> implement correction 5 with cv-coder

Claude will follow `skills/cv-coder/SKILL.md`:
1. Check out feature branch `cv-coder-impl-5`
2. Dispatch the Opus subagent with the system prompt + task body
3. Save response to `scratch/coder_response_5.json`
4. Run `finalize_implementation.py`
5. Show you the diff
6. Wait for merge confirmation

- [ ] **Step 4: Inspect the diff before merging**

```bash
git diff main..cv-coder-impl-5
```

Read it carefully. Check:
- Only `parser/uslm_parser.py` (+ test files) modified
- At least one new test under `tests/unit/`
- The test uses a minimal XML fixture, not the real vol 78 XML
- The fix is minimal — no refactoring of unrelated code
- The test is genuinely new (not just a renamed existing test)

- [ ] **Step 5: Run the test suite manually**

```bash
python -m pytest tests/ -x -v
```

Expected: all tests pass.

- [ ] **Step 6: Merge if happy**

If the diff looks good, in the Claude Code session confirm the merge.
Otherwise:

```bash
git branch -D cv-coder-impl-5
```

And manually edit `active_corrections.json` to flip `#5`'s impl_status
back to `pending` (or `failed` with a note).

- [ ] **Step 7: Re-publish vol 78**

```bash
python re_publish_after_fix.py --entry 5
```

Confirm at the prompt. Expected: vol 78 republishes with 0 UniqueKey
duplicates in its validation report (vs. 22 before).

- [ ] **Step 8: Commit any post-smoke registry updates**

```bash
git add processed_output/active_corrections.json processed_output/run_manifest.json \
        processed_output/Volume-78/
git commit -m "Smoke test cv-coder on correction #5 + re-publish vol 78

Correction #5 (sibling <appropriations> duplicate headings) implemented
by cv-coder on branch cv-coder-impl-5, merged via the human-review gate.
Vol 78 re-published: UniqueKey duplicate count went from 22 to 0."
```

---

## Task 10: Documentation — update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a cv-coder section**

Open `README.md`. After the existing "Quick start" section, insert this
new section:

```markdown
## cv-coder workflow (autonomous code fixes)

`type: "other"` corrections describe extractor-code changes that can't be
expressed as a runtime trigger+replacement rule. The **cv-coder** skill
takes an approved `other` correction and implements it in `parser/`,
gated on a TDD discipline (failing test first) + a full `pytest` gate +
human review of the diff.

### End-to-end workflow

```bash
# 1. After the cv-correct subagent surfaced an `other` proposal, approve it.
python approve_corrections.py approve <id>
# At the prompt "Auto-implement now via the cv-coder agent? [y/N]: ", type `y`.
# A coder task is queued at processed_output/scratch/coder_task_<id>.json.

# 2. In a Claude Code session in the repo, invoke the cv-coder skill:
#    "implement correction <id> with cv-coder"
# Claude:
#   - creates a feature branch cv-coder-impl-<id>
#   - dispatches an Opus subagent (with ultrathink) to write a failing test,
#     implement the fix, run the full suite
#   - runs finalize_implementation.py as a gate (pytest green + scope clean
#     + new test added)
#   - shows you the diff and asks for merge confirmation

# 3. After merge, re-publish the affected volumes:
python re_publish_after_fix.py --entry <id>
```

### What gets checked

- The subagent's reported `status` must be `"success"`
- The full `pytest tests/ -x` must pass
- Only files under `parser/`, `pipeline/`, `tests/` may be modified
- At least one new test must be added
- Branch-per-fix isolation — main is untouched on failure

### Failure handling

If the coder fails any gate, the entry's `implementation_status` becomes
`failed` with notes in the registry. The branch is preserved so you can
inspect what the coder tried. Retry by running `approve_corrections.py
approve <id>` again (the entry's status is already approved; the prompt
will re-queue a task).
```

- [ ] **Step 2: Verify the README change**

```bash
grep -c "cv-coder workflow" README.md
```

Expected: `1`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "README: document the cv-coder workflow for type=other corrections

End-to-end: approve_corrections.py approve <id> -> prompt for auto-implement
-> Claude Code session runs the cv-coder skill (Opus + ultrathink + TDD
discipline + scope guard) -> human-reviews diff -> merge -> re-publish
affected volumes via re_publish_after_fix.py --entry <id>."
```

---

## Task 11: Push everything

- [ ] **Step 1: Verify all commits**

```bash
git log --oneline ^origin/main HEAD
```

Expected: 9-10 new commits (one per task above, plus the smoke-test commit).

- [ ] **Step 2: Run full suite one more time**

```bash
python -m pytest tests/ -x
```

Expected: PASS — 125+ tests.

- [ ] **Step 3: Push**

```bash
git push origin main
```

If push is blocked by the auto-mode classifier, run from a terminal
directly. If it succeeds, the plan is fully landed on GitHub.

---

## Self-review checklist (the plan-author's checklist, not a task)

Before declaring this plan done:

**1. Spec coverage** — Each piece of the user request should map to a task:
   - ✅ "Autonomous coding agent that writes/modifies code in parser scripts" → Tasks 5-7 (skill scaffold + system_prompt + finalize helper)
   - ✅ "Apply the approved fixes for 'other' issues" → Tasks 5-7 + Task 9 (smoke test)
   - ✅ "Automatically invoked when user approves corrections" → Task 4 (approve_corrections.py prompt + queue) + Task 5 (skill picks up the queued task)
   - ✅ "Confirms agent to fix those issues" → Task 4 (the y/N prompt)
   - ✅ Manifest honesty (related concern from prior conversation) → Task 3
   - ✅ Re-publish affected volumes after fix → Task 8

**2. Placeholder scan** — No `TBD`, `TODO`, `implement later`, or "write tests
   for the above" without actual test code. Every step has the actual content.

**3. Type consistency** — `implementation_status` (snake_case, string)
   consistently used everywhere; `CorrectionEntry` field names match
   between `from_dict`, `to_dict`, and the helper that mutates them;
   `_filter_active_ids_for_manifest`, `_queue_coder_task`,
   `_identify_affected_volumes`, `_run_pytest_gate`, `_assert_scope_clean`,
   `_git_capture_head_sha`, `_update_entry_status`, `_load_response` —
   all names referenced consistently in tests and implementations.

---

## Open design questions (for the operator to decide before execution)

The plan above assumes the following defaults. If you want different
behavior, flag at execution time:

1. **Branch-per-fix vs. direct-to-main**: plan assumes a feature branch
   (`cv-coder-impl-<id>`) per fix, with human merge confirm. Alternative:
   direct commit to main on coder success + pytest green. Trade-off is
   review granularity vs. friction.

2. **Auto-publish after merge**: plan keeps `re_publish_after_fix.py` as
   a separate manual step. Alternative: have the cv-coder skill chain
   directly into re-publishing after merge confirmation. Trade-off is
   convenience vs. seeing the diff and re-publish stages as separate
   review gates.

3. **Sequential vs. batch coder runs**: plan assumes one coder run per
   approved entry, sequential. The 10 currently-pending `other` entries
   form 4 logical groups (#2/#14/#15/#16 are refinements of null-num;
   #3/#7/#11/#17 are container-walker extensions; #5 and #13 are
   one-offs). Alternative: a batch mode where one coder run tackles all
   refinements of the same root cause as a single diff. Trade-off is
   bigger but more cohesive diffs vs. smaller / easier-to-review diffs.

4. **Worktree isolation**: plan uses ordinary feature branches in the
   primary working tree. Alternative: `git worktree add` for full
   filesystem isolation per coder run, so multiple coder runs can
   proceed in parallel. Requires the `superpowers:using-git-worktrees`
   skill on the orchestrator side.

The defaults are the safer choice. Tell me which you want to flip before
starting execution.
