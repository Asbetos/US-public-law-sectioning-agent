---
name: cv-coder
description: |
  Pick up a queued cv-coder task (processed_output/scratch/coder_task_<id>.json) and
  dispatch an Opus subagent to implement the approved type=other correction(s) by editing
  parser code, writing failing regression tests first, then running the full pytest suite.
  Use when the operator says "implement correction <id> with cv-coder", "/cv-coder
  implement <id>", "run the coder agent on task <id>", or when they confirm
  auto-implementation during approve_corrections.py.
---

# cv-coder Skill

This skill is the Claude Code orchestrator for implementing approved type='other'
extractor-code corrections — invoked after approve_corrections.py queues a task.

## Trigger

After approve_corrections.py approve <id> with confirmation, the operator invokes
this skill in Claude Code by saying:

  "implement correction N with cv-coder"

If approval was done in a terminal (no Claude session), the task persists on disk
until the operator opens Claude Code and invokes the skill.

## Per-task workflow (NO feature branch — direct to main)

### Step 1 — Load the queued task

Read `processed_output/scratch/coder_task_<N>.json`. If missing, abort and tell the
operator to run `python approve_corrections.py approve <N>` first.

Extract: `task_id`, `entry_ids`, `family`, `registry_entries`, `context_files`,
`constraints`.

### Step 2 — Verify clean working tree

Before dispatching the coder, verify the working tree is clean:

```bash
git status --porcelain
```

If anything is uncommitted, abort with a message: "Working tree must be clean before
cv-coder runs. Commit or stash your changes first."

### Step 3 — Dispatch the coder subagent

Read `skills/cv-coder/system_prompt.md`. Substitute the task placeholders. Then
dispatch the Agent tool:

```
subagent_type: general-purpose
model: opus
description: "cv-coder: implement correction(s) #<task_id>"
prompt: <filled system_prompt.md content>
```

**Always pass model: opus.** The cv-coder's judgement task requires the strongest
available model regardless of what the parent session uses.

### Step 4 — Save the subagent's response

Write the subagent's full text response to `processed_output/scratch/coder_response_<N>.json`
for audit. Use the tolerant JSON extractor (look for the first balanced {} block if
the response wraps the JSON in markdown fences).

### Step 5 — Run the finalize helper

```bash
python skills/cv-coder/finalize_implementation.py \
    --task-id <N> \
    --response processed_output/scratch/coder_response_<N>.json \
    --output-dir processed_output
```

The helper:
- Parses the coder JSON
- Verifies status == "success"
- Verifies pytest tests/ -x is green (working-tree, no commit yet)
- Verifies files_modified are all under parser/, pipeline/, or tests/
- Verifies at least one new test was added
- On success: `git add` the modified files, `git commit` directly to main, capture
  the commit SHA, and update ALL entry_ids' implementation_status to "implemented"
  with the SHA in implementation_commit_sha
- On any gate failure: revert the working tree (`git checkout -- <modified files>`)
  and mark all entry_ids implementation_status="failed" with notes

**Branch-aware (old + new volumes):** the task's `target_repo` field selects
where edits land — `pipeline` (default; structural corrections in
`parser/uslm_parser.py`, shared by legacy ≤63 and modern >63 volumes) or
`legacy-law-identity` (legacy law-identity corrections in the resolver package,
e.g. sidenote-regex changes). The finalize helper runs *that repo's* pytest,
enforces scope against *that repo's* allowed prefixes, commits in *that repo*,
and records the SHA. `approve_corrections.py` sets `target_repo` when it queues
the task (see `_target_repo_for`).

### Step 6 — Auto-chain re-publish

If finalize exited 0 (success), it ALREADY invoked re_publish_after_fix.py
--entry <primary_task_id> --yes internally (no second confirmation prompt). The
affected volumes have been re-published.

Print a summary to the operator: which volumes were re-published, the new
output paths, and the commit SHA. No further action required.

### Step 7 — Surface failure clearly

If finalize exited non-zero:

```
✗ cv-coder failed on task #<N>
   Reason: <from registry entry's implementation_notes>
   Coder response: processed_output/scratch/coder_response_<N>.json
   Working tree has been reverted; main is unchanged.
   Entry(ies) #<entry_ids> are now marked implementation_status="failed".
   To retry: re-run approve_corrections.py approve <id> (entry is still 'approved'
   from the registry's perspective) or implement manually and use
   `mark-implemented <id>` (future CLI — not yet built).
```

## Failure modes

| Failure | Behavior |
|---|---|
| Task file missing | Abort; tell operator to run approve_corrections.py first |
| Working tree dirty before dispatch | Abort; tell operator to commit/stash |
| Subagent times out / errors | finalize handles — mark "failed", revert working tree |
| Subagent JSON unparseable | finalize handles — mark "failed", revert working tree |
| Pytest red on subagent's changes | finalize handles — mark "failed", revert working tree |
| Subagent modified disallowed files | finalize handles — mark "failed", revert |
| Subagent returned status="needs_human" | finalize handles — mark "failed", surface notes |
| re_publish_after_fix.py fails mid-volume | Commit landed but some volumes have stale Excel; operator runs re_publish manually |

## Hard prohibitions

- Never dispatch the coder without model: opus
- Never create a feature branch (operator decision: direct-to-main)
- Never bypass the pytest gate in finalize_implementation.py
- Never skip the auto-chain re-publish (operator decision: auto-chain after success)
- Never commit from inside the cv-coder skill orchestration — finalize handles all commits
