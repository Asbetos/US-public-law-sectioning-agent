"""USLM parser facade.

The actual extractor lives in ``Extract_Sections_Divisions_From_XML.py`` in
``/home/G39248410/citizen_voice/Code/``. This module re-exports the public
API under the new package layout so callers can do
``from parser.uslm_parser import extract_public_law_from_uslm``.

Post-extraction corrections that apply to the section row list (not to the
walk itself) live here as well, layered on top of the raw extractor output.
"""
import re
import sys
from pathlib import Path

_CODE_DIR = str(Path("/home/G39248410/citizen_voice/Code").resolve())
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from Extract_Sections_Divisions_From_XML import (  # noqa: E402
    extract_public_law_from_uslm as _extract_public_law_from_uslm_raw,
    get_clean_text,
)


def _section_number_maps_to_null_fallback(text):
    """Mirror of ``clean_and_format_section_fixed`` (generate_id_keys.py):
    return True iff this SectionNumber value would produce the null-fallback
    UniqueKey suffix ``'000000000000001'`` — i.e. ``None``, ``'1'``,
    ``'Section 1.'``, ``'Sec. 1.'``, etc.

    Used by :func:`_assign_unnumbered_section_ordinals` to detect when a
    null-section row in a pLaw would collide with an explicit Section 1 /
    Sec. 1. in the same pLaw (null-num correction family, entries #14 / #15).
    """
    if text is None:
        return True
    s = str(text).strip().upper()
    s = re.sub(r'^(SECTION|SEC\.?)\s*', '', s)
    s = ''.join(filter(str.isalnum, s))
    return s == "1"


def _assign_unnumbered_section_ordinals(section_rows):
    """Post-process pass for the null-num correction family (entries #2, #14,
    #15, #16, approved 2026-05-28 by G39248410).

    Group ``section_rows`` by ``LawIdentifier`` in document order. For each
    pLaw whose null-``SectionNumber`` rows would cause a ``UniqueKey`` suffix
    collision — either with each other (``>=2`` nulls) or with an explicit
    ``Section 1`` / ``Sec. 1.`` mapping to the same null-fallback suffix —
    rewrite each null ``SectionNumber`` with a synthetic ``'U{n}'`` ordinal
    in insertion order. The ``'U'`` prefix keeps synthetic ordinals in a
    namespace that cannot collide with explicit numeric section numbers when
    they flow through ``clean_and_format_section_fixed``.

    pLaws with a single null section and no explicit ``'1'``-equivalent are
    left untouched: their ``UniqueKey`` is already unique without intervention.
    Mutates ``section_rows`` in place.
    """
    # Group row indices by LawIdentifier, preserving first-seen order.
    by_law = {}
    for idx, row in enumerate(section_rows):
        law_id = row.get("LawIdentifier")
        by_law.setdefault(law_id, []).append(idx)

    for law_id, indices in by_law.items():
        null_idxs = [i for i in indices if section_rows[i].get("SectionNumber") is None]
        if not null_idxs:
            continue

        explicit_collides_with_null = any(
            section_rows[i].get("SectionNumber") is not None
            and _section_number_maps_to_null_fallback(section_rows[i].get("SectionNumber"))
            for i in indices
        )

        if len(null_idxs) >= 2 or explicit_collides_with_null:
            for ordinal, i in enumerate(null_idxs, start=1):
                section_rows[i]["SectionNumber"] = f"U{ordinal}"


def extract_public_law_from_uslm(file_path, vol):
    """Wrap the raw extractor and apply post-extraction corrections.

    Currently applies the null-num correction family (entries #2, #14, #15,
    #16): when multiple ``<section>`` rows in the same pLaw would collapse to
    the same ``UniqueKey`` suffix due to a missing ``<num value=...>``, assign
    each null row a distinct synthetic ``SectionNumber`` (``'U{n}'``) so
    downstream ``UniqueKey`` generation stays unique without inventing source
    section numbers.
    """
    results = _extract_public_law_from_uslm_raw(file_path, vol)
    if isinstance(results, dict) and "Sections" in results:
        _assign_unnumbered_section_ordinals(results["Sections"])
    return results


__all__ = ["extract_public_law_from_uslm", "get_clean_text"]
