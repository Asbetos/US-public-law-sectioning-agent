"""Regression tests for the null-num correction family (entries #2, #14, #15, #16).

When a pLaw contains <section> rows whose section number cannot be extracted
(no <num value=...> directly under <section>), the extractor previously left
SectionNumber=None on every such row. clean_and_format_section_fixed maps None
to the null-fallback suffix '000000000000001' — the same suffix produced by an
explicit '1' / 'Section 1.' / 'Sec. 1.'. Result: multiple rows in the same pLaw
collapse to identical UniqueKey.

These tests pin the family fix: post-process each pLaw's section rows, and
whenever the null rows would cause a UniqueKey collision, rewrite their
SectionNumber field with a synthetic 'U{n}' ordinal in document order.
"""
import tempfile
import textwrap
from pathlib import Path

from parser.uslm_parser import extract_public_law_from_uslm


def _write_uslm_xml(tmp_dir: Path, body_xml: str) -> Path:
    """Wrap a pLaw body fragment in a complete USLM document and write it to disk.

    body_xml is one or more <pLaw>... fragments (NOT wrapped in <main>).
    """
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<uslm xmlns="http://schemas.gpo.gov/xml/uslm">\n'
        f'{body_xml}\n'
        '</uslm>\n'
    )
    xml_path = tmp_dir / "STATUTE-test.xml"
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path


def _build_plaw(law_id_human: str, sections_xml: str, extra_main_xml: str = "") -> str:
    """Build a minimal <pLaw> XML fragment. law_id_human like 'Public Law 87-292'."""
    return f"""
      <pLaw>
        <publicPrivate>public</publicPrivate>
        <citableAs>{law_id_human}</citableAs>
        <approvedDate>1961-09-21</approvedDate>
        <officialTitle>Test Act</officialTitle>
        <docTitle>JOINT RESOLUTION</docTitle>
        <main>
          {sections_xml}
          {extra_main_xml}
        </main>
      </pLaw>
    """


# ---------- Entry #2: two sibling sections both lacking <num> (joint resolution) ----------

def test_entry_2_two_unnumbered_sibling_sections_get_distinct_ordinals(tmp_path):
    """PL 87-292 shape: joint resolution with two sibling <section> elements,
    neither has a <num>. Both must get distinct synthetic SectionNumber values
    so that downstream UniqueKey suffix generation produces unique keys.
    """
    sections = """
      <section class="inline"><content class="inline">First unnumbered section text.</content></section>
      <section class="inline"><content class="inline">Second unnumbered section text.</content></section>
    """
    plaw_xml = _build_plaw("Public Law 99-901", sections)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections_out = [r for r in result["Sections"] if r["LawIdentifier"].endswith("99–901") or r["LawIdentifier"].endswith("99-901")]

    assert len(sections_out) == 2, f"Expected 2 section rows, got {len(sections_out)}"
    section_numbers = [r["SectionNumber"] for r in sections_out]
    # Neither should be None (the post-pass must have assigned synthetic ordinals)
    assert None not in section_numbers, f"Null SectionNumber survived: {section_numbers}"
    # They must be distinct
    assert len(set(section_numbers)) == 2, f"SectionNumbers collide: {section_numbers}"


# ---------- Entry #14: null section + explicit <num value="1"> in same pLaw ----------

def test_entry_14_null_section_with_explicit_section_1_does_not_collide(tmp_path):
    """PL 92-344 shape: an enacting <section class="inline"> with no <num>,
    followed by a <section><num value="1">Section 1.</num>... in the same pLaw.

    Active correction #2 alone would assign ordinal '1' to the null row, but the
    explicit Section 1 already occupies position '1' — collision. The fix must
    place null-section ordinals in a namespace that cannot collide with explicit
    section numbers (e.g. 'U' prefix).
    """
    sections = """
      <section class="inline"><content class="inline">That the following sums are appropriated, namely:</content></section>
      <section class="firstIndent1 fontsize10">
        <num value="1"><inline class="smallCaps">Section</inline> 1. </num>
        <content>Except as otherwise provided herein, all vouchers shall be audited.</content>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 99-902", sections)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections_out = [r for r in result["Sections"] if "99" in r["LawIdentifier"] and "902" in r["LawIdentifier"]]

    assert len(sections_out) == 2

    # Simulate the suffix portion of UniqueKey that generate_id_keys.py would produce.
    from generate_id_keys import clean_and_format_section_fixed
    suffixes = [clean_and_format_section_fixed(r.get("SectionNumber")) for r in sections_out]

    # No suffix collision between the null row and the explicit "Section 1." row.
    assert len(set(suffixes)) == 2, f"UniqueKey suffix collision: {suffixes}, SectionNumbers={[r['SectionNumber'] for r in sections_out]}"


# ---------- Entry #15: unnumbered opening 'That ...' + later 'Sec. 1.' ----------

def test_entry_15_unnumbered_opening_does_not_collide_with_later_sec_1(tmp_path):
    """PL 93-91 shape: opening <section class="inline"> with 'That...' content
    (no <num>) followed downstream by a numbered <section><num>Sec. 1.</num>.
    'Sec. 1.' also maps to the null-fallback suffix '000000000000001' via
    clean_and_format_section_fixed — so the null row and the 'Sec. 1.' row must
    not collapse to the same UniqueKey.
    """
    sections = """
      <section class="inline"><content class="inline">That the following sums are appropriated, namely:</content></section>
      <section class="firstIndent1 fontsize10">
        <num class="smallCaps" value="1">Sec. 1. </num>
        <content class="inline">Except as otherwise provided herein, all vouchers shall be audited.</content>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 99-903", sections)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections_out = [r for r in result["Sections"] if "99" in r["LawIdentifier"] and "903" in r["LawIdentifier"]]

    assert len(sections_out) == 2

    from generate_id_keys import clean_and_format_section_fixed
    suffixes = [clean_and_format_section_fixed(r.get("SectionNumber")) for r in sections_out]
    assert len(set(suffixes)) == 2, (
        f"UniqueKey suffix collision: {suffixes}, "
        f"SectionNumbers={[r['SectionNumber'] for r in sections_out]}"
    )


# ---------- Entry #16: vol 88 outer-section-wraps-inner-numbered-section ----------

def test_entry_16_outer_sections_wrap_inner_numbered_sections_get_distinct_keys(tmp_path):
    """PL 93-275 / vol-88 dominant shape: multiple outer <section> wrappers,
    each holds a <heading> and a single inner numbered <section>. The outer
    section has no direct <num>, so the extractor sees SectionNumber=None.
    Multiple such outer wrappers must NOT collapse to the same UniqueKey.
    """
    sections = """
      <section>
        <heading class="smallCaps centered">short title</heading>
        <section class="firstIndent1 fontsize10">
          <num value="1"><inline class="smallCaps">Section</inline> 1. </num>
          <content>This Act may be cited as the "Test Act of 1974".</content>
        </section>
      </section>
      <section>
        <heading class="smallCaps centered">findings and purpose</heading>
        <section class="firstIndent1 fontsize10">
          <num value="2"><inline class="smallCaps">Section</inline> 2. </num>
          <content>The Congress finds and declares the following.</content>
        </section>
      </section>
      <section>
        <heading class="smallCaps centered">definitions</heading>
        <section class="firstIndent1 fontsize10">
          <num value="3"><inline class="smallCaps">Section</inline> 3. </num>
          <content>For purposes of this Act, the following definitions apply.</content>
        </section>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 99-904", sections)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections_out = [r for r in result["Sections"] if "99" in r["LawIdentifier"] and "904" in r["LawIdentifier"]]

    assert len(sections_out) == 3, f"Expected 3 outer-section rows, got {len(sections_out)}"

    from generate_id_keys import clean_and_format_section_fixed
    suffixes = [clean_and_format_section_fixed(r.get("SectionNumber")) for r in sections_out]
    assert len(set(suffixes)) == 3, (
        f"UniqueKey suffix collision: {suffixes}, "
        f"SectionNumbers={[r['SectionNumber'] for r in sections_out]}"
    )
    # And no row should still have null SectionNumber
    for r in sections_out:
        assert r["SectionNumber"] is not None, (
            f"Null SectionNumber survived for outer-section row: {r}"
        )


# ---------- Guard: single null section in a pLaw should not be touched ----------

def test_single_null_section_is_not_renumbered(tmp_path):
    """When a pLaw has exactly one section and it has no <num>, the null
    SectionNumber does not collide with anything in that pLaw, so the post-pass
    must NOT rewrite it (preserves existing behavior for single-section pLaws).
    """
    sections = """
      <section class="inline"><content class="inline">A standalone resolution body.</content></section>
    """
    plaw_xml = _build_plaw("Public Law 99-905", sections)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections_out = [r for r in result["Sections"] if "99" in r["LawIdentifier"] and "905" in r["LawIdentifier"]]

    assert len(sections_out) == 1
    # No collision risk → SectionNumber stays None
    assert sections_out[0]["SectionNumber"] is None


# ---------- Guard: pLaws with all explicit nums are unchanged ----------

def test_fully_numbered_pLaw_section_numbers_unchanged(tmp_path):
    """When all sections have explicit <num>, the post-pass must not alter any
    SectionNumber value.
    """
    sections = """
      <section>
        <num value="1">Section 1. </num>
        <content>First section content.</content>
      </section>
      <section>
        <num value="2">Section 2. </num>
        <content>Second section content.</content>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 99-906", sections)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections_out = [r for r in result["Sections"] if "99" in r["LawIdentifier"] and "906" in r["LawIdentifier"]]

    assert len(sections_out) == 2
    sn = [r["SectionNumber"] for r in sections_out]
    # Both retain their explicit text; neither becomes a synthetic 'U...'
    assert all(s is not None for s in sn)
    assert not any(str(s).startswith("U") for s in sn), f"Explicit section numbers were rewritten: {sn}"
