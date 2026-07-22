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


def test_congress_hint_prevents_cross_congress_boundary_error():
    # Regression: the 72nd Congress's 2nd session adjourned 1933-03-04, the exact
    # day the 73rd Congress's term began (its special session convened Mar 9), so
    # the table overlaps at Mar 4. A 72nd-Congress act signed Mar 4 1933 must NOT
    # be pushed into the phantom 73rd-Congress "S1" session.
    congress_df = pd.DataFrame({
        "Congress": [72, 72, 73, 73],
        "Session":  [1, 2, "S1", 1],
        "BeginDate":  ["Dec 7 1931", "Dec 5 1932", "Mar 4 1933", "Mar 9 1933"],
        "AdjournDate": ["Dec 5 1932", "Mar 4 1933", "Mar 9 1933", "Jan 3 1934"],
    })
    dates = pd.Series(["March 4, 1933", "March 4, 1933"])
    # Without a hint, the old "latest BeginDate wins" tie-break mislabels it 73-S1.
    no_hint = gik.map_approved_date_to_congress(dates, congress_df)
    assert str(no_hint.iloc[0]["Congress"]) == "73"
    # With the law's own congress as the hint, it is anchored to 72 -> session 2.
    hinted = gik.map_approved_date_to_congress(dates, congress_df,
                                               congress_hints=["72", "72"])
    assert int(hinted.iloc[0]["Congress"]) == 72 and str(hinted.iloc[0]["Session"]) == "2"
    # A genuine 73rd-Congress law signed Mar 9 1933 still resolves to 73-1.
    d2 = gik.map_approved_date_to_congress(pd.Series(["March 9, 1933"]), congress_df,
                                           congress_hints=["73"])
    assert int(d2.iloc[0]["Congress"]) == 73 and str(d2.iloc[0]["Session"]) == "1"


def test_congress_hint_anchors_law_signed_after_adjournment():
    # A bill passed by the 81st Congress but signed a few days AFTER it adjourned
    # (session 2 ends Jan 3 1951) carries LawIdentifier congress 81 but a Jan-1951
    # approvedDate that falls in the 82nd Congress's window. It must stay 81-2
    # (nearest session of its own congress), not become 82-1 or null.
    congress_df = pd.DataFrame({
        "Congress": [81, 81, 82],
        "Session":  [1, 2, 1],
        "BeginDate":  ["Jan 3 1949", "Jan 3 1950", "Jan 3 1951"],
        "AdjournDate": ["Jan 3 1950", "Jan 3 1951", "Jan 8 1952"],
    })
    res = gik.map_approved_date_to_congress(pd.Series(["January 10, 1951"]),
                                            congress_df, congress_hints=["81"])
    assert int(res.iloc[0]["Congress"]) == 81 and str(res.iloc[0]["Session"]) == "2"


def test_legacy_approved_date_parses_to_yyyy_mm_dd():
    # Legacy XML stores "Month DD, YYYY"; output must be yyyy-mm-dd to match the
    # modern/original pipeline.
    s = pd.Series(["January 29, 1941", "July 24, 1941", "December 16, 1925"])
    parsed = gik.clean_date_col(s)
    assert [p.strftime("%Y-%m-%d") for p in parsed] == ["1941-01-29", "1941-07-24", "1925-12-16"]
