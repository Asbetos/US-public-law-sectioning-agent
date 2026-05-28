"""Post-coder finalize: pytest gate -> commit to main -> auto-chain re-publish.

Reads the coder's response JSON, enforces a gate suite (status, scope, new tests,
pytest), commits the working-tree changes on full pass, otherwise reverts.
Updates implementation_status across active + pending correction registries for
every entry covered by the task. On success, auto-chains the re-publish helper.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent

_ALLOWED_PREFIXES = ("parser/", "pipeline/", "tests/")
_FORBIDDEN_FILES = (
    "pipeline/corrections_registry.py",
    "apply_corrections_and_publish.py",
    "approve_corrections.py",
)

logger = logging.getLogger("cv-coder.finalize")


def _load_response(path: Path) -> dict | None:
    """Tolerant JSON extraction (handles markdown fences + bare blocks)."""
    if not path.exists():
        return None
    raw = path.read_text().strip()
    if not raw:
        return None
    # try direct
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # fenced
    m = re.search(r"```(?:json)?\s*(\{.+?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # balanced
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
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


def _assert_scope_clean(files_modified):
    for f in files_modified:
        if f in _FORBIDDEN_FILES:
            return False, f"forbidden file modified: {f}"
        if not any(f.startswith(p) for p in _ALLOWED_PREFIXES):
            return False, f"out-of-scope file: {f}"
    return True, None


def _run_pytest_gate(repo_root):
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-x", "--tb=short"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=600,
    )
    summary = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, summary[-2000:]


def _git_commit_and_capture_sha(files_modified, message, repo_root):
    """Stage files, commit, return HEAD SHA. Returns None on failure."""
    add = subprocess.run(
        ["git", "add", *files_modified],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        return None
    commit = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        return None
    sha_p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return sha_p.stdout.strip() if sha_p.returncode == 0 else None


def _git_revert_files(files_modified, repo_root=None):
    if repo_root is None:
        repo_root = _REPO_ROOT
    for f in files_modified:
        subprocess.run(
            ["git", "checkout", "--", f],
            cwd=str(repo_root),
            capture_output=True,
        )


def _invoke_republish(task_id, output_dir, repo_root=None):
    if repo_root is None:
        repo_root = _REPO_ROOT
    rc = subprocess.call(
        [
            "python",
            "re_publish_after_fix.py",
            "--entry",
            str(task_id),
            "--yes",
            "--output-dir",
            str(output_dir),
        ],
        cwd=str(repo_root),
    )
    return rc == 0


def _update_entries_status(output_dir, entry_ids, new_status, *, commit_sha=None, notes=None):
    """Update implementation_status in BOTH active_corrections.json and pending_corrections.json."""
    entry_id_set = set(entry_ids)
    for filename in ("active_corrections.json", "pending_corrections.json"):
        path = output_dir / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("Could not parse %s; skipping status update", path)
            continue
        modified = False
        for bucket_key in ("entries", "rejected"):
            for entry in data.get(bucket_key, []) or []:
                if entry.get("id") in entry_id_set:
                    entry["implementation_status"] = new_status
                    if commit_sha is not None:
                        entry["implementation_commit_sha"] = commit_sha
                    if notes is not None:
                        entry["implementation_notes"] = notes
                    modified = True
        if modified:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            tmp.replace(path)


def _read_task_json(output_dir, task_id):
    """Load coder_task_<task_id>.json to find entry_ids."""
    task_path = output_dir / "scratch" / f"coder_task_{task_id}.json"
    if not task_path.exists():
        return None
    try:
        return json.loads(task_path.read_text())
    except json.JSONDecodeError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    # Load task JSON to get entry_ids list
    task = _read_task_json(args.output_dir, args.task_id)
    entry_ids = task.get("entry_ids", [args.task_id]) if task else [args.task_id]

    # Load coder response
    resp = _load_response(args.response)
    if resp is None:
        _update_entries_status(
            args.output_dir,
            entry_ids,
            "failed",
            notes=f"coder response unparseable: {args.response}",
        )
        logger.error("Unparseable coder response")
        return 1

    # Gate 1: coder status
    if resp.get("status") != "success":
        notes = f"coder returned status={resp.get('status')!r}; notes: {resp.get('notes', '')}"
        _update_entries_status(args.output_dir, entry_ids, "failed", notes=notes)
        _git_revert_files(resp.get("files_modified", []))
        logger.error("Coder did not succeed: %s", notes)
        return 1

    files_modified = resp.get("files_modified", []) or []

    # Gate 2: scope
    scope_ok, scope_err = _assert_scope_clean(files_modified)
    if not scope_ok:
        _update_entries_status(args.output_dir, entry_ids, "failed", notes=f"scope: {scope_err}")
        _git_revert_files(files_modified)
        logger.error("Scope violation: %s", scope_err)
        return 1

    # Gate 3: at least one new test
    if not resp.get("tests_added"):
        _update_entries_status(
            args.output_dir,
            entry_ids,
            "failed",
            notes="no new tests reported (TDD gate)",
        )
        _git_revert_files(files_modified)
        logger.error("No new tests")
        return 1

    # Gate 4: pytest on working tree
    pytest_ok, pytest_summary = _run_pytest_gate(_REPO_ROOT)
    if not pytest_ok:
        _update_entries_status(
            args.output_dir,
            entry_ids,
            "failed",
            notes=f"pytest red: {pytest_summary}",
        )
        _git_revert_files(files_modified)
        logger.error("Pytest gate failed")
        return 1

    # All gates passed: commit
    commit_msg = (
        f"cv-coder: implement correction(s) #{','.join(str(i) for i in entry_ids)}\n\n"
        f"{resp.get('diff_summary', '')}"
    )
    sha = _git_commit_and_capture_sha(files_modified, commit_msg, _REPO_ROOT)
    if sha is None:
        _update_entries_status(args.output_dir, entry_ids, "failed", notes="git commit failed")
        _git_revert_files(files_modified)
        logger.error("Commit failed")
        return 1

    # Mark implemented
    _update_entries_status(
        args.output_dir,
        entry_ids,
        "implemented",
        commit_sha=sha,
        notes=resp.get("diff_summary", ""),
    )

    # Auto-chain re-publish (failure here is a warning, not a hard failure)
    republish_ok = _invoke_republish(args.task_id, args.output_dir)
    if not republish_ok:
        logger.warning(
            "re_publish_after_fix failed for entry #%d; commit %s already landed. "
            "Re-run manually: python re_publish_after_fix.py --entry %d --yes",
            args.task_id,
            sha,
            args.task_id,
        )

    print(f"OK Entry(ies) #{entry_ids} implementation_status=implemented")
    print(f"  Commit: {sha}")
    if republish_ok:
        print("  Re-publish: complete")
    else:
        print("  Re-publish: FAILED (warning only - commit landed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
