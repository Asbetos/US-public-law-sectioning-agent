"""Regression tests for the top-level-container correction family (entries #3, #7, #11, #17).

A pLaw whose ``<main>`` has zero top-level ``<section>`` children — only different
kinds of container elements (``<part>``, ``<title>`` with nested ``<part>``,
``<chapter>``, bare ``<subsection>``, or ``<quotedContent>``) — is silently
DROPPED by the upstream section walker (0 rows emitted). This means the volume's
distinct ``LawIdentifier`` count falls below the public-pLaw count in the XML.

These tests pin the family fix: a post-extraction pass in ``parser.uslm_parser``
detects dropped pLaws and synthesizes section rows by walking the container(s)
under ``<main>``. Container headings are carried into the ``DivisionHeadingLevel``
columns when present.

The four family members:
  * #3a — ``<main>`` contains ``<part>`` elements directly (multi-part Act).
  * #3b — ``<main>`` contains bare ``<subsection>`` elements (short amending Act).
  * #7  — ``<main>`` contains ``<title>`` elements whose body is ``<part>``
          containers (CIA Retirement Act shape; ``<title><part><section>``).
  * #11 — ``<main>`` contains ``<chapter>`` elements directly.
  * #17 — ``<main>`` contains ``<quotedContent>`` directly as its body holder.
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
        <approvedDate>1961-09-21</approvedDate>
        <officialTitle>Test Act</officialTitle>
        <docTitle>{doc_title}</docTitle>
        <main>
          {main_inner_xml}
        </main>
      </pLaw>
    """


def _sections_for(result, law_id_human):
    """Filter section rows by law_identifier (matching the 87-195 / 87–195 dash variants)."""
    needle_hyphen = law_id_human.replace("–", "-")
    needle_endash = law_id_human.replace("-", "–")
    return [
        r for r in result["Sections"]
        if r["LawIdentifier"] in (law_id_human, needle_hyphen, needle_endash)
        or law_id_human in r["LawIdentifier"]
    ]


# ---------- Entry #3a: <main> contains <part> elements directly (multi-part Act) ----------

def test_entry_3a_main_with_part_containers_emits_section_per_part(tmp_path):
    """PL 87-195 / PL 87-328 shape: multi-part Act. ``<main>`` has only ``<part>``
    children (no top-level ``<section>``), and each part contains ``<section>``
    children. Walker must emit one row per section, carrying the part heading
    into ``DivisionHeadingLevel1``.
    """
    main_inner = """
      <longTitle>Foreign Assistance Act of 1961</longTitle>
      <enactingFormula>Be it enacted...</enactingFormula>
      <part>
        <num value="1">PART I—</num>
        <heading>POLICY</heading>
        <section>
          <num value="101">Sec. 101. </num>
          <heading>statement of policy</heading>
          <content>It is the sense of the Congress that...</content>
        </section>
        <section>
          <num value="102">Sec. 102. </num>
          <heading>declaration of policy</heading>
          <content>The Congress declares...</content>
        </section>
      </part>
      <part>
        <num value="2">PART II—</num>
        <heading>MILITARY ASSISTANCE</heading>
        <section>
          <num value="201">Sec. 201. </num>
          <heading>authorization</heading>
          <content>The President is authorized...</content>
        </section>
      </part>
    """
    plaw_xml = _build_plaw("Public Law 99-901", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-901")

    assert len(rows) == 3, (
        f"Expected 3 section rows (one per <section> under <part>), got {len(rows)}: {rows}"
    )

    # Section numbers come through (extracted from <num>)
    section_numbers = [r["SectionNumber"] for r in rows]
    assert "101" in str(section_numbers[0])
    assert "102" in str(section_numbers[1])
    assert "201" in str(section_numbers[2])

    # Part heading is carried into DivisionHeadingLevel1.
    div1_first = rows[0]["DivisionHeadingLevel1"] or ""
    assert "POLICY" in div1_first.upper() or "PART I" in div1_first.upper(), (
        f"Expected part label in DivisionHeadingLevel1, got {div1_first!r}"
    )
    div1_third = rows[2]["DivisionHeadingLevel1"] or ""
    assert "MILITARY" in div1_third.upper() or "PART II" in div1_third.upper(), (
        f"Expected Part II label in DivisionHeadingLevel1, got {div1_third!r}"
    )


# ---------- Entry #3b: <main> contains bare <subsection> elements (short amending Act) ----------

def test_entry_3b_main_with_bare_subsections_synthesizes_single_section(tmp_path):
    """PL 87-397 shape: short single-section amending Act with no ``<section>``
    wrapper. ``<main>`` directly contains ``<subsection>`` elements (a, b, c, d).
    Walker must synthesize ONE section row carrying the concatenated subsection
    text.
    """
    main_inner = """
      <longTitle>To amend the Internal Revenue Code identifying-numbers provisions</longTitle>
      <enactingFormula>Be it enacted...</enactingFormula>
      <subsection>
        <num value="a">(a) </num>
        <content>Subsection (a) of section 6109 is amended by striking ...</content>
      </subsection>
      <subsection>
        <num value="b">(b) </num>
        <content>Subsection (b) is amended by inserting ...</content>
      </subsection>
      <subsection>
        <num value="c">(c) </num>
        <content>Subsection (c) is amended by adding ...</content>
      </subsection>
    """
    plaw_xml = _build_plaw("Public Law 99-902", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-902")

    assert len(rows) == 1, f"Expected exactly 1 synthesized section row, got {len(rows)}: {rows}"
    text = rows[0]["Text"] or ""
    assert "Subsection (a)" in text or "amended" in text, (
        f"Expected concatenated subsection text in Text field, got {text!r}"
    )


# ---------- Entry #7: <main> contains <title> with nested <part> (CIA Retirement Act) ----------

def test_entry_7_main_with_title_part_section_emits_row_per_section(tmp_path):
    """PL 88-643 shape: CIA Retirement Act. ``<main>`` has two ``<title>``
    elements; each ``<title>`` contains ``<part>`` elements; each ``<part>``
    contains ``<section>`` children. Walker must emit one row per section,
    carrying the title heading into ``DivisionHeadingLevel1`` and the part
    heading into ``DivisionHeadingLevel2``.

    The upstream extractor already handles ``<main><title><section>`` and
    ``<main><title><chapter><section>``, but NOT ``<main><title><part><section>``,
    which is the actual PL 88-643 structure — the post-pass must cover it.
    """
    main_inner = """
      <longTitle>CIA Retirement Act</longTitle>
      <enactingFormula>Be it enacted...</enactingFormula>
      <title>
        <num value="1">TITLE I—</num>
        <heading>DEFINITIONS</heading>
        <part>
          <num value="A">PART A—</num>
          <heading>SHORT TITLE</heading>
          <section>
            <num value="101">Sec. 101. </num>
            <heading>short title</heading>
            <content>This Act may be cited as ...</content>
          </section>
          <section>
            <num value="102">Sec. 102. </num>
            <heading>definitions</heading>
            <content>For purposes of this Act ...</content>
          </section>
        </part>
      </title>
      <title>
        <num value="2">TITLE II—</num>
        <heading>ESTABLISHMENT OF SYSTEM</heading>
        <part>
          <num value="A">PART A—</num>
          <heading>ELIGIBILITY</heading>
          <section>
            <num value="201">Sec. 201. </num>
            <heading>eligibility</heading>
            <content>Eligibility is established ...</content>
          </section>
        </part>
      </title>
    """
    plaw_xml = _build_plaw("Public Law 99-903", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-903")

    assert len(rows) == 3, (
        f"Expected 3 section rows (title>part>section walked), got {len(rows)}: {rows}"
    )

    # Title heading on DivisionHeadingLevel1.
    div1_first = rows[0]["DivisionHeadingLevel1"] or ""
    assert "DEFINITIONS" in div1_first.upper() or "TITLE I" in div1_first.upper(), (
        f"Expected title heading in DivisionHeadingLevel1, got {div1_first!r}"
    )

    # Part heading on DivisionHeadingLevel2.
    div2_first = rows[0]["DivisionHeadingLevel2"] or ""
    assert "SHORT TITLE" in div2_first.upper() or "PART A" in div2_first.upper(), (
        f"Expected part heading in DivisionHeadingLevel2, got {div2_first!r}"
    )

    # Title II row.
    div1_last = rows[-1]["DivisionHeadingLevel1"] or ""
    assert "ESTABLISHMENT" in div1_last.upper() or "TITLE II" in div1_last.upper(), (
        f"Expected TITLE II label on last row's DivisionHeadingLevel1, got {div1_last!r}"
    )


# ---------- Entry #11: <main> contains <chapter> elements directly ----------

def test_entry_11_main_with_chapter_containers_emits_row_per_section(tmp_path):
    """PL 91-599 shape: International Financial Institutions Act. ``<main>``
    has five ``<chapter>`` children, each containing ``<section>`` rows. Walker
    must emit one row per section, carrying the chapter heading into
    ``DivisionHeadingLevel1``.
    """
    main_inner = """
      <longTitle>International Financial Institutions Act</longTitle>
      <enactingFormula>Be it enacted...</enactingFormula>
      <chapter>
        <num value="1">Chapter 1—</num>
        <heading>INTERNATIONAL MONETARY FUND</heading>
        <section>
          <num value="11">Sec. 11. </num>
          <content>The IMF subscription ...</content>
        </section>
      </chapter>
      <chapter>
        <num value="2">Chapter 2—</num>
        <heading>INTER-AMERICAN DEVELOPMENT BANK</heading>
        <section>
          <num value="21">Sec. 21. </num>
          <content>IADB participation ...</content>
        </section>
        <section>
          <num value="22">Sec. 22. </num>
          <content>IADB authorization ...</content>
        </section>
      </chapter>
    """
    plaw_xml = _build_plaw("Public Law 99-904", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-904")

    assert len(rows) == 3, (
        f"Expected 3 section rows (one per <section> under <chapter>), got {len(rows)}: {rows}"
    )

    # Chapter heading is carried into DivisionHeadingLevel1.
    div1_first = rows[0]["DivisionHeadingLevel1"] or ""
    assert "MONETARY" in div1_first.upper() or "CHAPTER 1" in div1_first.upper(), (
        f"Expected Chapter 1 label in DivisionHeadingLevel1, got {div1_first!r}"
    )
    div1_third = rows[2]["DivisionHeadingLevel1"] or ""
    assert "INTER-AMERICAN" in div1_third.upper() or "CHAPTER 2" in div1_third.upper(), (
        f"Expected Chapter 2 label in DivisionHeadingLevel1 on third row, got {div1_third!r}"
    )


# ---------- Entry #17: <main> contains <quotedContent> directly (joint resolution) ----------

def test_entry_17_main_with_quoted_content_synthesizes_single_section(tmp_path):
    """PL 94-7 shape: joint resolution amending another Act by quoting the
    amendatory text directly under ``<main>``. ``<main>`` has ``<longTitle>``,
    ``<resolvingClause>``, ``<quotedContent>``, ``<action>`` — no ``<section>``,
    no ``<part>``, no ``<title>``, no bare ``<subsection>``. Walker must
    synthesize ONE section row carrying the quotedContent text.
    """
    main_inner = """
      <longTitle><docTitle>Joint Resolution</docTitle>
        <officialTitle>Making further continuing appropriations for the fiscal year 1975</officialTitle>
      </longTitle>
      <resolvingClause>Resolved by the Senate and House of Representatives ...</resolvingClause>
      <quotedContent>
        <content>That clause (c) of section 102 of the joint resolution of June 30, 1974 is hereby further amended by striking out "February 28, 1975" and inserting in lieu thereof "June 30, 1975".</content>
      </quotedContent>
      <action><actionDescription>Approved March 14, 1975.</actionDescription></action>
    """
    plaw_xml = _build_plaw("Public Law 99-905", main_inner, doc_title="JOINT RESOLUTION")
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-905")

    assert len(rows) == 1, (
        f"Expected 1 synthesized section row from <quotedContent>, got {len(rows)}: {rows}"
    )
    text = rows[0]["Text"] or ""
    assert "amended" in text.lower() or "february" in text.lower() or "1975" in text, (
        f"Expected quoted amendatory text in Text field, got {text!r}"
    )


# ---------- Guards: existing well-formed pLaws are not double-counted by the post-pass ----------

def test_recovery_pass_does_not_duplicate_existing_section_rows(tmp_path):
    """A pLaw whose ``<main>`` has direct ``<section>`` children (the normal
    case) must NOT be re-walked by the recovery pass — otherwise sections would
    be doubled.
    """
    main_inner = """
      <section>
        <num value="1">Sec. 1. </num>
        <content>Normal section content.</content>
      </section>
      <section>
        <num value="2">Sec. 2. </num>
        <content>Second normal section.</content>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 99-906", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-906")

    assert len(rows) == 2, f"Expected exactly 2 rows (no duplication), got {len(rows)}: {rows}"


def test_recovery_pass_skips_pLaw_whose_title_walker_already_emitted_rows(tmp_path):
    """The upstream walker handles ``<main><title><section>`` directly. The
    recovery pass must not re-walk that pLaw and double-count.
    """
    main_inner = """
      <title>
        <num value="1">TITLE I—</num>
        <heading>POLICY</heading>
        <section>
          <num value="1">Sec. 1. </num>
          <content>Policy text.</content>
        </section>
      </title>
    """
    plaw_xml = _build_plaw("Public Law 99-907", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-907")

    # The upstream title walker emits 1 row; recovery pass must not add a second.
    assert len(rows) == 1, (
        f"Expected exactly 1 row from upstream title walker (no recovery duplication), "
        f"got {len(rows)}: {rows}"
    )
