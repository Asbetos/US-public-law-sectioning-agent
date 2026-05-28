"""Regression tests for the sibling-level correction family (entry #13).

When a pLaw's ``<main>`` contains a ``<title>`` (or other top-level container)
that holds two or more sibling ``<level>`` elements, each with their own
``<section>`` children, the upstream extractor walks each ``<level>``'s
sections but does NOT capture the ``<level>``'s own ``<heading>`` into any
``UniqueKey``-bearing column. The resulting Section rows share
``(Title, SubTitle, Chapter, SubChapter, SectionNumber)`` across sibling
levels — collapsing to identical ``UniqueKey``.

These tests pin the family fix: a post-extraction pass in
``parser.uslm_parser`` detects sibling-level Section-row groups within a
single pLaw (rows that share container prefix but whose SectionNumber suffix
repeats in document order), and disambiguates the 2nd+ sibling block by
mutating an empty ``UniqueKey``-bearing column (``SubTitle`` preferred, then
``Chapter``, then ``SubChapter``) with a sequential alpha marker ('B', 'C',
...). The first sibling block is left untouched.

The affected example from vol 86:
  * PL 92-351 TITLE IV: two sibling ``<level>`` blocks
    ('General Provisions—General Services Administration' and
    'General Provisions—Civil Defense') each contain Sec. 1 and Sec. 2.
    All four rows currently collapse to two colliding UniqueKey pairs.
"""
import sys
from pathlib import Path

from parser.uslm_parser import extract_public_law_from_uslm

_CODE_DIR = "/home/G39248410/citizen_voice/Code"
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from generate_id_keys import clean_and_format_section_fixed  # noqa: E402


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
        <approvedDate>1972-06-01</approvedDate>
        <officialTitle>Test Sibling-Level Act</officialTitle>
        <docTitle>{doc_title}</docTitle>
        <main>
          {main_inner_xml}
        </main>
      </pLaw>
    """


def _sections_for(result, law_id_human):
    """Filter Section rows by LawIdentifier (matching dash variants)."""
    needle_hyphen = law_id_human.replace("–", "-")
    needle_endash = law_id_human.replace("-", "–")
    return [
        r for r in result["Sections"]
        if r["LawIdentifier"] in (law_id_human, needle_hyphen, needle_endash)
        or law_id_human in r["LawIdentifier"]
    ]


def _key_tuple(row):
    """Return the (Title, SubTitle, Chapter, SubChapter, SectionNumber-suffix)
    tuple that drives the Section row UniqueKey.
    """
    return (
        (row.get("Title") or "").strip(),
        (row.get("SubTitle") or "").strip(),
        (row.get("Chapter") or "").strip(),
        (row.get("SubChapter") or "").strip(),
        clean_and_format_section_fixed(row.get("SectionNumber")),
    )


# ---------- Entry #13: two sibling <level>s under a <title>, each with Sec. 1, Sec. 2 ----------

def test_entry_13_two_sibling_levels_get_distinct_unique_keys(tmp_path):
    """PL 92-351 TITLE IV shape: two sibling ``<level>`` blocks each containing
    their own Sec. 1 and Sec. 2. The four resulting Section rows must produce
    FOUR distinct ``UniqueKey`` tuples after the post-pass.
    """
    main_inner = """
      <title>
        <num value="IV">TITLE IV—</num>
        <heading>GENERAL PROVISIONS</heading>
        <level>
          <heading class="smallCaps centered">General Provisions—General Services Administration</heading>
          <section>
            <num value="1">Sec. 1 </num>
            <content>GSA crediting language.</content>
          </section>
          <section>
            <num value="2">Sec. 2. </num>
            <content>GSA construction language.</content>
          </section>
        </level>
        <level>
          <heading class="smallCaps centered">General Provisions—Civil Defense</heading>
          <section>
            <num value="1">Sec. 1. </num>
            <content>Civil Defense limitation language.</content>
          </section>
          <section>
            <num value="2">Sec. 2. </num>
            <content>Civil Defense warehouse language.</content>
          </section>
        </level>
      </title>
    """
    plaw_xml = _build_plaw("Public Law 99-351", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-351")

    assert len(rows) == 4, f"Expected 4 Section rows, got {len(rows)}: {rows}"

    keys = [_key_tuple(r) for r in rows]
    assert len(set(keys)) == 4, (
        f"Sibling-level UniqueKey collision survived: only "
        f"{len(set(keys))} distinct (Title, SubTitle, Chapter, SubChapter, sec) "
        f"tuples for 4 rows: {keys}"
    )

    # First sibling block (rows 0, 1) should retain the original empty
    # SubTitle so the dominant block's UniqueKey is unchanged.
    assert (rows[0].get("SubTitle") or "") == "", (
        f"First sibling block's SubTitle was unexpectedly mutated: {rows[0]['SubTitle']!r}"
    )
    assert (rows[1].get("SubTitle") or "") == "", (
        f"First sibling block's second row SubTitle was mutated: {rows[1]['SubTitle']!r}"
    )

    # Second sibling block (rows 2, 3) must both share a non-empty SubTitle
    # marker so their (Sec.1, Sec.2) rows do not collide with the first block.
    sub_block2 = [(rows[2].get("SubTitle") or "").strip(), (rows[3].get("SubTitle") or "").strip()]
    assert sub_block2[0] and sub_block2[1], (
        f"Second sibling block's SubTitle was not populated to disambiguate: {sub_block2}"
    )
    assert sub_block2[0] == sub_block2[1], (
        f"Second sibling block's two rows must share the same disambiguation "
        f"marker so they stay grouped, got {sub_block2}"
    )


# ---------- Entry #13b: three sibling <level>s get distinct markers ----------

def test_entry_13_three_sibling_levels_get_sequential_markers(tmp_path):
    """A title with three sibling ``<level>`` blocks, each carrying Sec. 1.
    All three rows must end up with distinct ``UniqueKey`` tuples, and the
    second/third blocks must receive distinct disambiguation markers.
    """
    main_inner = """
      <title>
        <num value="V">TITLE V—</num>
        <heading>MISC PROVISIONS</heading>
        <level>
          <heading>First Provisions</heading>
          <section><num value="1">Sec. 1. </num><content>First block content.</content></section>
        </level>
        <level>
          <heading>Second Provisions</heading>
          <section><num value="1">Sec. 1. </num><content>Second block content.</content></section>
        </level>
        <level>
          <heading>Third Provisions</heading>
          <section><num value="1">Sec. 1. </num><content>Third block content.</content></section>
        </level>
      </title>
    """
    plaw_xml = _build_plaw("Public Law 99-352", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-352")

    assert len(rows) == 3, f"Expected 3 Section rows, got {len(rows)}: {rows}"

    keys = [_key_tuple(r) for r in rows]
    assert len(set(keys)) == 3, (
        f"Expected three distinct UniqueKey tuples after the sibling-level "
        f"post-pass, got {keys}"
    )

    sub_titles = [(r.get("SubTitle") or "").strip() for r in rows]
    # First block stays untouched.
    assert sub_titles[0] == "", f"First block's SubTitle mutated: {sub_titles}"
    # 2nd and 3rd are non-empty and distinct from each other.
    assert sub_titles[1] and sub_titles[2], sub_titles
    assert sub_titles[1] != sub_titles[2], (
        f"2nd and 3rd sibling-level blocks must get distinct markers, got {sub_titles}"
    )


# ---------- Guard: a single <level> under a <title> is NOT touched ----------

def test_single_level_under_title_is_unchanged(tmp_path):
    """When a ``<title>`` has exactly one ``<level>`` child, no collision
    exists and the post-pass must NOT mutate any SubTitle.
    """
    main_inner = """
      <title>
        <num value="I">TITLE I—</num>
        <heading>Sole Title</heading>
        <level>
          <heading>Only Provisions</heading>
          <section><num value="1">Sec. 1. </num><content>Only block content.</content></section>
          <section><num value="2">Sec. 2. </num><content>Second sec.</content></section>
        </level>
      </title>
    """
    plaw_xml = _build_plaw("Public Law 99-353", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-353")

    assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}: {rows}"
    sub_titles = [(r.get("SubTitle") or "").strip() for r in rows]
    assert sub_titles == ["", ""], (
        f"Single-level under title must not have SubTitle mutated, got {sub_titles}"
    )

    # And the two rows have distinct sec numbers, so UniqueKey tuples are unique anyway.
    keys = [_key_tuple(r) for r in rows]
    assert len(set(keys)) == 2, keys


# ---------- Guard: distinct LawIdentifiers don't interact across pLaws ----------

def test_sibling_level_scoped_per_plaw(tmp_path):
    """A sibling-level collision in pLaw A must not cause a single-level pLaw B
    with the same Title and SectionNumber to receive a marker.
    """
    main_a = """
      <title>
        <num value="IV">TITLE IV—</num>
        <heading>Provisions</heading>
        <level>
          <heading>Block A1</heading>
          <section><num value="1">Sec. 1. </num><content>pLaw A block 1.</content></section>
        </level>
        <level>
          <heading>Block A2</heading>
          <section><num value="1">Sec. 1. </num><content>pLaw A block 2.</content></section>
        </level>
      </title>
    """
    main_b = """
      <title>
        <num value="IV">TITLE IV—</num>
        <heading>Provisions</heading>
        <level>
          <heading>Sole Block</heading>
          <section><num value="1">Sec. 1. </num><content>pLaw B sole content.</content></section>
        </level>
      </title>
    """
    plaw_xml = (
        _build_plaw("Public Law 99-354", main_a)
        + _build_plaw("Public Law 99-355", main_b)
    )
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows_a = _sections_for(result, "99-354")
    rows_b = _sections_for(result, "99-355")

    assert len(rows_a) == 2, f"pLaw A: expected 2 rows, got {len(rows_a)}: {rows_a}"
    assert len(rows_b) == 1, f"pLaw B: expected 1 row, got {len(rows_b)}: {rows_b}"

    # pLaw A: second row mutated, first not.
    assert (rows_a[0].get("SubTitle") or "") == ""
    assert (rows_a[1].get("SubTitle") or "") != ""

    # pLaw B: lone row must NOT be mutated.
    assert (rows_b[0].get("SubTitle") or "") == "", (
        f"pLaw B's single block was incorrectly mutated: {rows_b[0]['SubTitle']!r}"
    )


# ---------- Guard: pre-existing distinct sec numbers across blocks are NOT touched ----------

def test_distinct_sec_numbers_across_sibling_levels_unchanged(tmp_path):
    """Two sibling ``<level>`` blocks whose section numbers DON'T overlap
    (e.g. level A has Sec. 1; level B has Sec. 2) produce no UniqueKey
    collision, so the post-pass must leave both blocks' SubTitle empty.
    """
    main_inner = """
      <title>
        <num value="II">TITLE II—</num>
        <heading>Title II</heading>
        <level>
          <heading>Block 1</heading>
          <section><num value="1">Sec. 1. </num><content>Block 1.</content></section>
        </level>
        <level>
          <heading>Block 2</heading>
          <section><num value="2">Sec. 2. </num><content>Block 2.</content></section>
        </level>
      </title>
    """
    plaw_xml = _build_plaw("Public Law 99-356", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-356")

    assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}: {rows}"
    sub_titles = [(r.get("SubTitle") or "").strip() for r in rows]
    assert sub_titles == ["", ""], (
        f"No collision exists; SubTitle must not be mutated, got {sub_titles}"
    )
