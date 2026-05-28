"""Known law-ID corrections for OCR/parsing errors in older statute volumes.

These rules were originally inlined in Extract_Sections_Divisions_From_XML.py;
moved here so the main parser loop is easier to read and the corrections are
easier to audit and extend.
"""

LAW_ID_CORRECTIONS = [
    # (law_id_substring, title_substring_lowercase, replacement_id)
    ("81-175", "social security", "81-174"),
    ("81-208", "federal crop insurance", "81-268"),
    ("81-208", "preference act of 1944 with respect to certain mothers of veterans", "81-269"),
    ("81-285", "republic of finland on the principal or interest", "81-265"),
    ("104–9", "federal election campaign act of 1971 to improve", "104-79"),
    ("79-496", "to amend the act approved july 3, 1943, entitled “an act to provide for the settlement of claims for damage to or loss or destruction of property or personal injury or death caused by military personnel or civilian employees, or otherwise incident to activities, of the war department or of the army", "79-466"),
    ("79-673", "to authorize the return of the grand river dam project to the grand river dam authority and the adjustment and settlement of accounts between the authority and the united states, and for other purposes", "79-573"),
    ("79-679", "to authorize the use by industry of silver held or owned by the united states, and for other purposes", "79-579"),
    ("84-274", "to modify the project for the saint mary river, michigan, south canal, in order to repeal the authorization for the alteration of the international bridge as part of such project, and to authorize the secretary of the army to accomplish such alteration.", "84-663"),
]


def apply_law_id_corrections(law_identifiers, law_title):
    """Return the corrected law identifier when a known issue is detected."""
    title_lower = law_title.lower()
    for match_id, match_title, replacement in LAW_ID_CORRECTIONS:
        if match_id in law_identifiers and match_title in title_lower:
            law_identifiers = replacement
    return law_identifiers


SECTION_NUMBER_CORRECTIONS = [
    # (law_id_substring, heading_text_substring, text_substring_or_None, new_num)
    ("106\u2013382", "USE OF PICK-SLOAN POWER", None, "SEC. 6."),
    ("106\u2013259", "transfer of funds", "Funds appropriated in title III of this Act for the Department of Defense Pilot Mentor-Protege Program may be transferred to any other appropriation contained in this Act solely for the purpose of implementing a Mentor-Protege Program developmental assistance agreement pursuant to section 831 of the National Defense Authorization Act for Fiscal Year 1991 (Public Law 101\u2013510; 10 U.S.C. 2301 note), as amended, under the authority of this provision or any other transfer authority contained in this Act.", "SEC. 8015."),
    ("106\u2013259", "transfer of funds", "During the current fiscal year, amounts contained in the Department of Defense Overseas Military Facility Investment Recovery Account established by section 2921(c)(1) of the National Defense Authorization Act of 1991 (Public Law 101\u2013510; 10 U.S.C. 2687 note) shall be available until expended for the payments specified by section 2921(c)(2) of that Act:", "SEC. 8041."),
    ("106\u2013181", "GRANTS FROM SMALL AIRPORT FUND", None, "SEC. 128."),
    ("98\u2013369", "VALUE OF USED COMPONENTS FURNISHED BY FIRST USER NOT TAKEN INTO ACCOUNT IN DETERMINING PRICE", None, "SEC. 734."),
]


def apply_section_number_correction(num, law_identifiers, heading_text, text):
    """Return (num, flagged); flagged=True means num was overridden to a literal SEC-number string."""
    h = (heading_text or "").lower()
    t = (text or "").lower()
    for match_id, match_heading, match_text, replacement in SECTION_NUMBER_CORRECTIONS:
        if match_id not in law_identifiers:
            continue
        if match_heading.lower() not in h:
            continue
        if match_text is not None and match_text.lower() not in t:
            continue
        return replacement, True
    return num, False
