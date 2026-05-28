"""Regression tests for the sibling-appropriations correction family (entry #5).

When a pLaw contains two or more sibling ``<appropriations>`` elements that share
identical ``<heading>`` text under the same parent, the extractor's appropriations
walker emits one Division row per ``<appropriations>``. Because ``UniqueKey``
positions for Division rows are derived from the heading text path
(``DivisionHeadingLevel1``/``2``/``3``), the rows collapse to the same
``UniqueKey`` even though their content bodies differ (regular + supplemental
"additional amount" + transferred).

These tests pin the family fix: a post-extraction pass in ``parser.uslm_parser``
groups Division rows by ``(LawIdentifier, DivisionHeadingLevel1,
DivisionHeadingLevel2, DivisionHeadingLevel3)`` in document order and appends
a sequential intra-heading ordinal (" 2", " 3", ...) to the deepest non-null
heading level for the 2nd and subsequent occurrences. The first occurrence is
left untouched so the dominant row retains its original heading text.

The affected examples from vol 78:
  * PL 88-356: two ``<heading>construction</heading>`` blocks under
    ``<heading>National Park Service</heading>`` (level-3 collision).
  * PL 88-356: two ``<heading>administration of territories</heading>`` under
    ``<heading>Office of Territories</heading>`` (level-2 collision).
  * PL 88-390: two ``<heading>Army Security Agency</heading>`` intermediates.
  * PL 88-392: three ``<heading>salaries and expenses</heading>``.
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
    """Build a minimal ``<pLaw>`` whose ``<main>`` body is ``main_inner_xml``."""
    return f"""
      <pLaw>
        <publicPrivate>public</publicPrivate>
        <citableAs>{law_id_human}</citableAs>
        <approvedDate>1964-07-07</approvedDate>
        <officialTitle>Test Appropriations Act</officialTitle>
        <docTitle>{doc_title}</docTitle>
        <main>
          {main_inner_xml}
        </main>
      </pLaw>
    """


def _divisions_for(result, law_id_human):
    """Filter Division rows by LawIdentifier (matching dash variants)."""
    needle_hyphen = law_id_human.replace("–", "-")
    needle_endash = law_id_human.replace("-", "–")
    return [
        r for r in result["Divisions"]
        if r["LawIdentifier"] in (law_id_human, needle_hyphen, needle_endash)
        or law_id_human in r["LawIdentifier"]
    ]


def _heading_path(row):
    """Return ``(L1, L2, L3)`` heading path for a Division row, trimmed."""
    return (
        (row.get("DivisionHeadingLevel1") or "").strip(),
        (row.get("DivisionHeadingLevel2") or "").strip(),
        (row.get("DivisionHeadingLevel3") or "").strip(),
    )


# ---------- Entry #5a: two level-3 sibling <appropriations> with identical heading ----------

def test_entry_5_two_sibling_small_appropriations_get_ordinal_on_level3(tmp_path):
    """PL 88-356 shape: under <heading>National Park Service</heading>, two
    ``<appropriations level="small">`` siblings both have
    ``<heading>construction</heading>``. The extractor emits two Division rows
    whose (L1, L2, L3) path is identical. The post-pass must append " 2" to the
    second row's deepest non-null level (DivisionHeadingLevel3) so the heading
    path is unique while leaving the first row unchanged.
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
            <content>For an additional amount for construction, $5,000,000.</content>
          </appropriations>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-911", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-911")

    assert len(rows) == 2, (
        f"Expected 2 Division rows from sibling <appropriations level='small'>, "
        f"got {len(rows)}: {rows}"
    )

    paths = [_heading_path(r) for r in rows]
    assert len(set(paths)) == 2, (
        f"Sibling-heading collision survived: both rows have identical "
        f"(L1, L2, L3) heading path: {paths}"
    )

    # First row keeps the original heading text.
    assert paths[0][2].lower() == "construction", (
        f"Expected first row's DivisionHeadingLevel3 to stay 'construction', got {paths[0][2]!r}"
    )
    # Second row's level-3 heading is suffixed with an ordinal (e.g. 'construction 2').
    second_l3 = paths[1][2].lower()
    assert second_l3.startswith("construction") and second_l3 != "construction", (
        f"Expected second row's DivisionHeadingLevel3 to have an ordinal suffix, "
        f"got {paths[1][2]!r}"
    )
    assert "2" in second_l3, (
        f"Expected the ordinal '2' in second row's DivisionHeadingLevel3, got {paths[1][2]!r}"
    )


# ---------- Entry #5b: three level-3 siblings; ordinals are 1, 2, 3 in document order ----------

def test_entry_5_three_sibling_appropriations_get_sequential_ordinals(tmp_path):
    """PL 88-392 shape: three ``<heading>salaries and expenses</heading>``
    siblings under the same parent. The first stays untouched; the second gets
    " 2", the third " 3" — sequential in document order.
    """
    main_inner = """
      <appropriations>
        <heading>DEPARTMENT OF THE TREASURY</heading>
        <appropriations>
          <heading>Bureau of the Mint</heading>
          <appropriations level="small">
            <heading>salaries and expenses</heading>
            <content>For salaries and expenses, $4,000,000.</content>
          </appropriations>
          <appropriations level="small">
            <heading>salaries and expenses</heading>
            <content>Additional amount for salaries and expenses, $250,000.</content>
          </appropriations>
          <appropriations level="small">
            <heading>salaries and expenses</heading>
            <content>Transferred amount for salaries and expenses, $100,000.</content>
          </appropriations>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-912", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-912")

    assert len(rows) == 3, f"Expected 3 Division rows, got {len(rows)}: {rows}"

    paths = [_heading_path(r) for r in rows]
    assert len(set(paths)) == 3, (
        f"Expected all 3 (L1, L2, L3) heading paths to be distinct after the "
        f"post-pass, got {paths}"
    )

    l3_values = [p[2].lower() for p in paths]
    # First stays as-is; subsequent rows include the ordinal.
    assert l3_values[0] == "salaries and expenses", l3_values
    assert "2" in l3_values[1] and l3_values[1].startswith("salaries and expenses")
    assert "3" in l3_values[2] and l3_values[2].startswith("salaries and expenses")


# ---------- Entry #5c: level-2 sibling collision (intermediate appropriations) ----------

def test_entry_5_sibling_intermediate_appropriations_get_ordinal_on_level2(tmp_path):
    """PL 88-390 shape: two ``<heading>Army Security Agency</heading>``
    intermediate ``<appropriations>`` elements under the same top-level parent,
    each with their own ``level="small"`` child carrying ``<content>``.

    The extractor produces level-3 rows for these (one per small child), but
    when the level-2 heading collides, the (L1, L2, L3) paths still match.
    The post-pass must disambiguate via the deepest non-null level — here L2 or
    L3, depending on row shape. The test asserts both rows end up with unique
    full (L1, L2, L3) paths.
    """
    main_inner = """
      <appropriations>
        <heading>DEPARTMENT OF THE ARMY</heading>
        <appropriations>
          <heading>Army Security Agency</heading>
          <appropriations level="small">
            <heading>operation and maintenance</heading>
            <content>For O and M of the Army Security Agency, $10,000,000.</content>
          </appropriations>
        </appropriations>
        <appropriations>
          <heading>Army Security Agency</heading>
          <appropriations level="small">
            <heading>operation and maintenance</heading>
            <content>Additional amount, $2,000,000.</content>
          </appropriations>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-913", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-913")

    assert len(rows) == 2, f"Expected 2 Division rows, got {len(rows)}: {rows}"

    paths = [_heading_path(r) for r in rows]
    assert len(set(paths)) == 2, (
        f"Expected sibling Army Security Agency rows to have unique "
        f"(L1, L2, L3) heading paths, got {paths}"
    )


# ---------- Guard: non-colliding sibling headings are NOT modified ----------

def test_sibling_appropriations_with_distinct_headings_are_not_modified(tmp_path):
    """If sibling ``<appropriations>`` already have distinct ``<heading>`` text
    (the normal case), the post-pass must NOT append ordinals — original
    headings flow through verbatim.
    """
    main_inner = """
      <appropriations>
        <heading>DEPARTMENT OF JUSTICE</heading>
        <appropriations>
          <heading>Federal Bureau of Investigation</heading>
          <appropriations level="small">
            <heading>salaries and expenses</heading>
            <content>For FBI S and E, $200,000,000.</content>
          </appropriations>
          <appropriations level="small">
            <heading>buildings and facilities</heading>
            <content>For FBI B and F, $5,000,000.</content>
          </appropriations>
        </appropriations>
      </appropriations>
    """
    plaw_xml = _build_plaw("Public Law 99-914", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _divisions_for(result, "99-914")

    assert len(rows) == 2, f"Expected 2 Division rows, got {len(rows)}: {rows}"

    l3_values = [(r.get("DivisionHeadingLevel3") or "").strip().lower() for r in rows]
    assert l3_values == ["salaries and expenses", "buildings and facilities"], (
        f"Distinct sibling headings must pass through unmodified, got {l3_values}"
    )


# ---------- Guard: distinct LawIdentifiers don't interact across pLaws ----------

def test_sibling_appropriations_grouping_is_scoped_to_one_plaw(tmp_path):
    """Two pLaws with their own sibling-heading collision must each be
    disambiguated independently. A "construction" sibling in pLaw A must not
    cause "construction" in pLaw B to receive an ordinal.
    """
    main_a = """
      <appropriations>
        <heading>National Park Service</heading>
        <appropriations level="small">
          <heading>construction</heading>
          <content>pLaw A first construction block.</content>
        </appropriations>
        <appropriations level="small">
          <heading>construction</heading>
          <content>pLaw A second construction block.</content>
        </appropriations>
      </appropriations>
    """
    main_b = """
      <appropriations>
        <heading>National Park Service</heading>
        <appropriations level="small">
          <heading>construction</heading>
          <content>pLaw B sole construction block.</content>
        </appropriations>
      </appropriations>
    """
    plaw_xml = (
        _build_plaw("Public Law 99-915", main_a)
        + _build_plaw("Public Law 99-916", main_b)
    )
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows_a = _divisions_for(result, "99-915")
    rows_b = _divisions_for(result, "99-916")

    # pLaw A: two rows, second one got an ordinal on its level-2 ('construction').
    assert len(rows_a) == 2, f"pLaw A: expected 2 rows, got {len(rows_a)}: {rows_a}"
    a_paths = [_heading_path(r) for r in rows_a]
    assert len(set(a_paths)) == 2, f"pLaw A heading paths collided: {a_paths}"

    # pLaw B: single 'construction' row, must NOT have been suffixed.
    assert len(rows_b) == 1, f"pLaw B: expected 1 row, got {len(rows_b)}: {rows_b}"
    b_path = _heading_path(rows_b[0])
    # The "construction" heading in pLaw B is the deepest non-null label.
    b_deepest = (
        b_path[2] or b_path[1] or b_path[0]
    ).lower()
    assert b_deepest == "construction", (
        f"pLaw B's lone 'construction' must stay untouched, got {b_deepest!r}"
    )
