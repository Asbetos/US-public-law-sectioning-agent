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
import xml.etree.ElementTree as ET
from pathlib import Path

# The original extractor modules now live in this repo under legacy/.
_LEGACY_DIR = str(Path(__file__).resolve().parents[1] / "legacy")
if _LEGACY_DIR not in sys.path:
    sys.path.insert(0, _LEGACY_DIR)

from Extract_Sections_Divisions_From_XML import (  # noqa: E402
    extract_public_law_from_uslm as _extract_public_law_from_uslm_raw,
    extract_section_text,
    get_clean_text,
    process_section,
)
from law_id_corrections import (  # noqa: E402
    apply_law_id_corrections,
    apply_section_number_correction,
)

# Canonical public-law identifier shape: "Public Law <congress>-<docNumber>"
# where the separator is an ASCII hyphen, en-dash, or em-dash. Used by the
# malformed-law-id repair pass (entry #41) to detect LawIdentifier values that
# arose from corrupt source <citableAs> text.
_CANONICAL_PUBLIC_LAW_ID = re.compile(r"Public Law \d+[-–—]\d+")


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


def _disambiguate_sibling_levels(section_rows):
    """Post-process pass for the sibling-level correction family (entry #13,
    approved 2026-05-28 by asbetos).

    When a pLaw's ``<main>`` contains a ``<title>`` (or other top-level
    container) holding two or more sibling ``<level>`` elements, each with
    their own ``<section>`` children, the upstream extractor walks each
    ``<level>``'s sections but does not capture the ``<level>``'s own
    ``<heading>`` text into any ``UniqueKey``-bearing column. The resulting
    Section rows share ``(Title, SubTitle, Chapter, SubChapter, SectionNumber)``
    across sibling levels, collapsing to identical ``UniqueKey``.

    This pass walks ``section_rows`` in document order grouped by
    ``LawIdentifier``. Within each pLaw, rows are sub-grouped by their
    container prefix ``(Title, SubTitle, Chapter, SubChapter)``. For each
    sub-group, the pass tracks the set of section-number suffixes seen so
    far (normalized via ``clean_and_format_section_fixed``); when a row's
    suffix re-appears within the same prefix, that signals the start of a
    new sibling-level block. The block ordinal is incremented and every
    subsequent row in that prefix receives a sequential alpha marker
    ('B', 'C', ...) injected into the first empty column among
    ``SubTitle``, ``Chapter``, ``SubChapter``. The first sibling block
    (block_ordinal == 0) is left untouched so the dominant block's
    ``UniqueKey`` is unchanged.

    PL 92-351 TITLE IV (vol 86) is the affected example: two ``<level>``
    siblings each containing Sec. 1 and Sec. 2. Today both Sec. 1 rows
    (and both Sec. 2 rows) collapse to the same ``UniqueKey`` because
    only the parent TITLE IV heading is recorded.

    Mutates ``section_rows`` in place.
    """
    if not section_rows:
        return

    # Group row indices by LawIdentifier, preserving document order.
    by_law = {}
    for idx, row in enumerate(section_rows):
        law_id = row.get("LawIdentifier")
        by_law.setdefault(law_id, []).append(idx)

    # Local import to avoid module-level dependency on generate_id_keys.
    try:
        from generate_id_keys import clean_and_format_section_fixed
    except ImportError:  # pragma: no cover - defensive fallback
        return

    def _alpha_marker(ordinal):
        """1 -> 'B', 2 -> 'C', ... 25 -> 'Z', 26 -> 'AA', ..."""
        # Block ordinals start at 1 for the SECOND block. Map to letters
        # starting at 'B' so 'A' remains free for downstream uses.
        result = ""
        n = ordinal + 1  # shift so ordinal 1 -> 2 -> 'B'
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(ord("A") + rem) + result
        return result

    for law_id, indices in by_law.items():
        # Sub-group by container prefix (Title, SubTitle, Chapter, SubChapter)
        # in document order. Use a list of (prefix, [row_indices]) so we
        # preserve order across distinct prefixes inside one pLaw.
        prefix_groups = {}
        prefix_order = []
        for i in indices:
            row = section_rows[i]
            prefix = (
                (row.get("Title") or "").strip(),
                (row.get("SubTitle") or "").strip(),
                (row.get("Chapter") or "").strip(),
                (row.get("SubChapter") or "").strip(),
            )
            if prefix not in prefix_groups:
                prefix_groups[prefix] = []
                prefix_order.append(prefix)
            prefix_groups[prefix].append(i)

        for prefix in prefix_order:
            group_indices = prefix_groups[prefix]
            if len(group_indices) < 2:
                continue  # No collision possible inside a single-row prefix.

            seen_suffixes = set()
            block_ordinal = 0
            for i in group_indices:
                row = section_rows[i]
                suffix = clean_and_format_section_fixed(row.get("SectionNumber"))
                if suffix in seen_suffixes:
                    # Start of a new sibling-level block under this prefix.
                    block_ordinal += 1
                    seen_suffixes = {suffix}
                else:
                    seen_suffixes.add(suffix)

                if block_ordinal == 0:
                    continue  # First block — leave untouched.

                marker = _alpha_marker(block_ordinal)
                # Inject the marker into the first empty UniqueKey-bearing
                # column among SubTitle, Chapter, SubChapter. If all three
                # are populated, append the marker to SubChapter as a last
                # resort so the row still gets a distinct UniqueKey.
                for col in ("SubTitle", "Chapter", "SubChapter"):
                    existing = row.get(col)
                    if existing is None or not str(existing).strip():
                        row[col] = marker
                        break
                else:
                    # All four prefix slots populated upstream — append a
                    # marker to SubChapter as the deepest disambiguator.
                    row["SubChapter"] = f"{str(row['SubChapter']).rstrip()} {marker}"


def _disambiguate_sibling_appropriations(division_rows):
    """Post-process pass for the sibling-appropriations correction family
    (entry #5, approved 2026-05-28 by asbetos; extended by entry #24,
    approved 2026-05-28 by asbetos).

    Within a single pLaw, the extractor's appropriations walker can emit two or
    more Division rows whose ``(DivisionHeadingLevel1, DivisionHeadingLevel2,
    DivisionHeadingLevel3)`` triple is identical — typically a regular
    appropriation followed by an "additional amount" supplemental or a
    transferred appropriation that share the same ``<heading>`` text under the
    same parent ``<appropriations>``. Since the UniqueKey for Division rows is
    derived from these three heading-mapped IDs, the rows collapse to the same
    UniqueKey even though their ``<content>`` bodies differ.

    This pass groups Division rows by ``LawIdentifier`` first, then by full
    ``(L1, L2, L3)`` heading path in document order. For each group with two
    or more rows, it appends a sequential intra-heading ordinal (``" 2"``,
    ``" 3"``, ...) to the deepest non-null heading level on the 2nd and
    subsequent rows; the first row is left untouched so the dominant heading
    survives unchanged. The ordinal is appended to the heading TEXT so the
    downstream heading-to-ID mapper in ``generate_id_keys.py`` produces
    distinct ``DivisionHeadingLevel*`` IDs — and therefore distinct UniqueKeys —
    without any change to the key-generation pipeline itself.

    Entry #24 extension — case-insensitive collision detection: the downstream
    heading-to-ID mapper in ``generate_id_keys.py`` lower-cases heading text
    before lookup, so two heading paths that differ only in letter case
    ("Contingent Expenses of the Senate" vs "contingent expenses of the
    senate", PL 92-18 vol 85 TITLE II) still collapse to the same UniqueKey.
    The grouping key is therefore case-folded; the row's heading TEXT is
    preserved as-is, only the ordinal is appended so display case is unchanged
    on the first row and the second row keeps its original case + ordinal.

    Mutates ``division_rows`` in place.
    """
    if not division_rows:
        return

    # Group row indices by LawIdentifier, preserving document order.
    by_law = {}
    for idx, row in enumerate(division_rows):
        law_id = row.get("LawIdentifier")
        by_law.setdefault(law_id, []).append(idx)

    for law_id, indices in by_law.items():
        # Within a single pLaw, group by full (L1, L2, L3) heading triple.
        # The grouping key is case-folded so headings that differ only in
        # letter case still collide (the downstream heading-to-ID mapper
        # lower-cases before lookup; see generate_id_keys.handle_division_headings).
        path_groups = {}
        path_order = []
        for i in indices:
            row = division_rows[i]
            path = (
                (row.get("DivisionHeadingLevel1") or "").strip().casefold(),
                (row.get("DivisionHeadingLevel2") or "").strip().casefold(),
                (row.get("DivisionHeadingLevel3") or "").strip().casefold(),
            )
            if path not in path_groups:
                path_groups[path] = []
                path_order.append(path)
            path_groups[path].append(i)

        for path in path_order:
            group_indices = path_groups[path]
            if len(group_indices) < 2:
                continue  # No collision — nothing to disambiguate.
            # Append a sequential ordinal to the deepest non-null heading level
            # on the 2nd and subsequent rows (group_indices is already in
            # document order because we iterated row indices ascending).
            for ordinal, i in enumerate(group_indices[1:], start=2):
                row = division_rows[i]
                for level_key in (
                    "DivisionHeadingLevel3",
                    "DivisionHeadingLevel2",
                    "DivisionHeadingLevel1",
                ):
                    value = row.get(level_key)
                    if value is not None and str(value).strip():
                        row[level_key] = f"{str(value).rstrip()} {ordinal}"
                        break


def _container_label(elem, ns):
    """Return ``num.text + heading.text`` for an immediate ``<num>``/``<heading>``
    child of ``elem`` (a ``<part>``/``<title>``/``<chapter>`` container).
    Empty string if neither is present.
    """
    if elem is None:
        return ""
    num = elem.find("uslm:num", ns)
    heading = elem.find("uslm:heading", ns)
    return (
        (get_clean_text(num) if num is not None else "")
        + (get_clean_text(heading) if heading is not None else "")
    ).strip()


def _make_section_row(law_identifiers, approved_date, law_title, law_type,
                      section_number, section_name, text,
                      div1=None, div2=None, div3=None):
    """Build a Sections-row dict matching the schema produced by the upstream extractor."""
    return {
        "counter": 0,  # rewritten downstream; the upstream extractor does the same.
        "LawIdentifier": law_identifiers,
        "approvedDate": approved_date,
        "LawTitle": law_title,
        "LawType": law_type,
        "Division": None,
        "Title": None,
        "SubTitle": None,
        "Chapter": None,
        "SubChapter": None,
        "SectionNumber": section_number,
        "SectionName": section_name,
        "Text": text if text else None,
        "DivisionHeadingLevel1": div1,
        "DivisionHeadingLevel2": div2,
        "DivisionHeadingLevel3": div3,
    }


def _emit_section_rows(container_elem, ns, plaw_meta, div1, div2, div3, rows_out):
    """Emit one Sections row per ``<section>`` child of ``container_elem``.

    ``plaw_meta`` is a tuple ``(law_id, approved_date, law_title, law_type)``.
    Heading labels are carried into ``div1``/``div2``/``div3`` columns.
    """
    law_id, approved_date, law_title, law_type = plaw_meta
    for section in container_elem.findall("uslm:section", ns):
        num, heading, text = process_section(section, ns)
        num, flagged = apply_section_number_correction(
            num, law_id,
            get_clean_text(heading) if heading is not None else "",
            text,
        )
        rows_out.append(_make_section_row(
            law_identifiers=law_id,
            approved_date=approved_date,
            law_title=law_title,
            law_type=law_type,
            section_number=(num if flagged else get_clean_text(num) if num is not None else None),
            section_name=get_clean_text(heading) if heading is not None else None,
            text=text,
            div1=div1, div2=div2, div3=div3,
        ))


def _walk_container_recursively(elem, ns, plaw_meta, labels, rows_out):
    """Recurse into ``elem`` looking for ``<section>`` children at any nested
    container depth. ``labels`` is a list of accumulated heading labels (up to
    three levels carried into DivisionHeadingLevel1/2/3).

    Walks the nesting order: ``<part>``, ``<title>``, ``<chapter>``,
    ``<subchapter>``, ``<subtitle>``, ``<level>`` (any of which may be the
    direct child or nested).
    """
    # 1) Emit any direct <section> children at this level.
    has_direct_section = elem.find("uslm:section", ns) is not None
    if has_direct_section:
        div1 = labels[0] if len(labels) > 0 else None
        div2 = labels[1] if len(labels) > 1 else None
        div3 = labels[2] if len(labels) > 2 else None
        _emit_section_rows(elem, ns, plaw_meta, div1, div2, div3, rows_out)

    # 2) Recurse into any nested container child.
    for child_tag in ("part", "title", "chapter", "subchapter", "subtitle", "level"):
        for child in elem.findall(f"uslm:{child_tag}", ns):
            child_label = _container_label(child, ns)
            new_labels = labels + [child_label] if child_label else labels + [None]
            # Cap accumulated labels at 3 levels (DivisionHeadingLevel1..3).
            _walk_container_recursively(child, ns, plaw_meta, new_labels[:3], rows_out)


def _emit_appropriations_fallback_rows(container_elem, ns, plaw_meta, container_label, rows_out):
    """Entry #25 shape (b) helper: when a top-level container (e.g. ``<chapter>``)
    holds only ``<appropriations>`` and no ``<section>`` at any depth, synthesize
    ONE section row per ``<appropriations>`` block so the dropped pLaw is
    recovered.

    Walks ``<appropriations>`` at any nesting depth under ``container_elem`` and
    emits a row carrying:
      * ``DivisionHeadingLevel1`` = ``container_label`` (the chapter / title /
        part heading).
      * ``DivisionHeadingLevel2`` = the outer ``<appropriations>``'s ``<heading>``
        text (if any).
      * ``DivisionHeadingLevel3`` = the inner ``<appropriations>``'s ``<heading>``
        text (if any).
      * ``Text`` = the concatenated ``<content>``/text of the deepest
        ``<appropriations>``.

    Returns the number of rows emitted.
    """
    law_id, approved_date, law_title, law_type = plaw_meta
    emitted = 0

    def _appr_heading_text(appr):
        h = appr.find("uslm:heading", ns)
        return get_clean_text(h).strip() if h is not None else ""

    def _appr_body_text(appr):
        # Prefer direct <content>; otherwise the appropriations subtree text
        # minus headings (mirrors the upstream extractor's behavior).
        content = appr.find("uslm:content", ns)
        if content is not None:
            text = get_clean_text(content)
        else:
            text = get_clean_text(appr, "appr")
        return text.strip() if text else ""

    outer_apprs = container_elem.findall("uslm:appropriations", ns)
    for outer in outer_apprs:
        outer_h = _appr_heading_text(outer)
        inner_apprs = outer.findall("uslm:appropriations", ns)
        if inner_apprs:
            for inner in inner_apprs:
                inner_h = _appr_heading_text(inner)
                deepest = inner.findall("uslm:appropriations", ns)
                if deepest:
                    for d in deepest:
                        rows_out.append(_make_section_row(
                            law_identifiers=law_id,
                            approved_date=approved_date,
                            law_title=law_title,
                            law_type=law_type,
                            section_number=None,
                            section_name=None,
                            text=_appr_body_text(d) or None,
                            div1=container_label or None,
                            div2=outer_h or None,
                            div3=inner_h or None,
                        ))
                        emitted += 1
                else:
                    rows_out.append(_make_section_row(
                        law_identifiers=law_id,
                        approved_date=approved_date,
                        law_title=law_title,
                        law_type=law_type,
                        section_number=None,
                        section_name=None,
                        text=_appr_body_text(inner) or None,
                        div1=container_label or None,
                        div2=outer_h or None,
                        div3=None,
                    ))
                    emitted += 1
        else:
            rows_out.append(_make_section_row(
                law_identifiers=law_id,
                approved_date=approved_date,
                law_title=law_title,
                law_type=law_type,
                section_number=None,
                section_name=None,
                text=_appr_body_text(outer) or None,
                div1=container_label or None,
                div2=outer_h or None,
                div3=None,
            ))
            emitted += 1

    return emitted


def _collect_bare_main_body_text(main, ns):
    """Entry #25 shape (a) helper: collect text from bare ``<p>`` / ``<content>``
    children of ``<main>`` that are NOT part of the metadata wrappers
    (``<longTitle>``, ``<preamble>``, ``<resolvingClause>``, ``<enactingFormula>``,
    ``<action>``, ``<sidenote>``).

    Returns the concatenated text (joined with single spaces, stripped) or
    an empty string if no operative body text is present.
    """
    SKIP_TAGS = {
        "longTitle", "preamble", "resolvingClause", "enactingFormula",
        "action", "sidenote", "page", "approvedDate", "footnote",
    }
    pieces = []
    for child in list(main):
        tag = child.tag.split("}")[-1]
        if tag in SKIP_TAGS:
            continue
        if tag in ("p", "content"):
            text = get_clean_text(child)
            if text and text.strip():
                pieces.append(text.strip())
    return " ".join(pieces).strip()


def _compute_law_identifier(plaw, ns, vol):
    """Mirror of the upstream extractor's law-id derivation, used by the
    recovery pass to identify which pLaws were silently dropped.

    Returns the same string the upstream extractor would have written into
    ``LawIdentifier``; ``None`` if the pLaw is not public or no id is derivable.
    """
    lawtype_elem = plaw.find(".//uslm:publicPrivate", ns)
    if lawtype_elem is None or not lawtype_elem.text:
        return None
    if lawtype_elem.text.lower() != "public":
        return None

    try:
        vol_int = int(vol)
    except (TypeError, ValueError):
        vol_int = 0

    if vol_int > 63:
        c = plaw.find(".//uslm:citableAs", ns)
        law_identifiers = "".join(c.itertext()).strip() if c is not None else ""
        if vol_int == 70:
            c = plaw.find(".//uslm:docNumber", ns)
            law_identifiers = "".join(c.itertext()).strip() if c is not None else ""
            congress = plaw.find(".//uslm:congress", ns)
            congress_text = "".join(congress.itertext()).strip() if congress is not None else ""
            law_identifiers = "Public Law " + congress_text + "-" + law_identifiers
        if "v" in law_identifiers:
            c = plaw.find(".//uslm:docNumber", ns)
            law_identifiers = "".join(c.itertext()).strip() if c is not None else ""
            law_identifiers = "Public Law " + law_identifiers
        if "public law" not in law_identifiers.lower():
            c = plaw.find(".//uslm:docNumber", ns)
            law_identifiers = "".join(c.itertext()).strip() if c is not None else ""
            congress = plaw.find(".//uslm:congress", ns)
            congress_text = "".join(congress.itertext()).strip() if congress is not None else ""
            law_identifiers = "Public Law " + congress_text + "-" + law_identifiers
    else:
        c = plaw.find(".//uslm:sidenote", ns)
        law_identifiers_text = "".join(c.itertext()).strip() if c is not None else ""
        pattern1 = r"\bPublic Law\s+\d+(?:-\d+)?\b"
        pattern2 = r"[Pp]ub[l]?i[c]?[e]?\s*,?\.?\s*No\.?\s*\d+.+"
        match = re.search(pattern1, law_identifiers_text) or re.search(pattern2, law_identifiers_text)
        congress = plaw.find(".//uslm:congress", ns)
        congress_text = "".join(congress.itertext()).strip() if congress is not None else ""
        law_identifiers = ""
        if match:
            law_identifiers = match.group(0)
            law_num = re.search(r"\d+", law_identifiers)
            if law_num is None:
                return None
            law_identifiers = congress_text + "-" + str(law_num.group(0))
        else:
            return None

    law_title_elem = plaw.find(".//uslm:officialTitle", ns)
    law_title = get_clean_text(law_title_elem) if law_title_elem is not None else ""
    law_identifiers = apply_law_id_corrections(law_identifiers, law_title)
    return law_identifiers


def _recover_dropped_container_pLaws(file_path, vol, results):
    """Post-extraction recovery for the top-level-container correction family
    (entries #3, #7, #11, #17, approved 2026-05-28 by asbetos; extended by
    entry #25, approved 2026-05-28 by asbetos).

    A pLaw whose ``<main>`` has NO top-level ``<section>`` children — only
    container elements (``<part>``, ``<title>``, ``<chapter>``, bare
    ``<subsection>``, or ``<quotedContent>``) — is silently dropped by the
    upstream section walker (0 rows emitted). This pass:

      1. Re-parses the XML to enumerate public pLaws.
      2. For each public pLaw whose ``LawIdentifier`` is absent from the
         existing ``Sections``+``Divisions`` row sets, walks ``<main>``:
           * direct ``<section>`` children → emit row per section (defensive;
             upstream would normally have already handled this).
           * ``<part>``/``<title>``/``<chapter>`` containers (possibly nested
             title>part, etc.) → walk recursively and emit one row per
             ``<section>``, carrying container headings into Division
             columns 1-3.
           * Entry #25 shape (b): a ``<part>``/``<title>``/``<chapter>``
             container whose recursive walk yields ZERO rows but which holds
             ``<appropriations>`` (PL 93-624 supplemental-appropriations
             Joint Resolution shape: ``<chapter><appropriations>`` only, no
             nested ``<section>``) → synthesize one row per ``<appropriations>``
             block carrying the container heading on
             ``DivisionHeadingLevel1`` and the appropriations headings on
             ``DivisionHeadingLevel2/3``.
           * bare ``<subsection>`` children → synthesize ONE section row whose
             ``Text`` is the concatenated subsection text (short single-section
             amending-Act shape, e.g. PL 87-397).
           * ``<quotedContent>`` children → synthesize ONE section row whose
             ``Text`` is the quoted amendatory text (joint-resolution shape,
             e.g. PL 94-7).
           * Entry #25 shape (a): bare ``<p>`` / ``<content>`` operative
             paragraph(s) under ``<main>`` with no other recognized container
             (PL 93-513 nuclear-warship Joint Resolution "policy" shape) →
             synthesize ONE section row whose ``Text`` is the concatenated
             text of those bare children.

    Mutates ``results['Sections']`` in place. Idempotent: pLaws already present
    in results are not re-walked.
    """
    try:
        tree = ET.parse(file_path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return
    root = tree.getroot()
    ns = {"uslm": root.tag.split("}")[0].strip("{")}

    sections_list = results.get("Sections", [])
    divisions_list = results.get("Divisions", [])
    existing_law_ids = {
        r.get("LawIdentifier") for r in sections_list if r.get("LawIdentifier") is not None
    } | {
        r.get("LawIdentifier") for r in divisions_list if r.get("LawIdentifier") is not None
    }

    for plaw in root.findall(".//uslm:pLaw", ns):
        law_id = _compute_law_identifier(plaw, ns, vol)
        if not law_id:
            continue
        if law_id in existing_law_ids:
            continue  # not dropped — upstream walker handled it
        main = plaw.find("uslm:main", ns)
        if main is None:
            continue

        # Gather pLaw-level metadata for row construction.
        approved_date_elem = plaw.find(".//uslm:approvedDate", ns)
        approved_date = (
            "".join(approved_date_elem.itertext()).strip()
            if approved_date_elem is not None else ""
        )
        law_title_elem = plaw.find(".//uslm:officialTitle", ns)
        law_title = get_clean_text(law_title_elem) if law_title_elem is not None else ""
        law_type_elem = plaw.find(".//uslm:docTitle", ns)
        law_type = get_clean_text(law_type_elem) if law_type_elem is not None else ""
        plaw_meta = (law_id, approved_date, law_title, law_type)

        # Snapshot row count before this pLaw's recovery walk so we can verify
        # whether anything was actually emitted.
        before_count = len(sections_list)

        # Family member #3a / #7 / #11 (and any nested combinations):
        # walk part / title / chapter containers recursively for <section>.
        # Entry #25 shape (b) extension: when a top-level container yields
        # zero rows but holds <appropriations> (no nested <section> anywhere),
        # synthesize one row per <appropriations> block instead of leaving the
        # pLaw dropped (PL 93-624 shape: <chapter><appropriations> only).
        for tag in ("part", "title", "chapter"):
            for top_container in main.findall(f"uslm:{tag}", ns):
                top_label = _container_label(top_container, ns)
                before_container = len(sections_list)
                _walk_container_recursively(
                    top_container, ns, plaw_meta,
                    [top_label] if top_label else [None],
                    sections_list,
                )
                if len(sections_list) == before_container:
                    # Container produced no <section> rows. If it carries
                    # <appropriations>, synthesize one row per block.
                    if top_container.find("uslm:appropriations", ns) is not None:
                        _emit_appropriations_fallback_rows(
                            top_container, ns, plaw_meta, top_label, sections_list,
                        )

        # If a container walk emitted rows, we're done for this pLaw — fall
        # through only when nothing was emitted (subsection-only / quotedContent
        # shapes).
        if len(sections_list) > before_count:
            existing_law_ids.add(law_id)
            continue

        # Family member #3b: <main> contains bare <subsection> elements.
        # Synthesize ONE section row carrying the concatenated subsection text.
        subsections = main.findall("uslm:subsection", ns)
        if subsections:
            sub_texts = []
            for subsection in subsections:
                sub_text = extract_section_text(subsection, ns)
                if sub_text:
                    sub_texts.append(sub_text)
            sections_list.append(_make_section_row(
                law_identifiers=law_id,
                approved_date=approved_date,
                law_title=law_title,
                law_type=law_type,
                section_number="1",
                section_name=None,
                text="\n".join(sub_texts) if sub_texts else None,
            ))
            existing_law_ids.add(law_id)
            continue

        # Family member #17: <main> contains <quotedContent> directly.
        # Synthesize ONE section row carrying the quotedContent text.
        quoted_blocks = main.findall("uslm:quotedContent", ns)
        if quoted_blocks:
            quoted_texts = []
            for qc in quoted_blocks:
                qc_text = get_clean_text(qc)
                if qc_text:
                    quoted_texts.append(qc_text.strip())
            sections_list.append(_make_section_row(
                law_identifiers=law_id,
                approved_date=approved_date,
                law_title=law_title,
                law_type=law_type,
                section_number="1",
                section_name=None,
                text="\n".join(t for t in quoted_texts if t) if quoted_texts else None,
            ))
            existing_law_ids.add(law_id)
            continue

        # Entry #25 shape (a): <main> contains bare <p> or <content> operative
        # paragraph(s) (e.g. PL 93-513 nuclear-warship Joint Resolution) — no
        # <section>, <part>, <title>, <chapter>, <subsection>, or
        # <quotedContent>. Synthesize ONE section row carrying the concatenated
        # operative text.
        bare_body_text = _collect_bare_main_body_text(main, ns)
        if bare_body_text:
            sections_list.append(_make_section_row(
                law_identifiers=law_id,
                approved_date=approved_date,
                law_title=law_title,
                law_type=law_type,
                section_number="1",
                section_name=None,
                text=bare_body_text,
            ))
            existing_law_ids.add(law_id)
            continue


def _repair_malformed_law_identifiers(file_path, vol, results):
    """Post-extraction repair for the malformed-law-id correction family
    (entry #41, approved 2026-06-02 by "asbetos auto-approve batch2").

    Corrupt source ``<citableAs>`` text yields ``LawIdentifier`` values that do
    not match the canonical ``Public Law <congress>-<docNumber>`` shape:

      * vol 105 — ``<citableAs>`` is ``"Public Law 102–v"`` (the public-law
        NUMBER is the literal token ``v``). The upstream "v"-branch rebuilds
        from ``<docNumber>`` alone, dropping ``<congress>``, so the row carries
        a bare ``"Public Law 23"`` … ``"Public Law 49"`` (18 pLaws).
      * vol 108 — ``<citableAs>`` is ``"Public Law 103ߝ399"`` where the
        congress/number separator is the corrupt non-dash character U+07DD;
        the extractor passes it through verbatim as ``"Public Law 103ߝ399"``.

    This pass re-parses the XML and, for every PUBLIC pLaw whose extractor-
    computed ``LawIdentifier`` (mirrored via :func:`_compute_law_identifier`)
    does NOT match :data:`_CANONICAL_PUBLIC_LAW_ID`, re-derives the id from the
    authoritative ``<docNumber>`` and ``<congress>`` as
    ``"Public Law {congress}-{docNumber}"``. The authoritative metadata is
    preferred over attempting to repair the corrupt ``citableAs`` string.

    It builds a ``{malformed_id: corrected_id}`` map (only for pLaws whose
    rebuilt id is itself canonical) and rewrites every ``Sections`` /
    ``Divisions`` row whose ``LawIdentifier`` matches a malformed key. Rows that
    already carry a canonical id are left untouched. Mutates ``results`` in
    place; idempotent.
    """
    try:
        tree = ET.parse(file_path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return
    root = tree.getroot()
    ns = {"uslm": root.tag.split("}")[0].strip("{")}

    repair_map = {}
    for plaw in root.findall(".//uslm:pLaw", ns):
        malformed_id = _compute_law_identifier(plaw, ns, vol)
        if not malformed_id:
            continue
        if _CANONICAL_PUBLIC_LAW_ID.search(malformed_id):
            continue  # already canonical — nothing to repair

        doc_elem = plaw.find(".//uslm:docNumber", ns)
        doc_number = (
            "".join(doc_elem.itertext()).strip() if doc_elem is not None else ""
        )
        congress_elem = plaw.find(".//uslm:congress", ns)
        congress = (
            "".join(congress_elem.itertext()).strip()
            if congress_elem is not None else ""
        )
        if not doc_number or not congress:
            continue  # no authoritative metadata to rebuild from

        corrected_id = f"Public Law {congress}-{doc_number}"
        if not _CANONICAL_PUBLIC_LAW_ID.search(corrected_id):
            continue  # rebuilt id still not canonical — leave row as-is
        repair_map[malformed_id] = corrected_id

    if not repair_map:
        return

    for key in ("Sections", "Divisions"):
        for row in results.get(key, []):
            current = row.get("LawIdentifier")
            if current in repair_map:
                row["LawIdentifier"] = repair_map[current]


def extract_public_law_from_uslm(file_path, vol):
    """Wrap the raw extractor and apply post-extraction corrections.

    Applies the following post-extraction correction families layered on the
    raw extractor output:

      * **null-num** (entries #2, #14, #15, #16): when multiple ``<section>``
        rows in the same pLaw would collapse to the same ``UniqueKey`` suffix
        due to a missing ``<num value=...>``, assign each null row a distinct
        synthetic ``SectionNumber`` (``'U{n}'``) so downstream ``UniqueKey``
        generation stays unique without inventing source section numbers.

      * **top-level-container** (entries #3, #7, #11, #17): when a pLaw's
        ``<main>`` has zero top-level ``<section>`` children — only container
        elements (``<part>``, ``<title>``, ``<chapter>``, bare ``<subsection>``,
        or ``<quotedContent>``) — the upstream walker silently drops it (0 rows
        emitted). The recovery pass detects these dropped pLaws, walks the
        containers, and emits synthesized rows so distinct ``LawIdentifier``
        counts match the volume's public-pLaw count.

      * **sibling-appropriations** (entry #5): when a pLaw contains two or more
        sibling ``<appropriations>`` elements that share identical ``<heading>``
        text under the same parent (regular + supplemental "additional amount"
        + transferred), the extractor emits one Division row per
        ``<appropriations>`` but the heading-derived ``UniqueKey`` positions
        collide. The post-pass appends a sequential intra-heading ordinal
        (``" 2"``, ``" 3"``, ...) to the deepest non-null heading level on the
        2nd and subsequent occurrences within each pLaw.

      * **sibling-level** (entry #13): when a pLaw's ``<title>`` (or other
        top-level container) holds two or more sibling ``<level>`` elements
        each with their own ``<section>`` children, the upstream extractor
        does not capture the ``<level>``'s heading into any
        ``UniqueKey``-bearing column. Within a single pLaw and a single
        ``(Title, SubTitle, Chapter, SubChapter)`` prefix, the post-pass
        detects a repeating section-number suffix as the start of a new
        sibling-level block and injects a sequential alpha marker
        ('B', 'C', ...) into the first empty column among
        ``SubTitle``/``Chapter``/``SubChapter`` so the 2nd and subsequent
        block's rows produce distinct ``UniqueKey``\\ s. The first block is
        left untouched.

      * **malformed-law-id** (entry #41): when corrupt source ``<citableAs>``
        text yields a ``LawIdentifier`` that does not match the canonical
        ``Public Law <congress>-<docNumber>`` shape — vol 105's bare
        ``"Public Law 23"`` (the "v"-token shape) and vol 108's
        ``"Public Law 103ߝ399"`` (corrupt U+07DD separator) — the repair pass
        re-derives the id from the authoritative ``<docNumber>`` and
        ``<congress>`` and rewrites the affected ``Sections`` / ``Divisions``
        rows. It runs AFTER the container-recovery pass (whose ``LawIdentifier``
        bookkeeping mirrors the raw extractor's malformed ids) but BEFORE the
        row-level grouping passes, so they group on the corrected (canonical)
        ``LawIdentifier``.
    """
    results = _extract_public_law_from_uslm_raw(file_path, vol)
    if isinstance(results, dict) and "Sections" in results:
        _recover_dropped_container_pLaws(file_path, vol, results)
        # The malformed-id repair pass rebuilds ids from <docNumber>, which is the
        # PUBLIC-LAW number for modern volumes (>63) but the CHAPTER number for legacy
        # volumes (<=63). Legacy ids now come correctly from the legacy-law-identity
        # resolver, so the repair pass must only run for modern volumes.
        if int(vol) > 63:
            _repair_malformed_law_identifiers(file_path, vol, results)
        _assign_unnumbered_section_ordinals(results["Sections"])
        _disambiguate_sibling_levels(results["Sections"])
    if isinstance(results, dict) and "Divisions" in results:
        _disambiguate_sibling_appropriations(results["Divisions"])
    return results


__all__ = ["extract_public_law_from_uslm", "get_clean_text"]
