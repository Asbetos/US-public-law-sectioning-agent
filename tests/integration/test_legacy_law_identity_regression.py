"""Regression: legacy-law-identity resolver over the 2026-06-30 vols 44-64 run.

Parses real XML from the read-only production dir. Skips automatically if the
XML dir is unavailable (e.g. off-server / post-migration).
"""
import pathlib
import re

import pytest

from parser.uslm_parser import extract_public_law_from_uslm

XML_DIR = "/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06"
PATTERN = re.compile(r"\d+[-–—]\d+")

pytestmark = pytest.mark.skipif(
    not pathlib.Path(XML_DIR).exists(),
    reason="production XML dir unavailable",
)


def _law_ids(vol):
    res = extract_public_law_from_uslm(f"{XML_DIR}/STATUTE-{vol}.xml", str(vol))
    return [r.get("LawIdentifier") for r in res["Sections"]]


@pytest.mark.parametrize("vol", [44, 48])
def test_previously_crashing_volumes_now_parse(vol):
    ids = _law_ids(vol)              # must not raise AttributeError
    assert len(ids) > 0


@pytest.mark.parametrize("vol", [45, 46, 47, 49, 50, 51, 52, 53, 54, 56, 58])
def test_no_blank_law_identifiers(vol):
    ids = _law_ids(vol)
    blanks = [x for x in ids if not x or not PATTERN.search(str(x))]
    assert blanks == [], f"vol {vol} has {len(blanks)} unrecognizable LawIdentifiers"


@pytest.mark.parametrize("vol", [55, 57, 59, 61, 62, 63, 64])
def test_ready_volumes_ids_are_pl_number_namespace(vol):
    # Legacy ids must no longer be blank/chapter-only: every id should be a
    # recognizable {congress}-{N} value reflecting the sidenote public-law number.
    # Vol 64 is legacy-structured too (public-law number in the sidenote, chapter
    # in docNumber, no "Public Law N" citableAs), so the legacy boundary is <=64.
    ids = [x for x in _law_ids(vol) if x]
    assert ids and all(PATTERN.search(str(x)) for x in ids)


@pytest.mark.parametrize("vol", [105, 108])
def test_modern_volumes_unaffected(vol):
    # Module is gated to <=64; modern volumes (>64) must still parse and keep the
    # canonical "Public Law N-M" citable form (repair pass still runs for >64).
    ids = [x for x in _law_ids(vol) if x]
    assert ids
    assert any("Public Law" in str(x) for x in ids)


def test_vol70_saint_mary_seed_correction_survives_repair():
    # Regression: the 84-274 -> 84-663 seed correction (Saint Mary River) must
    # survive the malformed-id repair pass. The repair previously treated the
    # bare corrected id "84-663" (no "Public Law" prefix) as malformed and
    # rebuilt "Public Law 84-274" from <docNumber>, undoing the correction.
    res = extract_public_law_from_uslm(f"{XML_DIR}/STATUTE-70.xml", "70")
    sm = [r for r in res["Sections"]
          if "saint mary river" in str(r.get("LawTitle", "")).lower()]
    assert sm, "saint-mary law not found in vol 70"
    ids = {r.get("LawIdentifier") for r in sm}
    assert ids == {"84-663"}, f"expected 84-663, got {ids}"
