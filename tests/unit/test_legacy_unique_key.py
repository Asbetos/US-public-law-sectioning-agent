"""Updated 11-segment UniqueKey for legacy volumes (<=63): congress/session
derived from approvedDate; laws sharing a number across sessions stay distinct.
"""
import pandas as pd

import generate_id_keys as gik


def _row(**kw):
    base = dict(
        VolumeNumber=55, LawIdentifier="Public Law 77-188", Congress=77, Session=1,
        EntryType="Section", SectionNumber="Sec. 1.", Division=None, Title=None,
        SubTitle=None, Chapter=None, SubChapter=None,
    )
    base.update(kw)
    return pd.Series(base)


def test_legacy_key_is_11_segments_with_congress_session():
    key = gik.generate_unique_key_legacy(_row())
    parts = key.split("-")
    assert len(parts) == 11
    assert parts[0] == "055"          # volume
    assert parts[1] == "077"          # congress
    assert parts[2] == "1"            # session
    assert parts[3] == "188"          # law number (after the dash in LawIdentifier)
    assert parts[9] == "S"            # entry type


def test_same_law_number_different_session_yields_distinct_keys():
    k1 = gik.generate_unique_key_legacy(_row(Session=1))
    k2 = gik.generate_unique_key_legacy(_row(Session=2))
    assert k1 != k2                   # session disambiguates within one volume


def test_map_approved_date_to_congress_boundary_and_session():
    congress_df = pd.DataFrame({
        "Congress": [77, 77],
        "Session": [1, 2],
        "BeginDate": ["Jan 3 1941", "Jan 5 1942"],
        "AdjournDate": ["Jan 2 1942", "Dec 16 1942"],
    })
    res = gik.map_approved_date_to_congress(
        pd.Series(["July 24, 1941", "March 1, 1942"]), congress_df
    )
    assert int(res.iloc[0]["Congress"]) == 77 and int(res.iloc[0]["Session"]) == 1
    assert int(res.iloc[1]["Session"]) == 2


def test_legacy_approved_date_parses_to_yyyy_mm_dd():
    # Legacy XML stores "Month DD, YYYY"; output must be yyyy-mm-dd to match the
    # modern/original pipeline.
    s = pd.Series(["January 29, 1941", "July 24, 1941", "December 16, 1925"])
    parsed = gik.clean_date_col(s)
    assert [p.strftime("%Y-%m-%d") for p in parsed] == ["1941-01-29", "1941-07-24", "1925-12-16"]
