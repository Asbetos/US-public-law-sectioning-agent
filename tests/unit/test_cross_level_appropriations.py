"""Regression tests for the cross-level / case-folded sibling-appropriations
collision (entry #24, approved 2026-05-28 by asbetos).

Correction #5's ``_disambiguate_sibling_appropriations`` already groups Division
rows by their ``(DivisionHeadingLevel1, DivisionHeadingLevel2,
DivisionHeadingLevel3)`` triple and appends a sequential ordinal (" 2", " 3",
...) to the deepest non-null heading level on the 2nd and subsequent rows
within a same-LawIdentifier group. However, the original implementation
grouped on the raw (stripped) heading strings — so two ``<appropriations>``
siblings whose ``<heading>`` texts case-fold to the same value
("Contingent Expenses of the Senate" vs "contingent expenses of the senate")
escape detection: they appear as distinct path tuples, no ordinal is
appended, and the downstream heading-to-ID mapper in ``generate_id_keys.py``
lower-cases the heading text and produces an identical ``UniqueKey`` for
both rows.

The affected example from vol 85:
  * PL 92-18, TITLE II 'INCREASED PAY COSTS' — under
    ``<appropriations level="major"><heading>LEGISLATIVE BRANCH</heading>``
    one intermediate-level ``<appropriations>`` carries
    ``<heading>Contingent Expenses of the Senate</heading>`` and a later
    small-level sibling carries ``<heading>contingent expenses of the
    senate</heading>``. Their Division rows collapse to the same UniqueKey.

These tests pin the family fix: collision detection in the post-pass must be
case-insensitive so any same-pLaw Division-row pair whose heading paths
case-fold to the same value receives the disambiguating ordinal.
"""
from pathlib import Path

from parser.uslm_parser import extract_public_law_from_uslm


def _write_uslm_xml(tmp_dir: Path, body_xml: str) -> Path:
    """Wrap one or more ``<pLaw>`` fragments in a complete USLM document on disk."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<uslm xmlns="http://schemas.gpo.gov/xml/uslm">\n'
        f'{body_xml}\n'
        '</uslm>\n'
    )
    xml_path = tmp_dir / "STATUTE-test.xml"
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path


def _build_plaw(law_id_human: str, main_inner_xml: str, doc_title: str = "AN ACT") -> str:
    return f"""
      <pLaw>
        <publicPrivate>public</publicPrivate>
        <citableAs>{law_id_human}</citableAs>
        <approvedDate>1971-05-25</approvedDate>
        <officialTitle>Test Cross-Level Appropriations Act</officialTitle>
        <docTitle>{doc_title}</docTitle>
        <main>
          {main_inner_xml}
        </main>
      </pLaw>
    """


def _divisions_for(result, law_id_human):
    needle_hyphen = law_id_human.replace("–", "-")
    needle_endash = law_id_human.replace("-", "–")
    return [
        r for r in result["Divisions"]
        if r["LawIdentifier"] in (law_id_human, needle_hyphen, needle_endash)
        or law_id_human in r["LawIdentifier"]
    ]


def _heading_path_casefolded(row):
    """Return the case-folded heading path so a UniqueKey-equivalent comparison
    can be made (the downstream mapper in generate_id_keys.py lower-cases
    heading text before lookup, so two heading paths that case-fold to the
    same tuple produce identical UniqueKeys).
    """
    return (
        (row.get("DivisionHeadingLevel1") or "").strip().casefold(),
        (row.get("DivisionHeadingLevel2") or "").strip().casefold(),
        (row.get("DivisionHeadingLevel3") or "").strip().casefold(),
    )


# ---------- Entry #24a: case-folded sibling heading collision on level-2 ----------

def test_entry_24_case_folded_sibling_appropriations_get_disambiguating_ordinal(tmp_path):
    """PL 92-18, vol 85 shape: under a major-level ``<heading>LEGISLATIVE
    BRANCH</heading>`` parent, an intermediate ``<appropriations>`` with
    ``<heading>Contingent Expenses of the Senate</heading>`` and a later
    small-level ``<appropriations>`` with ``<heading>contingent expenses of
    the senate</heading>`` are both walked by the extractor's intermediate
    loop (it doesn't inspect ``level``; both are direct ``<appropriations>``
    children of the major parent).

    Both rows are emitted with ``DivisionHeadingLevel1='LEGISLATIVE BRANCH'``
    and ``DivisionHeadingLevel2`` carrying their respective heading text. The
    case difference alone is NOT enough — the downstream heading-to-ID
    mapper lower-cases before lookup, so both rows produce the same
    UniqueKey. The fix: the sibling-appropriations post-pass must detect
    collisions case-insensitively and append a sequential ordinal to the
    deepest non-null heading level on the second occurrence.
    """
    main_inner = """
      <appropriations level="major">
        <heading>LEGISLATIVE BRANCH</heading>
        <appropriations level="intermediate">
          <heading>Senate</heading>
          <content>For Senate, $100,000.</content>
        </appropriations>
        <appropriations level="intermediate">
          <heading>Contingent Expenses of the Senate</heading>
          <content>Senate policy committees, automobiles, inquiries, folding documents.</content>
        </appropriations>
        <appropriations level="intermediate">
          <heading>House of Representatives</heading>
          <content>For House, $200,000.</content>
        </appropriations>
        <appropriations level="intermediate">
          <heading>Joint Items</heading>
          <content>Joint Committee on Reduction of Federal Expenditures, $5,440.</content>
        </appropriations>
        <appropriations level="small">
          <heading>contingent expenses of the senate</heading>
          <content>Joint Economic Committee, Joint Committee on Atomic Energy, Joint Committee on Printing.</content>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-918", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-918")

    # 5 intermediate-level rows expected: Senate, Contingent Expenses (cap),
    # House, Joint Items, contingent expenses (lower).
    assert len(rows) == 5, (
        f"Expected 5 Division rows from sibling intermediate <appropriations>, "
        f"got {len(rows)}: {[(r.get('DivisionHeadingLevel1'), r.get('DivisionHeadingLevel2')) for r in rows]}"
    )

    # The two 'contingent expenses of the senate' rows must have distinct
    # heading paths AFTER case-folding (which is what the downstream
    # UniqueKey generator actually does).
    cf_paths = [_heading_path_casefolded(r) for r in rows]
    assert len(set(cf_paths)) == 5, (
        f"Case-folded heading paths still collide — UniqueKey will duplicate: {cf_paths}"
    )

    # Identify the two rows whose Level-2 heading case-folds to
    # 'contingent expenses of the senate'.
    colliding_rows = [
        (i, r) for i, r in enumerate(rows)
        if (r.get("DivisionHeadingLevel2") or "").strip().casefold().startswith(
            "contingent expenses of the senate"
        )
    ]
    assert len(colliding_rows) == 2, (
        f"Expected exactly 2 rows whose L2 case-folds to "
        f"'contingent expenses of the senate', got {len(colliding_rows)}: "
        f"{[r.get('DivisionHeadingLevel2') for _, r in colliding_rows]}"
    )

    # First occurrence (document order) keeps its heading text unchanged.
    first_idx, first_row = colliding_rows[0]
    assert (first_row.get("DivisionHeadingLevel2") or "").strip() == (
        "Contingent Expenses of the Senate"
    ), (
        f"Expected first colliding row to retain 'Contingent Expenses of the Senate', "
        f"got {first_row.get('DivisionHeadingLevel2')!r}"
    )

    # Second occurrence has the ordinal appended.
    second_idx, second_row = colliding_rows[1]
    second_l2 = (second_row.get("DivisionHeadingLevel2") or "").strip().casefold()
    assert second_l2.startswith("contingent expenses of the senate") and "2" in second_l2, (
        f"Expected second colliding row's L2 to carry the ordinal '2', "
        f"got {second_row.get('DivisionHeadingLevel2')!r}"
    )


# ---------- Entry #24b: case-folded collision across non-adjacent siblings ----------

def test_entry_24_case_folded_collision_across_nonadjacent_siblings(tmp_path):
    """Two ``<appropriations>`` whose case-folded headings collide need not be
    adjacent siblings — other distinct-heading siblings can sit between them.
    The post-pass must still detect and disambiguate the pair.
    """
    main_inner = """
      <appropriations level="major">
        <heading>DEPARTMENT OF THE INTERIOR</heading>
        <appropriations level="intermediate">
          <heading>Office of Territories</heading>
          <content>For Office of Territories, $1,000,000.</content>
        </appropriations>
        <appropriations level="intermediate">
          <heading>Bureau of Indian Affairs</heading>
          <content>For BIA, $5,000,000.</content>
        </appropriations>
        <appropriations level="intermediate">
          <heading>National Park Service</heading>
          <content>For NPS, $42,000,000.</content>
        </appropriations>
        <appropriations level="small">
          <heading>OFFICE OF TERRITORIES</heading>
          <content>Additional amount for Office of Territories.</content>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-919", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-919")

    assert len(rows) == 4, (
        f"Expected 4 Division rows, got {len(rows)}: "
        f"{[(r.get('DivisionHeadingLevel1'), r.get('DivisionHeadingLevel2')) for r in rows]}"
    )

    cf_paths = [_heading_path_casefolded(r) for r in rows]
    assert len(set(cf_paths)) == 4, (
        f"Case-folded heading paths still collide — UniqueKey will duplicate: {cf_paths}"
    )

    # Locate the two 'office of territories' rows by case-folded comparison.
    colliding = [
        r for r in rows
        if (r.get("DivisionHeadingLevel2") or "").strip().casefold().startswith(
            "office of territories"
        )
    ]
    assert len(colliding) == 2, (
        f"Expected 2 'office of territories' rows, got {len(colliding)}: "
        f"{[r.get('DivisionHeadingLevel2') for r in colliding]}"
    )

    # The 2nd occurrence (the UPPERCASE one, since it appears later in the
    # document) must carry the disambiguating ordinal.
    second_l2 = (colliding[1].get("DivisionHeadingLevel2") or "").strip().casefold()
    assert second_l2.startswith("office of territories") and "2" in second_l2, (
        f"Expected second 'office of territories' row to carry ordinal '2', "
        f"got {colliding[1].get('DivisionHeadingLevel2')!r}"
    )


# ---------- Guard: case-only-difference grouping does not break the existing same-case path ----------

def test_entry_24_does_not_re_ordinalize_same_case_collisions(tmp_path):
    """If two sibling ``<appropriations>`` headings already match by raw text
    (same case), correction #5's existing behavior must be preserved: ordinal
    appended to the second row only, exactly once. The case-insensitive
    grouping must not double-tag or re-tag.
    """
    main_inner = """
      <appropriations>
        <heading>DEPARTMENT OF THE INTERIOR</heading>
        <appropriations>
          <heading>National Park Service</heading>
          <appropriations level="small">
            <heading>construction</heading>
            <content>For construction, $42,000,000.</content>
          </appropriations>
          <appropriations level="small">
            <heading>construction</heading>
            <content>Additional amount for construction, $5,000,000.</content>
          </appropriations>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-920", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-920")

    assert len(rows) == 2, f"Expected 2 Division rows, got {len(rows)}: {rows}"

    l3_values = [(r.get("DivisionHeadingLevel3") or "").strip() for r in rows]
    # First stays untouched.
    assert l3_values[0] == "construction", l3_values
    # Second gets exactly one ordinal '2' appended.
    assert l3_values[1].lower().startswith("construction") and "2" in l3_values[1], l3_values
    # Verify single ordinal (not '2 2' or similar double-tag).
    assert l3_values[1].count("2") == 1, (
        f"Expected exactly one '2' in disambiguated heading, got {l3_values[1]!r}"
    )
