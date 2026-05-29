"""Regression tests for top-level-container recovery EXTENSION (entry #25).

This extends the recovery pass for two new ``<main>`` shapes observed in vol 88
that were silently dropped by the previous recovery family (#3, #7, #11, #17):

Shape (a) — joint-resolution "policy" shape (PL 93-513, vol 88):
  ``<main>`` contains ``<longTitle>``, ``<preamble>``/``<resolvingClause>``,
  a bare ``<p class="inline">That ...</p>`` operative paragraph, and
  ``<action>``. No ``<section>``, ``<part>``, ``<title>``, ``<chapter>``,
  ``<subsection>``, or ``<quotedContent>`` anywhere. Recovery must synthesize
  ONE section row whose ``Text`` is the operative paragraph's text.

Shape (b) — supplemental-appropriations joint-resolution shape (PL 93-624, vol 88):
  ``<main>`` contains multiple ``<chapter>`` children, each holding ONLY
  ``<appropriations>`` (with no nested ``<section>``). The existing recursive
  walker descends into ``<chapter>`` looking for ``<section>``, finds none,
  and emits 0 rows. Recovery must synthesize at least one section row per
  ``<chapter>`` carrying the chapter heading and the appropriations text.
"""
from pathlib import Path

from parser.uslm_parser import extract_public_law_from_uslm


def _write_uslm_xml(tmp_dir: Path, body_xml: str) -> Path:
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<uslm xmlns="http://schemas.gpo.gov/xml/uslm">\n'
        f'{body_xml}\n'
        '</uslm>\n'
    )
    xml_path = tmp_dir / "STATUTE-test.xml"
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path


def _build_plaw(law_id_human: str, main_inner_xml: str, doc_title: str = "JOINT RESOLUTION") -> str:
    return f"""
      <pLaw>
        <publicPrivate>public</publicPrivate>
        <citableAs>{law_id_human}</citableAs>
        <approvedDate>1974-12-06</approvedDate>
        <officialTitle>Test Joint Resolution</officialTitle>
        <docTitle>{doc_title}</docTitle>
        <main>
          {main_inner_xml}
        </main>
      </pLaw>
    """


def _sections_for(result, law_id_human):
    needle_hyphen = law_id_human.replace("–", "-")
    needle_endash = law_id_human.replace("-", "–")
    return [
        r for r in result["Sections"]
        if r["LawIdentifier"] in (law_id_human, needle_hyphen, needle_endash)
        or law_id_human in r["LawIdentifier"]
    ]


def _divisions_for(result, law_id_human):
    needle_hyphen = law_id_human.replace("–", "-")
    needle_endash = law_id_human.replace("-", "–")
    return [
        r for r in result["Divisions"]
        if r["LawIdentifier"] in (law_id_human, needle_hyphen, needle_endash)
        or law_id_human in r["LawIdentifier"]
    ]


# ---------- Entry #25 shape (a): bare <p> operative paragraph (PL 93-513) ----------

def test_entry_25a_main_with_bare_p_operative_paragraph_synthesizes_single_section(tmp_path):
    """PL 93-513 shape: joint-resolution policy shape. ``<main>`` contains
    ``<longTitle>``, ``<preamble>``, ``<resolvingClause>``, a bare
    ``<p class="inline">That ...</p>`` operative paragraph, and ``<action>``.
    No recognized container of any kind. Recovery must synthesize ONE section
    row carrying the operative paragraph text.
    """
    main_inner = """
      <longTitle>Joint resolution relating to nuclear warship visits</longTitle>
      <preamble>Whereas the United States has nuclear warships ...</preamble>
      <resolvingClause>Resolved by the Senate and House of Representatives ...</resolvingClause>
      <p class="inline">That it is the policy of the United States that it will pay claims or judgments for bodily injury, death, or damage to or loss of real or personal property proven to have resulted from a nuclear incident involving the nuclear reactor of a United States warship.</p>
      <action><actionDescription>Approved December 6, 1974.</actionDescription></action>
    """
    plaw_xml = _build_plaw("Public Law 99-913", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-913")

    assert len(rows) >= 1, (
        f"Expected >=1 synthesized section row from bare <p> operative paragraph, "
        f"got {len(rows)}: {rows}"
    )
    text = rows[0]["Text"] or ""
    assert "policy of the United States" in text or "nuclear" in text.lower(), (
        f"Expected operative paragraph text in Text field, got {text!r}"
    )


def test_entry_25a_with_content_element_instead_of_p(tmp_path):
    """Variant where the operative body is held in a bare ``<content>`` element
    directly under ``<main>`` (no ``<p>``)."""
    main_inner = """
      <longTitle>Joint resolution</longTitle>
      <resolvingClause>Resolved by the Senate and House ...</resolvingClause>
      <content>That the Secretary of the Navy is authorized to do various things.</content>
      <action><actionDescription>Approved.</actionDescription></action>
    """
    plaw_xml = _build_plaw("Public Law 99-914", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-914")

    assert len(rows) >= 1, (
        f"Expected >=1 synthesized section row from bare <content>, got {len(rows)}: {rows}"
    )
    text = rows[0]["Text"] or ""
    assert "Secretary of the Navy" in text, (
        f"Expected <content> text in Text field, got {text!r}"
    )


# ---------- Entry #25 shape (b): <chapter> with only <appropriations> (PL 93-624) ----------

def test_entry_25b_main_with_chapter_only_appropriations_emits_row_per_chapter(tmp_path):
    """PL 93-624 shape: supplemental appropriations joint resolution. ``<main>``
    has multiple ``<chapter>`` children, each containing ONLY
    ``<appropriations>`` (no nested ``<section>``). The existing recursive
    walker descends into ``<chapter>``, finds no ``<section>``, and emits 0
    rows. Recovery must synthesize at least one section row per chapter so
    the pLaw is not silently dropped.
    """
    main_inner = """
      <longTitle>Joint resolution making further urgent supplemental appropriations</longTitle>
      <resolvingClause>Resolved by the Senate and House of Representatives ...</resolvingClause>
      <chapter>
        <num value="I">CHAPTER I</num>
        <heading class="centered">DEPARTMENT OF LABOR</heading>
        <appropriations level="intermediate">
          <heading>Manpower Administration</heading>
          <appropriations level="small">
            <heading>program administration</heading>
            <content class="firstIndent1">For an additional amount for "Program administration", $500,000.</content>
          </appropriations>
        </appropriations>
      </chapter>
      <chapter>
        <num value="II">CHAPTER II</num>
        <heading class="centered">DEPARTMENT OF DEFENSE</heading>
        <appropriations level="intermediate">
          <heading>Operation and Maintenance</heading>
          <content class="firstIndent1">For an additional amount for operations, $1,000,000.</content>
        </appropriations>
      </chapter>
    """
    plaw_xml = _build_plaw("Public Law 99-915", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    sections = _sections_for(result, "99-915")
    divisions = _divisions_for(result, "99-915")

    # Recovery should emit at least one row per chapter (either as Sections
    # rows or Division rows). The simplest acceptable outcome is one Sections
    # row per chapter carrying the chapter heading on DivisionHeadingLevel1.
    total_rows = len(sections) + len(divisions)
    assert total_rows >= 2, (
        f"Expected >=2 rows (one per chapter) but got {total_rows}: "
        f"sections={sections}, divisions={divisions}"
    )

    # The chapter headings must surface somewhere — on DivisionHeadingLevel1
    # of a Sections row or on a Division row.
    combined = sections + divisions
    div1_blob = " | ".join((r.get("DivisionHeadingLevel1") or "") for r in combined).upper()
    text_blob = " | ".join((r.get("Text") or "") for r in combined).upper()
    assert "LABOR" in div1_blob or "LABOR" in text_blob or "CHAPTER I" in div1_blob, (
        f"Expected CHAPTER I / Department of Labor signal in recovered rows, "
        f"got div1={div1_blob!r}, text={text_blob!r}"
    )
    assert "DEFENSE" in div1_blob or "DEFENSE" in text_blob or "CHAPTER II" in div1_blob, (
        f"Expected CHAPTER II / Department of Defense signal in recovered rows, "
        f"got div1={div1_blob!r}, text={text_blob!r}"
    )


# ---------- Guard: well-formed pLaws are NOT touched by the new fallback ----------

def test_recovery_extension_does_not_synthesize_for_normal_pLaw(tmp_path):
    """A pLaw whose ``<main>`` has direct ``<section>`` children must NOT
    receive an extra synthesized row from the new bare-``<p>`` fallback.
    """
    main_inner = """
      <section>
        <num value="1">Sec. 1. </num>
        <content>Normal section content.</content>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 99-916", main_inner, doc_title="AN ACT")
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=99)
    rows = _sections_for(result, "99-916")

    assert len(rows) == 1, (
        f"Expected exactly 1 row from upstream walker (no fallback duplication), "
        f"got {len(rows)}: {rows}"
    )
