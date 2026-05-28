"""Smoke tests for the corrections moved out of Extract_Sections_Divisions_From_XML.py."""
import pytest

from law_id_corrections import (
    apply_law_id_corrections,
    apply_section_number_correction,
    SECTION_NUMBER_CORRECTIONS,
)


# ---- apply_law_id_corrections ----

@pytest.mark.parametrize(
    "law_id_in, title, expected",
    [
        ("81-175", "An Act amending Social Security provisions", "81-174"),
        ("81-208", "Federal Crop Insurance reform", "81-268"),
        ("81-208", "Preference Act of 1944 with respect to certain mothers of veterans", "81-269"),
        ("81-285", "Republic of Finland on the principal or interest of war debts", "81-265"),
        # En-dash in input law id (–): must still match
        ("104–9", "Federal Election Campaign Act of 1971 to improve oversight", "104-79"),
        ("79-496", "To amend the Act approved July 3, 1943, entitled “An Act to provide for the settlement of claims for damage to or loss or destruction of property or personal injury or death caused by military personnel or civilian employees, or otherwise incident to activities, of the War Department or of the Army", "79-466"),
        ("79-673", "To authorize the return of the Grand River Dam project to the Grand River Dam Authority and the adjustment and settlement of accounts between the authority and the United States, and for other purposes", "79-573"),
        ("79-679", "To authorize the use by industry of silver held or owned by the United States, and for other purposes", "79-579"),
        ("84-274", "To modify the project for the Saint Mary River, Michigan, South Canal, in order to repeal the authorization for the alteration of the International Bridge as part of such project, and to authorize the Secretary of the Army to accomplish such alteration.", "84-663"),
    ],
)
def test_law_id_corrections_apply(law_id_in, title, expected):
    assert apply_law_id_corrections(law_id_in, title) == expected


def test_law_id_corrections_pass_through_when_no_match():
    # No correction should fire for unrelated law ids
    assert apply_law_id_corrections("99-999", "Some unrelated law title") == "99-999"


def test_law_id_corrections_pass_through_when_id_matches_but_title_does_not():
    # The 81-175 correction requires "social security" in the title; here it is absent.
    assert apply_law_id_corrections("81-175", "Some unrelated subject") == "81-175"


# ---- apply_section_number_correction ----

def test_section_correction_data_shape():
    # Five known overrides
    assert len(SECTION_NUMBER_CORRECTIONS) == 5
    for entry in SECTION_NUMBER_CORRECTIONS:
        assert len(entry) == 4
        match_id, match_heading, match_text, replacement = entry
        assert isinstance(match_id, str) and match_id
        assert isinstance(match_heading, str) and match_heading
        assert match_text is None or isinstance(match_text, str)
        assert isinstance(replacement, str) and replacement.startswith("SEC.")


@pytest.mark.parametrize(
    "law_id, heading, text, expected_num",
    [
        ("Public Law 106–382", "USE OF PICK-SLOAN POWER", "", "SEC. 6."),
        ("Public Law 106–181", "GRANTS FROM SMALL AIRPORT FUND", "", "SEC. 128."),
        ("Public Law 98–369",  "VALUE OF USED COMPONENTS FURNISHED BY FIRST USER NOT TAKEN INTO ACCOUNT IN DETERMINING PRICE", "", "SEC. 734."),
    ],
)
def test_section_correction_simple_heading_match(law_id, heading, text, expected_num):
    num, flagged = apply_section_number_correction("SEC. UNKNOWN.", law_id, heading, text)
    assert flagged is True
    assert num == expected_num


def test_section_correction_passes_through_when_no_match():
    num, flagged = apply_section_number_correction("SEC. 99.", "99-999", "unrelated heading", "")
    assert flagged is False
    assert num == "SEC. 99."


def test_section_correction_handles_none_heading_and_text():
    num, flagged = apply_section_number_correction("SEC. 99.", "99-999", None, None)
    assert flagged is False
    assert num == "SEC. 99."


def test_section_correction_106_259_requires_text_discriminator():
    # 106-259 has TWO entries; both need 'transfer of funds' in heading,
    # but they disambiguate on a long text substring. Without the text, no match.
    num, flagged = apply_section_number_correction("SEC. UNKNOWN.", "Public Law 106–259", "transfer of funds", "")
    assert flagged is False
    assert num == "SEC. UNKNOWN."


def test_section_correction_106_259_first_variant():
    text = (
        "Funds appropriated in title III of this Act for the Department of Defense Pilot Mentor-Protege Program "
        "may be transferred to any other appropriation contained in this Act solely for the purpose of "
        "implementing a Mentor-Protege Program developmental assistance agreement pursuant to section 831 of "
        "the National Defense Authorization Act for Fiscal Year 1991 (Public Law 101–510; 10 U.S.C. 2301 note), "
        "as amended, under the authority of this provision or any other transfer authority contained in this Act."
    )
    num, flagged = apply_section_number_correction("SEC. UNKNOWN.", "Public Law 106–259", "transfer of funds", text)
    assert flagged is True
    assert num == "SEC. 8015."


def test_section_correction_106_259_second_variant():
    text = (
        "During the current fiscal year, amounts contained in the Department of Defense Overseas Military "
        "Facility Investment Recovery Account established by section 2921(c)(1) of the National Defense "
        "Authorization Act of 1991 (Public Law 101–510; 10 U.S.C. 2687 note) shall be available until "
        "expended for the payments specified by section 2921(c)(2) of that Act:"
    )
    num, flagged = apply_section_number_correction("SEC. UNKNOWN.", "Public Law 106–259", "transfer of funds", text)
    assert flagged is True
    assert num == "SEC. 8041."


def test_section_correction_case_insensitive():
    # Heading lookup is case-insensitive
    num, flagged = apply_section_number_correction("SEC. UNKNOWN.", "Public Law 98–369", "value of used components furnished by first user not taken into account in determining price", "")
    assert flagged is True
    assert num == "SEC. 734."
