"""Vol 44 — the 1926 U.S. Code codification.

The codification is one undated <pLaw> (~12k sections) the resolver labeled
"69-1", colliding with the real Public Law 69-1 and leaving Congress/Session/
approvedDate null. The enricher gives it its own identity ("US Code 1926") plus
the authorizing-Act metadata (Congress 69, Session 1, approvedDate 1926-06-30),
and the validator accepts that special identifier.
"""
import pathlib

import pandas as pd
import pytest

from validation.validator import validate_law_id_format

XML_DIR = "/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06"


def test_validator_accepts_us_code_identifier():
    ok = pd.DataFrame({"LawIdentifier": ["US Code 1926", "Public Law 69–1", "72-430"]})
    assert validate_law_id_format(ok) == []
    bad = pd.DataFrame({"LawIdentifier": ["US Code", "random text"]})
    assert validate_law_id_format(bad)  # non-empty -> flagged


@pytest.mark.skipif(
    not pathlib.Path(f"{XML_DIR}/Congress_Session_Dates.csv").exists(),
    reason="Congress_Session_Dates.csv unavailable (off-server)",
)
def test_enricher_fills_vol44_codification(tmp_path):
    from pipeline.enricher import add_unique_keys

    cols = dict(VolumeNumber=44, EntryType="Section", SectionNumber="Sec. 1.",
                Division=None, Title=None, SubTitle=None, Chapter=None, SubChapter=None,
                DivisionHeadingLevel1=None, DivisionHeadingLevel2=None, DivisionHeadingLevel3=None)
    df = pd.DataFrame([
        {**cols, "LawIdentifier": "69-1", "approvedDate": ""},            # undated codification
        {**cols, "LawIdentifier": "69-495", "approvedDate": "July 3, 1926"},  # a real dated act
    ])
    out = add_unique_keys(df, tmp_path / "DivisionMapping.xlsx", vol=44,
                          source_xml_dir=XML_DIR, write_mapping=False)

    code = out.iloc[0]
    assert code["LawIdentifier"] == "US Code 1926"
    assert int(code["Congress"]) == 69
    assert str(code["Session"]) == "1"
    assert str(code["approvedDate"]) == "1926-06-30"

    dated = out.iloc[1]                       # the real dated law is untouched
    assert dated["LawIdentifier"] == "69-495"
    assert int(dated["Congress"]) == 69
