"""CLI for human review of pending corrections.

Subcommands:
    list [--status pending|approved|rejected]
    show <id>
    approve <id> [--note "..."] [--reviewer NAME]
    reject  <id> --reason "..."  [--reviewer NAME]
    diff   <id>

After ``approve``, the entry is moved into ``active_corrections.json`` and
will be loaded by the next pipeline run (for new first-time volumes).
Already-published volumes are hard-frozen per the PLAN.md decision §15.7 —
this CLI does not modify any existing Excel.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # so `import pipeline.*` works

from pipeline.correction_families import classify, family_members  # noqa: E402
from pipeline.corrections_registry import CorrectionEntry, CorrectionsRegistry  # noqa: E402


DEFAULT_OUTPUT_DIR = _HERE / "processed_output"


def _resolve_output_dir(args) -> Path:
    return Path(args.output_dir).expanduser().resolve()


def _print_entry_summary(e: CorrectionEntry, indent: str = "") -> None:
    """One-line summary used by `list`."""
    if e.type == "law_id":
        trig = f"law_id~{e.trigger.get('law_id_substring', '?')!r} + title~{e.trigger.get('title_substring', '?')[:40]!r}"
        fix = f"→ {e.correction.get('replace_with_law_id', '?')!r}"
    elif e.type == "section_number":
        trig = f"law_id~{e.trigger.get('law_id_substring', '?')!r} + heading~{e.trigger.get('heading_substring', '?')[:40]!r}"
        fix = f"→ SectionNumber={e.correction.get('replace_with_section_number', '?')!r}"
    else:
        trig = json.dumps(e.trigger)[:80]
        fix = json.dumps(e.correction)[:80]
    vol = f"vol{e.discovered_in_vol}" if e.discovered_in_vol is not None else "vol?"
    seen_extra = f" (seen_again={e.seen_again_count})" if e.seen_again_count else ""
    print(f"{indent}#{e.id:>4}  [{e.type:<14}] [{e.status:<8}] {vol}{seen_extra}  {trig}  {fix}")


def _print_entry_detail(e: CorrectionEntry) -> None:
    """Full pretty-print used by `show`."""
    print(f"Entry #{e.id}  ({e.type}, status={e.status})")
    print(f"  proposed_at:        {e.proposed_at}")
    print(f"  discovered_in_vol:  {e.discovered_in_vol}")
    print(f"  agent_version:      {e.agent_version}")
    print(f"  confidence:         {e.confidence}")
    print(f"  seen_again_count:   {e.seen_again_count}")
    print()
    print("  trigger:")
    for line in json.dumps(e.trigger, indent=2).splitlines():
        print(f"    {line}")
    print("  correction:")
    for line in json.dumps(e.correction, indent=2).splitlines():
        print(f"    {line}")
    if e.evidence:
        print("  evidence:")
        for line in json.dumps(e.evidence, indent=2).splitlines():
            print(f"    {line}")
    if e.reviewer or e.review_note or e.reviewed_at:
        print()
        print(f"  reviewer:     {e.reviewer}")
        print(f"  reviewed_at:  {e.reviewed_at}")
        if e.review_note:
            wrapped = textwrap.fill(e.review_note, width=72, subsequent_indent="                ")
            print(f"  review_note:  {wrapped}")
    if e.applied_in_runs:
        print(f"  applied_in_runs ({len(e.applied_in_runs)}):")
        for run in e.applied_in_runs[-5:]:
            print(f"    - {run}")


def _print_diff(e: CorrectionEntry) -> None:
    """Show what promoting this entry would change in the active rule set."""
    print(f"Entry #{e.id}  (type={e.type})")
    print()
    if e.type == "law_id":
        print("Would add to LAW_ID_CORRECTIONS:")
        rule = (
            e.trigger.get("law_id_substring", ""),
            e.trigger.get("title_substring", ""),
            e.correction.get("replace_with_law_id", ""),
        )
        print(f"  {rule!r}")
    elif e.type == "section_number":
        print("Would add to SECTION_NUMBER_CORRECTIONS:")
        rule = (
            e.trigger.get("law_id_substring", ""),
            e.trigger.get("heading_substring", ""),
            e.trigger.get("text_substring"),
            e.correction.get("replace_with_section_number", ""),
        )
        print(f"  {rule!r}")
    else:
        print("Unknown type — no rule mapping defined.")


# ---------- subcommands ----------

def cmd_list(args, reg: CorrectionsRegistry) -> int:
    pending = reg.all_pending_entries()
    rejected = reg.pending.rejected
    active = reg.all_active_entries()

    if args.status in (None, "pending"):
        live_pending = [e for e in pending if e.status == "pending"]
        print(f"== PENDING ({len(live_pending)}) ==")
        for e in live_pending:
            _print_entry_summary(e)
    if args.status in (None, "approved"):
        print(f"\n== ACTIVE / APPROVED ({len(active)}) ==")
        for e in active:
            _print_entry_summary(e)
    if args.status in (None, "rejected"):
        print(f"\n== REJECTED ({len(rejected)}) ==")
        for e in rejected:
            _print_entry_summary(e)
    return 0


def cmd_show(args, reg: CorrectionsRegistry) -> int:
    entry = reg.find_in_pending(args.id)
    if entry is None:
        for e in reg.all_active_entries():
            if e.id == args.id:
                entry = e
                break
    if entry is None:
        for e in reg.pending.rejected:
            if e.id == args.id:
                entry = e
                break
    if entry is None:
        print(f"No entry with id {args.id} found in pending / active / rejected.", file=sys.stderr)
        return 1
    _print_entry_detail(entry)
    return 0


def _queue_coder_task(
    output_dir: Path,
    entry_ids: list[int],
    family: str,
    *,
    registry: CorrectionsRegistry,
    reviewer: str,
) -> Path:
    """Write a coder-task JSON to ``<output_dir>/scratch/coder_task_<primary_id>.json``.

    The primary id is the only id when ``entry_ids`` has length 1, else the
    largest (so batched-family filenames are stable regardless of approval order).
    The task JSON includes the full registry-entry dicts for each id in
    ``entry_ids`` order, so the cv-coder subagent has everything it needs in one
    file.
    """
    entry_ids = sorted(entry_ids)
    primary_id = entry_ids[0] if len(entry_ids) == 1 else max(entry_ids)
    by_id: dict[int, dict] = {}
    for x in registry.all_pending_entries():
        by_id[x.id] = x.to_dict()
    for x in registry.all_active_entries():
        by_id[x.id] = x.to_dict()  # active wins if duplicated
    registry_entries = [by_id[i] for i in entry_ids if i in by_id]

    scratch = output_dir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    task = {
        "task_id": primary_id,
        "entry_ids": entry_ids,
        "family": family,
        "queued_at": datetime.now().isoformat(),
        "approver": reviewer,
        "registry_entries": registry_entries,
        "context_files": [
            "parser/uslm_parser.py",
            "tests/unit/test_uslm_parser.py",
        ],
        "constraints": [
            "Add at least one regression test per family member that fails on the OLD code and passes on the NEW code.",
            "Do not modify pipeline/corrections_registry.py, run_pipeline.py, processed_output/*, settings.json, .gitignore, or CI files.",
            "Do not delete or rename existing tests.",
            "All edits must be confined to parser/, pipeline/, and tests/.",
            "Do NOT git commit — leave changes staged or unstaged. The finalize helper will commit.",
            "Run `pytest tests/ -x` before reporting success.",
        ],
    }
    task_path = scratch / f"coder_task_{primary_id}.json"
    task_path.write_text(json.dumps(task, indent=2))
    return task_path


def _prompt_other_after_approval(
    promoted: CorrectionEntry,
    reg: CorrectionsRegistry,
    output_dir: Path,
    reviewer: str,
) -> None:
    """Post-promotion confirmation prompt for ``type='other'`` entries.

    - If the entry belongs to a known family with at least one *other* pending
      sibling, offer to batch all family members into ONE coder task (default Y).
    - Otherwise (or if the family-batch is declined), offer to auto-implement
      just this single entry (default N).
    Writes a task JSON to ``<output_dir>/scratch/coder_task_<id>.json`` and
    marks all queued entries ``implementation_status='in_progress'``.
    """
    if promoted.type != "other":
        return

    e_dict = promoted.to_dict()
    family = classify(e_dict)

    # Gather all entries from both pending and active sides to look for siblings.
    all_entries = [x.to_dict() for x in reg.all_pending_entries()] + [
        x.to_dict() for x in reg.all_active_entries()
    ]
    # The just-promoted entry now has status='approved' on the pending side
    # (and a copy with implementation_status='pending' on active). For family
    # batching, we want all *pending implementation_status* entries — the
    # just-approved one qualifies because its implementation_status is still
    # 'pending' (mark_in_progress hasn't been called yet).
    groups = family_members(all_entries, pending_only=True)
    raw_family_ids = sorted(set(groups.get(family, [])))
    # Always ensure the just-approved entry is included.
    if promoted.id not in raw_family_ids:
        raw_family_ids = sorted(set(raw_family_ids) | {promoted.id})
    family_ids = raw_family_ids

    if family != "none" and len(family_ids) > 1:
        print(f"\n⚙ Entry #{promoted.id} is type='other' (family: {family})")
        print(
            f"  {len(family_ids)} entries in this family currently have "
            f"implementation_status='pending':"
        )
        print(f"    {', '.join(f'#{i}' for i in family_ids)}")
        answer = input("  Batch all family members into ONE coder task? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            task_path = _queue_coder_task(
                output_dir, family_ids, family, registry=reg, reviewer=reviewer
            )
            reg.mark_in_progress(family_ids)
            primary_id = task_path.stem.split("_")[-1]
            print(f"\n  cv-coder task queued at {task_path}")
            print("  In your Claude Code session, invoke the cv-coder skill:")
            print(f'    "implement correction {primary_id} with cv-coder"')
            return
        # else: fall through to single-entry path
        family = "none"

    # Single-entry path (family='none', single eligible entry, or batch declined).
    answer = input(
        f"\n⚙ Entry #{promoted.id} is type='other' — describes an extractor-code change.\n"
        f"  Auto-implement now via the cv-coder agent? [y/N]: "
    ).strip().lower()
    if answer in ("y", "yes"):
        task_path = _queue_coder_task(
            output_dir, [promoted.id], family, registry=reg, reviewer=reviewer
        )
        reg.mark_in_progress([promoted.id])
        print(f"\n  cv-coder task queued at {task_path}")
        print("  In your Claude Code session, invoke the cv-coder skill:")
        print(f'    "implement correction {promoted.id} with cv-coder"')


def cmd_approve(args, reg: CorrectionsRegistry) -> int:
    try:
        promoted = reg.promote_to_active(entry_id=args.id, reviewer=args.reviewer, note=args.note)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Approved entry #{promoted.id} ({promoted.type}). Added to active_corrections.json.")
    print(f"Reviewer: {promoted.reviewer}")
    print(f"At:       {promoted.reviewed_at}")

    _prompt_other_after_approval(
        promoted, reg, _resolve_output_dir(args), reviewer=args.reviewer
    )
    return 0


def cmd_reject(args, reg: CorrectionsRegistry) -> int:
    try:
        rejected = reg.reject_pending(entry_id=args.id, reviewer=args.reviewer, reason=args.reason)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Rejected entry #{rejected.id} ({rejected.type}).")
    print(f"Reason:   {rejected.review_note}")
    return 0


def cmd_diff(args, reg: CorrectionsRegistry) -> int:
    entry = reg.find_in_pending(args.id)
    if entry is None:
        print(f"No pending entry with id {args.id}.", file=sys.stderr)
        return 1
    _print_diff(entry)
    return 0


# ---------- top-level ----------

def _default_reviewer() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review pending citizen_voice corrections.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Path to processed_output/ (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List pending / approved / rejected entries.")
    p_list.add_argument("--status", choices=["pending", "approved", "rejected"], default=None)

    p_show = sub.add_parser("show", help="Show one entry in full detail.")
    p_show.add_argument("id", type=int)

    p_approve = sub.add_parser("approve", help="Promote a pending entry to active.")
    p_approve.add_argument("id", type=int)
    p_approve.add_argument("--note", default=None)
    p_approve.add_argument("--reviewer", default=_default_reviewer())

    p_reject = sub.add_parser("reject", help="Reject a pending entry (with reason).")
    p_reject.add_argument("id", type=int)
    p_reject.add_argument("--reason", required=True)
    p_reject.add_argument("--reviewer", default=_default_reviewer())

    p_diff = sub.add_parser("diff", help="Show what the entry would add to the active rule set.")
    p_diff.add_argument("id", type=int)

    args = parser.parse_args(argv)
    reg = CorrectionsRegistry(_resolve_output_dir(args))

    dispatch = {
        "list":    cmd_list,
        "show":    cmd_show,
        "approve": cmd_approve,
        "reject":  cmd_reject,
        "diff":    cmd_diff,
    }
    return dispatch[args.cmd](args, reg)


if __name__ == "__main__":
    sys.exit(main())
