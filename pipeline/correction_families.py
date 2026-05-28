"""Classify type='other' correction entries into families by trigger pattern.

Each family represents a group of corrections that share a root cause in the
extractor code, so they can be implemented as one fused diff by the cv-coder
subagent. Used by approve_corrections.py to offer batch-mode approval +
implementation.

Families:
    null-num                 #2, #14, #15, #16 (SectionNumber=null collisions)
    top-level-container      #3, #7, #11, #17 (<main> has no <section> child)
    sibling-appropriations   #5
    sibling-level            #13
    none                     anything else (including non-'other' types)
"""
from __future__ import annotations

from collections import defaultdict

# Keyword tables. Each family is a list of substrings that, if found in
# trigger.pattern (case-insensitive) OR correction.description, classify
# the entry into that family. First match wins; check families in this order.
_FAMILY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("null-num", (
        "sectionnumber is null",
        "outer <section>",
        "unnumbered opening",
        "null <num>",
        "no <num>",
        "without appropriate num",
        "lacking <num>",
        "lacks the <num>",
        'section class="inline"',
        "enacting paragraph",
    )),
    ("top-level-container", (
        "<main> contains <part>",
        "<main> contains <title>",
        "<main> contains <chapter>",
        "<main> contains <quotedcontent>",
        "no top-level <section>",
        "zero top-level <section>",
        "bare <subsection>",
        "<main> has zero top-level",
        "<main> has no top-level",
    )),
    ("sibling-appropriations", (
        "sibling <appropriations>",
        "<appropriations> elements sharing",
    )),
    ("sibling-level", (
        "sibling <level>",
        "<level> elements within a single <title>",
    )),
]


def classify(entry: dict) -> str:
    """Return the family name for one correction entry, or 'none' if unclassified.

    Only `type='other'` entries are eligible — anything else returns 'none'.
    Matches first against `trigger.pattern`; if empty, falls back to
    `correction.description`. Case-insensitive."""
    if entry.get("type") != "other":
        return "none"
    pattern = (entry.get("trigger", {}).get("pattern") or "").lower()
    if not pattern:
        pattern = (entry.get("correction", {}).get("description") or "").lower()
    for family, needles in _FAMILY_KEYWORDS:
        if any(needle.lower() in pattern for needle in needles):
            return family
    return "none"


def family_members(
    entries: list[dict],
    *,
    pending_only: bool = False,
) -> dict[str, list[int]]:
    """Group entries by family. Returns {family_name: [entry_id, ...]}.

    Only families that have at least one matching entry appear in the result.
    Entries that classify as 'none' are dropped (not under a 'none' key).

    If ``pending_only=True``, only entries whose `implementation_status` is
    `'pending'` are included.
    """
    out: dict[str, list[int]] = defaultdict(list)
    for e in entries:
        if pending_only and e.get("implementation_status") != "pending":
            continue
        fam = classify(e)
        if fam == "none":
            continue
        out[fam].append(e["id"])
    return dict(out)
