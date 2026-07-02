"""P1: the law-id correction matcher must be dash/prefix-insensitive so a
proposal trigger like '77-5' (hyphen, no prefix) matches the published
'Public Law 77–5' (en-dash, prefixed). Applies to both legacy and modern.
"""
import pandas as pd

from apply_corrections_and_publish import _apply_law_id_rules, _canon_law_id


def test_canon_law_id_strips_prefix_and_unifies_dashes():
    assert _canon_law_id("Public Law 77–320") == "77-320"   # en-dash + prefix
    assert _canon_law_id("Public Law 106—171") == "106-171"  # em-dash + prefix
    assert _canon_law_id("77-320") == "77-320"               # already bare/hyphen


def test_hyphen_trigger_matches_endash_prefixed_data():
    df = pd.DataFrame({
        "LawIdentifier": ["Public Law 77–5", "Public Law 77–6"],
        "LawTitle": ["Navy and Marine Corps temporary appointment", "Some other act"],
    })
    # trigger is the bare-hyphen form the subagent emits
    rules = [("77-5", "navy and marine corps temporary appointment", "77-188")]
    n = _apply_law_id_rules(df, rules)
    assert n == 1
    assert df.loc[0, "LawIdentifier"] == "77-188"            # matched + replaced
    assert df.loc[1, "LawIdentifier"] == "Public Law 77–6"   # untouched


def test_title_scope_prevents_collateral_matches():
    # Two laws share the number namespace but only the titled one is corrected.
    df = pd.DataFrame({
        "LawIdentifier": ["Public Law 79–496", "Public Law 79–496"],
        "LawTitle": ["genuine act about widgets", "to amend the act approved july 3 1943"],
    })
    rules = [("79-496", "to amend the act approved july 3 1943", "79-466")]
    n = _apply_law_id_rules(df, rules)
    assert n == 1
    assert df.loc[1, "LawIdentifier"] == "79-466"
    assert df.loc[0, "LawIdentifier"] == "Public Law 79–496"
