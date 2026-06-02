"""Regression tests for the malformed-law-id correction family (entry #41).

Volumes 105 and 108 fail the validator rule "LawIdentifier values without
recognizable pattern" because corrupt source ``<citableAs>`` text produces
malformed ``LawIdentifier`` values. Two corruption shapes are observed:

  * vol 105 — ``<citableAs>`` is ``"Public Law 102–v"`` (the public-law
    NUMBER is the literal token ``v``). The upstream extractor's "v"-branch
    rebuilds from ``<docNumber>`` alone but omits ``<congress>``, yielding a
    bare ``"Public Law 23"``. Correct id: ``"Public Law 102-23"``.

  * vol 108 — ``<citableAs>`` is ``"Public Law 103ߝ399"`` where the
    congress/number separator is a corrupt non-dash character U+07DD. The
    extractor passes it through verbatim, yielding ``"Public Law 103ߝ399"``.
    Correct id: ``"Public Law 103-399"``.

The family fix is a post-extraction pass in ``parser.uslm_parser``: after raw
extraction, for every PUBLIC-law row whose ``LawIdentifier`` does NOT match the
canonical regex ``r'Public Law \\d+[-–—]\\d+'``, re-derive it from the
authoritative ``<docNumber>`` and ``<congress>`` of that pLaw as
``"Public Law {congress}-{docNumber}"`` (re-parsing the source XML to build the
docNumber+congress map). Authoritative metadata is preferred over attempting to
repair the corrupt ``citableAs`` text.
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


def _build_plaw(citable_as: str, doc_number: str, congress: str,
                main_inner_xml: str, doc_title: str = "AN ACT") -> str:
    """Build a minimal modern (vol > 63) ``<pLaw>`` carrying a corrupt
    ``<citableAs>`` plus the authoritative ``<docNumber>`` / ``<congress>``.
    """
    return f"""
      <pLaw>
        <publicPrivate>public</publicPrivate>
        <docNumber>{doc_number}</docNumber>
        <congress>{congress}</congress>
        <citableAs>{citable_as}</citableAs>
        <approvedDate>1991-05-10</approvedDate>
        <officialTitle>Test Act</officialTitle>
        <docTitle>{doc_title}</docTitle>
        <main>
          {main_inner_xml}
        </main>
      </pLaw>
    """


_SIMPLE_MAIN = """
  <section>
    <num value="1">Sec. 1. </num>
    <heading>short title</heading>
    <content>This Act may be cited as the Test Act.</content>
  </section>
"""


# ---------- vol 105 shape: <citableAs>Public Law 102–v</citableAs> ----------

def test_vol105_v_token_citableAs_rebuilds_with_congress_prefix(tmp_path):
    """vol 105 shape (a): ``<citableAs>`` is ``"Public Law 102–v"`` and the
    authoritative ``<docNumber>`` is ``23`` / ``<congress>`` is ``102``. The
    upstream "v"-branch rebuilds a bare ``"Public Law 23"`` (congress dropped).
    The post-pass must re-derive the canonical ``"Public Law 102-23"``.
    """
    plaw_xml = _build_plaw("Public Law 102–v", "23", "102", _SIMPLE_MAIN)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=105)
    law_ids = {r["LawIdentifier"] for r in result["Sections"]}

    assert law_ids == {"Public Law 102-23"}, (
        f"Expected the malformed bare 'Public Law 23' to be re-derived as "
        f"'Public Law 102-23', got {law_ids}"
    )


def test_vol105_v_token_last_docnumber_in_range(tmp_path):
    """vol 105 shape (a), high docNumber end of the affected range: docNumber
    ``49`` / congress ``102`` must produce ``"Public Law 102-49"``.
    """
    plaw_xml = _build_plaw("Public Law 102–v", "49", "102", _SIMPLE_MAIN)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=105)
    law_ids = {r["LawIdentifier"] for r in result["Sections"]}

    assert law_ids == {"Public Law 102-49"}, (
        f"Expected 'Public Law 102-49', got {law_ids}"
    )


def test_vol105_multiple_v_token_plaws_get_distinct_correct_ids(tmp_path):
    """vol 105 has 18 such pLaws; each shares the corrupt 'Public Law 102–v'
    citableAs but carries a distinct authoritative docNumber. The post-pass must
    map each to its own canonical id (no collapse to a single id).
    """
    plaw_xml = (
        _build_plaw("Public Law 102–v", "23", "102", _SIMPLE_MAIN)
        + _build_plaw("Public Law 102–v", "24", "102", _SIMPLE_MAIN)
        + _build_plaw("Public Law 102–v", "49", "102", _SIMPLE_MAIN)
    )
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=105)
    law_ids = {r["LawIdentifier"] for r in result["Sections"]}

    assert law_ids == {"Public Law 102-23", "Public Law 102-24", "Public Law 102-49"}, (
        f"Expected three distinct canonical ids, got {law_ids}"
    )


# ---------- vol 108 shape: <citableAs>Public Law 103ߝ399</citableAs> (U+07DD) ----------

def test_vol108_corrupt_separator_citableAs_normalized_to_dash(tmp_path):
    """vol 108 shape (b): ``<citableAs>`` is ``"Public Law 103ߝ399"`` where
    the congress/number separator is the corrupt non-dash character U+07DD. The
    extractor passes it through verbatim. The post-pass must re-derive the
    canonical ``"Public Law 103-399"`` from docNumber ``399`` / congress ``103``.
    """
    main_inner = """
      <section>
        <num value="1">Sec. 1. </num>
        <content>First section.</content>
      </section>
      <section>
        <num value="2">Sec. 2. </num>
        <content>Second section.</content>
      </section>
    """
    plaw_xml = _build_plaw("Public Law 103ߝ399", "399", "103", main_inner)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=108)
    law_ids = {r["LawIdentifier"] for r in result["Sections"]}

    assert law_ids == {"Public Law 103-399"}, (
        f"Expected the corrupt 'Public Law 103ߝ399' to be re-derived as "
        f"'Public Law 103-399', got {law_ids}"
    )
    # No row may retain the corrupt U+07DD character.
    assert all("ߝ" not in (r["LawIdentifier"] or "") for r in result["Sections"]), (
        "No section row may retain the corrupt U+07DD separator"
    )


# ---------- Guard: well-formed law-ids are left untouched ----------

def test_well_formed_law_id_is_not_rewritten(tmp_path):
    """A pLaw whose ``<citableAs>`` already produces a canonical
    ``"Public Law N-M"`` must pass through the post-pass unchanged — even if its
    authoritative docNumber/congress would yield a different string.
    """
    plaw_xml = _build_plaw("Public Law 105-100", "100", "105", _SIMPLE_MAIN)
    xml_path = _write_uslm_xml(tmp_path, plaw_xml)

    result = extract_public_law_from_uslm(str(xml_path), vol=105)
    law_ids = {r["LawIdentifier"] for r in result["Sections"]}

    assert law_ids == {"Public Law 105-100"}, (
        f"Well-formed law-id must be left untouched, got {law_ids}"
    )
