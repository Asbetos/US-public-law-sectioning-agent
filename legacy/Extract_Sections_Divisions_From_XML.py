import xml.etree.ElementTree as ET
import json
import re
import pandas as pd
import configparser
import os
import numpy as np
import time
from datetime import datetime
import shutil
import traceback
import logging
np.random.seed(42)

from post_process import fetch_agency_list,add_grouped_agencies
from generate_id_keys import generate_and_process_id, update_all_directories
from law_id_corrections import apply_law_id_corrections, apply_section_number_correction
from legacy_law_identity import resolve_legacy_law_identities

logger = logging.getLogger(__name__)


def get_clean_text(elem,typ='Section'):
    """Extract text from an element while skipping entire <sidenote> and <page> subtrees."""
    texts = []

    def recursive_collect(e):
        tag = e.tag.split('}')[-1]
        if tag in ['sidenote', 'page', 'approvedDate', "footnote"]:
            if e.tail:
                texts.append(e.tail)
            return  # Skip this tag and all its children
        if e.text:
            texts.append(e.text)
        for child in e:
            recursive_collect(child)
        if e.tail:
            texts.append(e.tail)

    def recursive_collect_appr(e):
        tag = e.tag.split('}')[-1]
        if tag in ['sidenote', 'page', 'approvedDate', "footnote", "heading", "subheading"]:
            if e.tail:
                texts.append(e.tail)
            return  # Skip this tag and all its children
        if e.text:
            texts.append(e.text)
        for child in e:
            recursive_collect_appr(child)
        if e.tail:
            texts.append(e.tail)

    try:
        if typ == 'Section':
            recursive_collect(elem)
        else:
            recursive_collect_appr(elem)
        # return ''.join(texts).strip()
        return "".join(filter(None, texts))
    except Exception as ex:
        # print(f"Error in get_clean_text: {ex}")
        return ''


def extract_section_text(section, ns):

    def recursive_extract(elem, indent_level=0):
        indent = "    " * indent_level
        lines = []

        tag = elem.tag.split('}')[-1]
        num = elem.find("uslm:num", ns)
        heading = elem.find("uslm:heading", ns)
        content = elem.find("uslm:content", ns)
        chapeau = elem.find("uslm:chapeau", ns)

        # num_text = ''.join(num.itertext()).strip() if num is not None else ""
        # heading_text = ''.join(heading.itertext()).strip() if heading is not None else ""

        num_text = get_clean_text(num) if num is not None else ""
        heading_text = get_clean_text(heading) if heading is not None else ""

        # Add content or chapeau
        if chapeau is not None:
            if tag== "section":
                lines.append(f"{indent}{get_clean_text(chapeau)}")
            else:
                # if indent_level == 0:
                #     indent = "    " * indent_level
                lines.append(f"{indent}{num_text}{heading_text}{get_clean_text(chapeau)}")

        if content is not None:
            if tag != "section":
                if tag=='appropriations':
                    lines.append(f"{get_clean_text(content)}")
                else:
                    lines.append(f"{indent}{num_text}{heading_text}{get_clean_text(content)}")
            else:
                lines.append(f"{indent}{get_clean_text(content)}")

        else:
            if tag != "section" and chapeau is None:
                lines.append(f"{indent}{num_text}{heading_text}")

        # Recurse through children (preserving hierarchy)
        # for child_tag in ["section", "subsection", "paragraph", "subparagraph", "clause", "subclause", "chapter",
        #                   "subchapter"]:
        #     for child in elem.findall(f"uslm:{child_tag}", ns):
        #         child_text = recursive_extract(child, indent_level + 1)
        #         if child_text:
        #             lines.append(child_text)

        for child in list(elem):
            tag_name = child.tag.split('}')[-1]
            if tag_name in {"section", "subsection", "paragraph", "subparagraph", "clause", "subclause", "chapter",
                            "subchapter", "item", "level"}:
                child_text = recursive_extract(child, indent_level + 1)
                if child_text:
                    continuation = child.findall("uslm:continuation", ns)
                    if continuation is not None:
                        continuation_text = ''
                        for cnt in continuation:
                            cnt_text = get_clean_text(cnt)
                            continuation_text = continuation_text + " " + cnt_text
                        child_text = child_text + ' ' +continuation_text
                    lines.append(child_text)

        return "\n".join(filter(None, lines))

    return recursive_extract(section).strip()


def process_section(section, ns):
    num = section.find("uslm:num", ns)
    heading = section.find("uslm:heading", ns)

    text = extract_section_text(section, ns)

    return num, heading, text


def extract_public_law_from_uslm(file_path,vol):
    tree = ET.parse(file_path)
    root = tree.getroot()
    ns = {'uslm': root.tag.split('}')[0].strip('{')}
    results = {"Sections": [], "Divisions": []}

    plaws = root.findall(".//uslm:pLaw", ns)
    legacy_ids = resolve_legacy_law_identities(plaws, vol, ns) if int(vol) <= 63 else {}

    for plaw_idx, plaw in enumerate(plaws):
        if int(vol) <= 63:
            ident = legacy_ids.get(plaw_idx)
            if ident is None or not ident["is_public"]:
                continue
        else:
            lawtype_el = plaw.find(".//uslm:publicPrivate", ns)
            if lawtype_el is None or not lawtype_el.text or lawtype_el.text.strip().lower() != "public":
                continue
        # Volumes >63 use modern USLM with <citableAs>; earlier volumes encode the
        # public-law number inside <sidenote> text and need regex extraction.
        if int(vol)>63:
            c = plaw.find(".//uslm:citableAs", ns)
            law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
            if int(vol) == 70:
                c = plaw.find(".//uslm:docNumber", ns)
                law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
                congress = plaw.find(".//uslm:congress", ns)
                congress_text = ''.join(congress.itertext()).strip() if congress is not None else ""
                law_identifiers = 'Public Law ' + congress_text + '-' + law_identifiers
            if "v" in law_identifiers:
                print("V- Logic")
                c = plaw.find(".//uslm:docNumber", ns)
                law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
                law_identifiers = 'Public Law ' + law_identifiers
            if "public law" not in law_identifiers.lower(): # was previously 'stat' in
                c = plaw.find(".//uslm:docNumber", ns)
                law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
                congress = plaw.find(".//uslm:congress", ns)
                congress_text = ''.join(congress.itertext()).strip() if congress is not None else ""
                law_identifiers = 'Public Law ' + congress_text + '-' + law_identifiers

        else:
            # Legacy (vol <=63) public-law-number id comes from the
            # legacy-law-identity resolver (computed once above). This replaces the
            # old inline <sidenote> regex (which emitted bare/empty ids and whose
            # private-law branch `break`-ed out of the whole volume walk).
            law_identifiers = legacy_ids[plaw_idx]["law_identifier"]

        # if law_identifiers!= '81-118':
        #     continue
        approved_date_elem = plaw.find(".//uslm:approvedDate", ns)
        approved_date = ''.join(approved_date_elem.itertext()).strip() if approved_date_elem is not None else ''
        law_title_elem = plaw.find(".//uslm:officialTitle", ns)
        law_title = get_clean_text(law_title_elem) if law_title_elem is not None else ''
        law_type_elem = plaw.find(".//uslm:docTitle", ns)
        law_type = get_clean_text(law_type_elem) if law_type_elem is not None else ''
        counter = 0

        law_identifiers = apply_law_id_corrections(law_identifiers, law_title)

        main = plaw.find("uslm:main", ns)
        if main is None:
            logger.warning("Skipping law %s (vol %s): no <main> element", law_identifiers, vol)
            continue

        # === Surgical correction #2 (approved 2026-05-27 by G39248410). Vol 75 only. ===
        # PL 87-292 (joint resolution, two unnumbered "That..." sections separated by
        # <resolvingClause>) and PL 87-356 (introductory <section> + amendatory <section>
        # whose <num value="207"> sits inside <quotedContent>) both produce 2 top-level
        # <section> elements with no extractor-visible <num>, collapsing to a duplicate
        # UniqueKey. Emit each section with a synthetic 1-based ordinal as SectionNumber.
        if str(vol) == "75" and law_identifiers in ("Public Law 87–292", "Public Law 87–356"):
            for idx, section in enumerate(main.findall("uslm:section", ns), start=1):
                _num, heading, text = process_section(section, ns)
                # PL 87-356's second <section> wraps its body in <quotedContent>, which
                # extract_section_text does not recurse into — fall back to a full subtree
                # walk so the amendatory text surfaces.
                if not text:
                    text = get_clean_text(section).strip() or None
                results["Sections"].append({
                    "counter": counter,
                    "LawIdentifier": law_identifiers,
                    "approvedDate": approved_date,
                    "LawTitle": law_title,
                    "LawType": law_type,
                    "Division": None,
                    "Title": None,
                    "SubTitle": None,
                    "Chapter": None,
                    "SubChapter": None,
                    "SectionNumber": str(idx),
                    "SectionName": get_clean_text(heading) if heading is not None else None,
                    "Text": text if text else None,
                    "DivisionHeadingLevel1": None,
                    "DivisionHeadingLevel2": None,
                    "DivisionHeadingLevel3": None,
                })
                counter += 1
            continue

        # === Surgical correction #3a (approved 2026-05-27 by G39248410). Vol 75 only. ===
        # PL 87-195 (Foreign Assistance Act of 1961) and PL 87-328 (Delaware River Basin
        # Compact) are multi-part Acts: <main> contains <part> elements at the top level
        # with no top-level <section>. The standard walker finds 0 sections and drops the
        # pLaw. Walk each <part>'s <section> children and carry the part heading into
        # DivisionHeadingLevel1.
        if str(vol) == "75" and law_identifiers in ("Public Law 87–195", "Public Law 87–328"):
            for part in main.findall("uslm:part", ns):
                part_num = part.find("uslm:num", ns)
                part_heading = part.find("uslm:heading", ns)
                part_label = (
                    (get_clean_text(part_num) if part_num is not None else "")
                    + (get_clean_text(part_heading) if part_heading is not None else "")
                ).strip()
                for section in part.findall("uslm:section", ns):
                    num, heading, text = process_section(section, ns)
                    num, flagged = apply_section_number_correction(
                        num, law_identifiers,
                        get_clean_text(heading) if heading is not None else "",
                        text,
                    )
                    results["Sections"].append({
                        "counter": counter,
                        "LawIdentifier": law_identifiers,
                        "approvedDate": approved_date,
                        "LawTitle": law_title,
                        "LawType": law_type,
                        "Division": None,
                        "Title": None,
                        "SubTitle": None,
                        "Chapter": None,
                        "SubChapter": None,
                        "SectionNumber": num if flagged else get_clean_text(num) if num is not None else None,
                        "SectionName": get_clean_text(heading) if heading is not None else None,
                        "Text": text if text else None,
                        "DivisionHeadingLevel1": part_label or None,
                        "DivisionHeadingLevel2": None,
                        "DivisionHeadingLevel3": None,
                    })
                    counter += 1
            continue

        # === Surgical correction #7 (approved 2026-05-27 by G39248410). Vol 78 only. ===
        # PL 88-643 (CIA Retirement Act of 1964): <main> contains 2 top-level <title>
        # elements (TITLE I — Title and Definitions; TITLE II — CIA Retirement and
        # Disability System) with no top-level <section>. Each <title> contains
        # <part> elements which contain the actual <section> children (26 total).
        # Standard walker finds 0 sections and drops the pLaw. Walk title/part/section
        # and carry title heading into DivisionHeadingLevel1, part heading into Level2.
        if str(vol) == "78" and law_identifiers == "Public Law 88–643":
            for title in main.findall("uslm:title", ns):
                title_num = title.find("uslm:num", ns)
                title_heading = title.find("uslm:heading", ns)
                title_label = (
                    (get_clean_text(title_num) if title_num is not None else "")
                    + (get_clean_text(title_heading) if title_heading is not None else "")
                ).strip()
                for part in title.findall("uslm:part", ns):
                    part_num = part.find("uslm:num", ns)
                    part_heading = part.find("uslm:heading", ns)
                    part_label = (
                        (get_clean_text(part_num) if part_num is not None else "")
                        + (get_clean_text(part_heading) if part_heading is not None else "")
                    ).strip()
                    for section in part.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        num, flagged = apply_section_number_correction(
                            num, law_identifiers,
                            get_clean_text(heading) if heading is not None else "",
                            text,
                        )
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": None,
                            "Title": None,
                            "SubTitle": None,
                            "Chapter": None,
                            "SubChapter": None,
                            "SectionNumber": num if flagged else get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": title_label or None,
                            "DivisionHeadingLevel2": part_label or None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1
            continue

        # === Surgical correction #3b (approved 2026-05-27 by G39248410). Vol 75 only. ===
        # PL 87-397 (IRC of 1954 identifying-numbers amendment) is a short single-section
        # amending Act: <main> contains 4 bare <subsection> elements (a, b, c, d) with no
        # top-level <section>. Standard walker finds 0 sections and drops the pLaw.
        # Synthesize one section row carrying the concatenated subsection text.
        if str(vol) == "75" and law_identifiers == "Public Law 87–397":
            sub_texts = []
            for subsection in main.findall("uslm:subsection", ns):
                sub_text = extract_section_text(subsection, ns)
                if sub_text:
                    sub_texts.append(sub_text)
            results["Sections"].append({
                "counter": counter,
                "LawIdentifier": law_identifiers,
                "approvedDate": approved_date,
                "LawTitle": law_title,
                "LawType": law_type,
                "Division": None,
                "Title": None,
                "SubTitle": None,
                "Chapter": None,
                "SubChapter": None,
                "SectionNumber": "1",
                "SectionName": None,
                "Text": "\n".join(sub_texts) if sub_texts else None,
                "DivisionHeadingLevel1": None,
                "DivisionHeadingLevel2": None,
                "DivisionHeadingLevel3": None,
            })
            counter += 1
            continue

        # Process top-level sections
        for section in main.findall("uslm:section", ns):
            num, heading, text = process_section(section, ns)

            num, flagged = apply_section_number_correction(num, law_identifiers, get_clean_text(heading) if heading is not None else "", text)

            results["Sections"].append({
                "counter": counter,
                "LawIdentifier": law_identifiers,
                "approvedDate": approved_date,
                "LawTitle": law_title,
                "LawType": law_type,
                "Division": None,
                "Title": None,
                "SubTitle": None,
                "Chapter": None,
                "SubChapter": None,
                "SectionNumber": num if flagged else get_clean_text(num) if num is not None else None,
                "SectionName": get_clean_text(heading) if heading is not None else None,
                "Text": text if text else None,
                "DivisionHeadingLevel1": None,
                "DivisionHeadingLevel2": None,
                "DivisionHeadingLevel3": None,
            })
            counter += 1

        #Process top-level appropriations - added for 63 and below
        for appropriation in main.findall("uslm:appropriations", ns):
            heading_appr = appropriation.find("uslm:heading", ns)
            subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
            subheading_1 = ' '
            if subheading_appr_1:
                for subheading_appr in subheading_appr_1:
                    subheading_1_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                    subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
            appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
            if appropriation_intermediate:
                for appropriation_level2 in appropriation_intermediate:
                    heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                    subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                    subheading_2 = ' '
                    if subheading_appr_2:
                        for subheading_appr in subheading_appr_2:
                            subheading_2_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                            subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                    appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                    if appropriation_small:
                        for appropriation_level3 in appropriation_small:
                            heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                            subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                            subheading_3 = ' '
                            if subheading_appr_3:
                                for subheading_appr in subheading_appr_3:
                                    subheading_3_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                    subheading_3 = str(subheading_3 or "") + str(subheading_3_text or "")
                            appr3_content = appropriation_level3.find("uslm:content", ns)
                            if appr3_content:
                                appr_small_text = get_clean_text(appr3_content)
                                # print("--here--")
                                # print(appr_small_text)
                            else:
                                appr_small_text = get_clean_text(appropriation_level3, "appr")
                                # print("--there--")
                                # print(appr_small_text)
                            results["Divisions"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": None,
                                "Title": None,
                                "SubTitle": None,
                                "Chapter": None,
                                "SubChapter": None,
                                "SectionNumber": None,
                                "SectionName": None,
                                "Text": appr_small_text,
                                "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                                "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "")+ str(subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                "DivisionHeadingLevel3": (str(get_clean_text(heading_appr_3) or "")+ str(subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                            })
                            counter += 1
                    else:
                        appr2_content = appropriation_level2.find("uslm:content", ns)
                        if appr2_content:
                            appr_inter_text = get_clean_text(appr2_content)
                        else:
                            appr_inter_text = get_clean_text(appropriation_level2, "appr")

                        results["Divisions"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": None,
                            "Title": None,
                            "SubTitle": None,
                            "Chapter": None,
                            "SubChapter": None,
                            "SectionNumber": None,
                            "SectionName": None,
                            "Text": appr_inter_text,
                            "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                            "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "")+ str(subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                            "DivisionHeadingLevel3":  None,
                        })
                        counter += 1

            else:
                appr_content = appropriation.find("uslm:content", ns)
                if appr_content:
                    division_text = get_clean_text(appr_content)
                else:
                    division_text = get_clean_text(appropriation, "appr")

                results["Divisions"].append({
                    "counter": counter,
                    "LawIdentifier": law_identifiers,
                    "approvedDate": approved_date,
                    "LawTitle": law_title,
                    "LawType": law_type,
                    "Division": None,
                    "Title": None,
                    "SubTitle": None,
                    "Chapter": None,
                    "SubChapter": None,
                    "SectionNumber": None,
                    "SectionName": None,
                    "Text": division_text,
                    "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                    "DivisionHeadingLevel2": None,
                    "DivisionHeadingLevel3": None,
                })
                counter += 1

        #Process top-level sections inside <level> - added for 63 and below
        for level in main.findall("uslm:level", ns):
            for section in level.findall("uslm:section", ns):
                num, heading, text = process_section(section, ns)
                results["Sections"].append({
                    "counter": counter,
                    "LawIdentifier": law_identifiers,
                    "approvedDate": approved_date,
                    "LawTitle": law_title,
                    "LawType": law_type,
                    "Division": None,
                    "Title": None,
                    "SubTitle": None,
                    "Chapter": None,
                    "SubChapter": None,
                    "SectionNumber": get_clean_text(num) if num is not None else None,
                    "SectionName": get_clean_text(heading) if heading is not None else None,
                    "Text": text if text else None,
                    "DivisionHeadingLevel1": None,
                    "DivisionHeadingLevel2": None,
                    "DivisionHeadingLevel3": None,
                })
                counter += 1


        # Process Title/Subtitle Level
        for title in main.findall("uslm:title", ns):
            num_title = title.find("uslm:num", ns)
            title_text = num_title.text if num_title is not None else None

            for level in title.findall("uslm:level", ns):
                for section in level.findall("uslm:section", ns):
                    num, heading, text = process_section(section, ns)
                    results["Sections"].append({
                        "counter": counter,
                        "LawIdentifier": law_identifiers,
                        "approvedDate": approved_date,
                        "LawTitle": law_title,
                        "LawType": law_type,
                        "Division": None,
                        "Title": title_text,
                        "SubTitle": None,
                        "Chapter": None,
                        "SubChapter": None,
                        "SectionNumber": get_clean_text(num) if num is not None else None,
                        "SectionName": get_clean_text(heading) if heading is not None else None,
                        "Text": text if text else None,
                        "DivisionHeadingLevel1": None,
                        "DivisionHeadingLevel2": None,
                        "DivisionHeadingLevel3": None,
                    })
                    counter += 1

            for section in title.findall("uslm:section", ns):
                num, heading, text = process_section(section, ns)

                num, flagged = apply_section_number_correction(num, law_identifiers, get_clean_text(heading) if heading is not None else "", text)

                results["Sections"].append({
                    "counter": counter,
                    "LawIdentifier": law_identifiers,
                    "approvedDate": approved_date,
                    "LawTitle": law_title,
                    "LawType": law_type,
                    "Division": None,
                    "Title": title_text,
                    "SubTitle": None,
                    "Chapter": None,
                    "SubChapter": None,
                    "SectionNumber": num if flagged else get_clean_text(num) if num is not None else None,
                    "SectionName": get_clean_text(heading) if heading is not None else None,
                    "Text": text if text else None,
                    "DivisionHeadingLevel1": None,
                    "DivisionHeadingLevel2": None,
                    "DivisionHeadingLevel3": None,
                })
                counter += 1

            #add chapter/subchapter to title
            for chapter in title.findall("uslm:chapter", ns):
                num_chapter = chapter.find("uslm:num", ns)
                chapter_text = num_chapter.text if num_chapter is not None else None

                for level in chapter.findall("uslm:level", ns):
                    for section in level.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": None,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": chapter_text,
                            "SubChapter": None,
                            "SectionNumber": get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                for section in chapter.findall("uslm:section", ns):
                    num, heading, text = process_section(section, ns)
                    results["Sections"].append({
                        "counter": counter,
                        "LawIdentifier": law_identifiers,
                        "approvedDate": approved_date,
                        "LawTitle": law_title,
                        "LawType": law_type,
                        "Division": None,
                        "Title": title_text,
                        "SubTitle": None,
                        "Chapter": chapter_text,
                        "SubChapter": None,
                        "SectionNumber": get_clean_text(num) if num is not None else None,
                        "SectionName": get_clean_text(heading) if heading is not None else None,
                        "Text": text if text else None,
                        "DivisionHeadingLevel1": None,
                        "DivisionHeadingLevel2": None,
                        "DivisionHeadingLevel3": None,
                    })
                    counter += 1

                for appropriation in chapter.findall("uslm:appropriations", ns):
                    heading_appr = appropriation.find("uslm:heading", ns)
                    subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
                    subheading_1 = ' '
                    if subheading_appr_1:
                        for subheading_appr in subheading_appr_1:
                            subheading_1_text = str(
                                get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                            subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
                    appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
                    if appropriation_intermediate:
                        for appropriation_level2 in appropriation_intermediate:
                            heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                            subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                            subheading_2 = ' '
                            if subheading_appr_2:
                                for subheading_appr in subheading_appr_2:
                                    subheading_2_text = str(
                                        get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                    subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                            appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                            if appropriation_small:
                                for appropriation_level3 in appropriation_small:
                                    heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                                    subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                                    subheading_3 = ' '
                                    if subheading_appr_3:
                                        for subheading_appr in subheading_appr_3:
                                            subheading_3_text = str(
                                                get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                            subheading_3 = str(subheading_3 or "") + str(subheading_3_text or "")
                                    appr3_content = appropriation_level3.find("uslm:content", ns)
                                    if appr3_content:
                                        appr_small_text = get_clean_text(appr3_content)
                                    else:
                                        appr_small_text = get_clean_text(appropriation_level3, "appr")
                                    results["Divisions"].append({
                                        "counter": counter,
                                        "LawIdentifier": law_identifiers,
                                        "approvedDate": approved_date,
                                        "LawTitle": law_title,
                                        "LawType": law_type,
                                        "Division": None,
                                        "Title": title_text,
                                        "SubTitle": None,
                                        "Chapter": chapter_text,
                                        "SubChapter": None,
                                        "SectionNumber": None,
                                        "SectionName": None,
                                        "Text": appr_small_text,
                                        "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                            subheading_1 or "")).strip() if heading_appr is not None else None,
                                        "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                            subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                        "DivisionHeadingLevel3": (str(get_clean_text(heading_appr_3) or "") + str(
                                            subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                                    })
                                    counter += 1
                            else:
                                appr2_content = appropriation_level2.find("uslm:content", ns)
                                if appr2_content:
                                    appr_inter_text = get_clean_text(appr2_content)
                                else:
                                    appr_inter_text = get_clean_text(appropriation_level2, "appr")

                                results["Divisions"].append({
                                    "counter": counter,
                                    "LawIdentifier": law_identifiers,
                                    "approvedDate": approved_date,
                                    "LawTitle": law_title,
                                    "LawType": law_type,
                                    "Division": None,
                                    "Title": title_text,
                                    "SubTitle": None,
                                    "Chapter": chapter_text,
                                    "SubChapter": None,
                                    "SectionNumber": None,
                                    "SectionName": None,
                                    "Text": appr_inter_text,
                                    "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                        subheading_1 or "")).strip() if heading_appr is not None else None,
                                    "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                        subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                    "DivisionHeadingLevel3": None,
                                })
                                counter += 1

                    else:
                        appr_content = appropriation.find("uslm:content", ns)
                        if appr_content:
                            division_text = get_clean_text(appr_content)
                        else:
                            division_text = get_clean_text(appropriation, "appr")

                        results["Divisions"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": None,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": chapter_text,
                            "SubChapter": None,
                            "SectionNumber": None,
                            "SectionName": None,
                            "Text": division_text,
                            "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                subheading_1 or "")).strip() if heading_appr is not None else None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1


            for part in title.findall("uslm:part",ns):
                # print("!!!!!!!!!!!!!part found")
                for chapter in part.findall("uslm:chapter", ns):
                    # print("!!!!!!!!!!!!!!!chapter")
                    num_chapter = chapter.find("uslm:num", ns)
                    chapter_text = num_chapter.text if num_chapter is not None else None

                    for level in chapter.findall("uslm:level", ns):
                        for section in level.findall("uslm:section", ns):
                            num, heading, text = process_section(section, ns)
                            results["Sections"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": None,
                                "Title": title_text,
                                "SubTitle": None,
                                "Chapter": chapter_text,
                                "SubChapter": None,
                                "SectionNumber": get_clean_text(num) if num is not None else None,
                                "SectionName": get_clean_text(heading) if heading is not None else None,
                                "Text": text if text else None,
                                "DivisionHeadingLevel1": None,
                                "DivisionHeadingLevel2": None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

                    for section in chapter.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        sec_num = None
                        if law_identifiers =='81-207' and '14' in title_text and '15' in chapter_text:
                            if 'Prisoners: allowances to; transportation' in get_clean_text(heading):
                                sec_num = '576.'
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": None,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": chapter_text,
                            "SubChapter": None,
                            "SectionNumber": sec_num if sec_num is not None else get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                    for appropriation in chapter.findall("uslm:appropriations", ns):
                        heading_appr = appropriation.find("uslm:heading", ns)
                        subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
                        subheading_1 = ' '
                        if subheading_appr_1:
                            for subheading_appr in subheading_appr_1:
                                subheading_1_text = str(
                                    get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
                        appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
                        if appropriation_intermediate:
                            for appropriation_level2 in appropriation_intermediate:
                                heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                                subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                                subheading_2 = ' '
                                if subheading_appr_2:
                                    for subheading_appr in subheading_appr_2:
                                        subheading_2_text = str(
                                            get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                        subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                                appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                                if appropriation_small:
                                    for appropriation_level3 in appropriation_small:
                                        heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                                        subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                                        subheading_3 = ' '
                                        if subheading_appr_3:
                                            for subheading_appr in subheading_appr_3:
                                                subheading_3_text = str(
                                                    get_clean_text(
                                                        subheading_appr)) if subheading_appr is not None else ''
                                                subheading_3 = str(subheading_3 or "") + str(subheading_3_text or "")
                                        appr3_content = appropriation_level3.find("uslm:content", ns)
                                        if appr3_content:
                                            appr_small_text = get_clean_text(appr3_content)
                                        else:
                                            appr_small_text = get_clean_text(appropriation_level3, "appr")
                                        results["Divisions"].append({
                                            "counter": counter,
                                            "LawIdentifier": law_identifiers,
                                            "approvedDate": approved_date,
                                            "LawTitle": law_title,
                                            "LawType": law_type,
                                            "Division": None,
                                            "Title": title_text,
                                            "SubTitle": None,
                                            "Chapter": chapter_text,
                                            "SubChapter": None,
                                            "SectionNumber": None,
                                            "SectionName": None,
                                            "Text": appr_small_text,
                                            "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                                subheading_1 or "")).strip() if heading_appr is not None else None,
                                            "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                                subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                            "DivisionHeadingLevel3": (str(get_clean_text(heading_appr_3) or "") + str(
                                                subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                                        })
                                        counter += 1
                                else:
                                    appr2_content = appropriation_level2.find("uslm:content", ns)
                                    if appr2_content:
                                        appr_inter_text = get_clean_text(appr2_content)
                                    else:
                                        appr_inter_text = get_clean_text(appropriation_level2, "appr")

                                    results["Divisions"].append({
                                        "counter": counter,
                                        "LawIdentifier": law_identifiers,
                                        "approvedDate": approved_date,
                                        "LawTitle": law_title,
                                        "LawType": law_type,
                                        "Division": None,
                                        "Title": title_text,
                                        "SubTitle": None,
                                        "Chapter": chapter_text,
                                        "SubChapter": None,
                                        "SectionNumber": None,
                                        "SectionName": None,
                                        "Text": appr_inter_text,
                                        "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                            subheading_1 or "")).strip() if heading_appr is not None else None,
                                        "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                            subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                        "DivisionHeadingLevel3": None,
                                    })
                                    counter += 1

                        else:
                            appr_content = appropriation.find("uslm:content", ns)
                            if appr_content:
                                division_text = get_clean_text(appr_content)
                            else:
                                division_text = get_clean_text(appropriation, "appr")

                            results["Divisions"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": None,
                                "Title": title_text,
                                "SubTitle": None,
                                "Chapter": chapter_text,
                                "SubChapter": None,
                                "SectionNumber": None,
                                "SectionName": None,
                                "Text": division_text,
                                "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                    subheading_1 or "")).strip() if heading_appr is not None else None,
                                "DivisionHeadingLevel2": None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

            #add appropriation to title
            for appropriation in title.findall("uslm:appropriations", ns):
                heading_appr = appropriation.find("uslm:heading", ns)
                subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
                subheading_1 = ' '
                if subheading_appr_1:
                    for subheading_appr in subheading_appr_1:
                        subheading_1_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                        subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
                appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
                if appropriation_intermediate:
                    for appropriation_level2 in appropriation_intermediate:
                        heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                        subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                        subheading_2 = ' '
                        if subheading_appr_2:
                            for subheading_appr in subheading_appr_2:
                                subheading_2_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                        appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                        if appropriation_small:
                            for appropriation_level3 in appropriation_small:
                                heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                                subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                                subheading_3 = ' '
                                if subheading_appr_3:
                                    for subheading_appr in subheading_appr_3:
                                        subheading_3_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                        subheading_3 = str(subheading_3 or "") + str(subheading_3_text or "")
                                appr3_content = appropriation_level3.find("uslm:content", ns)
                                if appr3_content:
                                    appr_small_text = get_clean_text(appr3_content)
                                else:
                                    appr_small_text = get_clean_text(appropriation_level3, "appr")
                                results["Divisions"].append({
                                    "counter": counter,
                                    "LawIdentifier": law_identifiers,
                                    "approvedDate": approved_date,
                                    "LawTitle": law_title,
                                    "LawType": law_type,
                                    "Division": None,
                                    "Title": title_text,
                                    "SubTitle": None,
                                    "Chapter": None,
                                    "SubChapter": None,
                                    "SectionNumber": None,
                                    "SectionName": None,
                                    "Text": appr_small_text,
                                    "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                                    "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "")+ str(subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                    "DivisionHeadingLevel3": (str(get_clean_text(heading_appr_3) or "")+ str(subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                                })
                                counter += 1
                        else:
                            appr2_content = appropriation_level2.find("uslm:content", ns)
                            if appr2_content:
                                appr_inter_text = get_clean_text(appr2_content)
                            else:
                                appr_inter_text = get_clean_text(appropriation_level2, "appr")

                            results["Divisions"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": None,
                                "Title": title_text,
                                "SubTitle": None,
                                "Chapter": None,
                                "SubChapter": None,
                                "SectionNumber": None,
                                "SectionName": None,
                                "Text": appr_inter_text,
                                "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                                "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "")+ str(subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

                else:
                    appr_content = appropriation.find("uslm:content", ns)
                    if appr_content:
                        division_text = get_clean_text(appr_content)
                    else:
                        division_text = get_clean_text(appropriation, "appr")

                    results["Divisions"].append({
                        "counter": counter,
                        "LawIdentifier": law_identifiers,
                        "approvedDate": approved_date,
                        "LawTitle": law_title,
                        "LawType": law_type,
                        "Division": None,
                        "Title": title_text,
                        "SubTitle": None,
                        "Chapter": None,
                        "SubChapter": None,
                        "SectionNumber": None,
                        "SectionName": None,
                        "Text": division_text,
                        "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                        "DivisionHeadingLevel2": None,
                        "DivisionHeadingLevel3": None,
                    })
                    counter += 1

            for subtitle in title.findall("uslm:subtitle", ns):
                num_subtitle = subtitle.find("uslm:num", ns)
                subtitle_text = num_subtitle.text if num_subtitle is not None else None

                for level in subtitle.findall("uslm:level", ns):
                    for section in level.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": None,
                            "Title": title_text,
                            "SubTitle": subtitle_text,
                            "Chapter": None,
                            "SubChapter": None,
                            "SectionNumber": get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                for section in subtitle.findall("uslm:section", ns):
                    num, heading, text = process_section(section, ns)
                    num, flagged = apply_section_number_correction(num, law_identifiers, get_clean_text(heading) if heading is not None else "", text)





                    results["Sections"].append({
                        "counter": counter,
                        "LawIdentifier": law_identifiers,
                        "approvedDate": approved_date,
                        "LawTitle": law_title,
                        "LawType": law_type,
                        "Division": None,
                        "Title": title_text,
                        "SubTitle": subtitle_text,
                        "Chapter": None,
                        "SubChapter": None,
                        "SectionNumber": num if flagged else get_clean_text(num) if num is not None else None,
                        "SectionName": get_clean_text(heading) if heading is not None else None,
                        "Text": text if text else None,
                        "DivisionHeadingLevel1": None,
                        "DivisionHeadingLevel2": None,
                        "DivisionHeadingLevel3": None,
                    })
                    counter += 1

                # add chapter/subchapter to title (sections)
                # add appropriation to subtitle

        # Process division Level
        for division in main.findall("uslm:division", ns):
            num_div = division.find("uslm:num", ns)
            div_title_text = get_clean_text(num_div)

            sections_in_div = division.findall("uslm:section", ns)
            if sections_in_div:
                for section in sections_in_div:
                    num, heading, text = process_section(section, ns)
                    results["Sections"].append({
                        "counter": counter,
                        "LawIdentifier": law_identifiers,
                        "approvedDate": approved_date,
                        "LawTitle": law_title,
                        "LawType": law_type,
                        "Division": div_title_text,
                        "Title": None,
                        "SubTitle": None,
                        "Chapter": None,
                        "SubChapter": None,
                        "SectionNumber": get_clean_text(num) if num is not None else None,
                        "SectionName": get_clean_text(heading) if heading is not None else None,
                        "Text": text if text else None,
                        "DivisionHeadingLevel1": None,
                        "DivisionHeadingLevel2": None,
                        "DivisionHeadingLevel3": None,
                    })
                    counter += 1

            for title in division.findall("uslm:title", ns):
                num_title = title.find("uslm:num", ns)
                title_text = num_title.text if num_title is not None else None

                for appropriation in title.findall("uslm:appropriations", ns):
                    heading_appr = appropriation.find("uslm:heading", ns)
                    subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
                    subheading_1 = ' '
                    if subheading_appr_1:
                        for subheading_appr in subheading_appr_1:
                            subheading_1_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                            subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
                    appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
                    if appropriation_intermediate:
                        for appropriation_level2 in appropriation_intermediate:
                            heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                            subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                            subheading_2 = ' '
                            if subheading_appr_2:
                                for subheading_appr in subheading_appr_2:
                                    subheading_2_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                    subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                            appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                            if appropriation_small:
                                for appropriation_level3 in appropriation_small:
                                    heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                                    subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                                    subheading_3 =' '
                                    if subheading_appr_3:
                                        for subheading_appr in subheading_appr_3:
                                            subheading_3_text = str(get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                            subheading_3 = str(subheading_3 or "") + str(subheading_3_text or "")
                                    appr3_content = appropriation_level3.find("uslm:content", ns)
                                    if appr3_content:
                                        appr_small_text = get_clean_text(appr3_content)
                                    else:
                                        appr_small_text = get_clean_text(appropriation_level3,"appr")
                                    results["Divisions"].append({
                                        "counter": counter,
                                        "LawIdentifier": law_identifiers,
                                        "approvedDate": approved_date,
                                        "LawTitle": law_title,
                                        "LawType": law_type,
                                        "Division": div_title_text,
                                        "Title": title_text,
                                        "SubTitle": None,
                                        "Chapter": None,
                                        "SubChapter": None,
                                        "SectionNumber": None,
                                        "SectionName": None,
                                        "Text": appr_small_text,
                                        "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                                        "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "")+ str(subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                        "DivisionHeadingLevel3": (str(get_clean_text(heading_appr_3) or "")+ str(subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                                    })
                                    counter += 1
                            else:
                                appr2_content = appropriation_level2.find("uslm:content", ns)
                                if appr2_content:
                                    appr_inter_text = get_clean_text(appr2_content)
                                else:
                                    appr_inter_text = get_clean_text(appropriation_level2, "appr")

                                results["Divisions"].append({
                                    "counter": counter,
                                    "LawIdentifier": law_identifiers,
                                    "approvedDate": approved_date,
                                    "LawTitle": law_title,
                                    "LawType": law_type,
                                    "Division": div_title_text,
                                    "Title": title_text,
                                    "SubTitle": None,
                                    "Chapter": None,
                                    "SubChapter": None,
                                    "SectionNumber": None,
                                    "SectionName": None,
                                    "Text": appr_inter_text,
                                    "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                                    "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "")+ str(subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                    "DivisionHeadingLevel3": None,
                                })
                                counter += 1

                    else:
                        appr_content = appropriation.find("uslm:content", ns)
                        if appr_content:
                            division_text = get_clean_text(appr_content)
                        else:
                            division_text = get_clean_text(appropriation, "appr")

                        results["Divisions"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": div_title_text,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": None,
                            "SubChapter": None,
                            "SectionNumber": None,
                            "SectionName": None,
                            "Text": division_text,
                            "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "")+ str(subheading_1 or "")).strip() if heading_appr is not None else None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                subtitles = title.findall("uslm:subtitle", ns)
                if subtitles:
                    for subtitle in subtitles:
                        num_subtitle = subtitle.find("uslm:num", ns)
                        subtitle_text = num_subtitle.text if num_subtitle is not None else None

                        for level in subtitle.findall("uslm:level", ns):
                            for section in level.findall("uslm:section", ns):
                                num, heading, text = process_section(section, ns)
                                results["Sections"].append({
                                    "counter": counter,
                                    "LawIdentifier": law_identifiers,
                                    "approvedDate": approved_date,
                                    "LawTitle": law_title,
                                    "LawType": law_type,
                                    "Division": div_title_text,
                                    "Title": title_text,
                                    "SubTitle": subtitle_text,
                                    "Chapter": None,
                                    "SubChapter": None,
                                    "SectionNumber": get_clean_text(num) if num is not None else None,
                                    "SectionName": get_clean_text(heading) if heading is not None else None,
                                    "Text": text if text else None,
                                    "DivisionHeadingLevel1": None,
                                    "DivisionHeadingLevel2": None,
                                    "DivisionHeadingLevel3": None,
                                })
                                counter += 1

                        for section in subtitle.findall("uslm:section", ns):
                            num, heading, text = process_section(section, ns)
                            num, flagged = apply_section_number_correction(num, law_identifiers, get_clean_text(heading) if heading is not None else "", text)

                            results["Sections"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": div_title_text,
                                "Title": title_text,
                                "SubTitle": subtitle_text,
                                "Chapter": None,
                                "SubChapter": None,
                                "SectionNumber": num if flagged else get_clean_text(num) if num is not None else None,
                                "SectionName": get_clean_text(heading) if heading is not None else None,
                                "Text": text if text else None,
                                "DivisionHeadingLevel1": None,
                                "DivisionHeadingLevel2": None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

                for level in title.findall("uslm:level", ns):
                    for section in level.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": div_title_text,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": None,
                            "SubChapter": None,
                            "SectionNumber": get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                for section in title.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": div_title_text,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": None,
                            "SubChapter": None,
                            "SectionNumber": get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                for chapter in title.findall("uslm:chapter", ns):
                    num_chapter = chapter.find("uslm:num", ns)
                    chapter_text = num_chapter.text if num_chapter is not None else None

                    for level in title.findall("uslm:level", ns):
                        for section in level.findall("uslm:section", ns):
                            num, heading, text = process_section(section, ns)
                            results["Sections"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": div_title_text,
                                "Title": title_text,
                                "SubTitle": None,
                                "Chapter": chapter_text,
                                "SubChapter": None,
                                "SectionNumber": get_clean_text(num) if num is not None else None,
                                "SectionName": get_clean_text(heading) if heading is not None else None,
                                "Text": text if text else None,
                                "DivisionHeadingLevel1": None,
                                "DivisionHeadingLevel2": None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

                    for section in title.findall("uslm:section", ns):
                        num, heading, text = process_section(section, ns)
                        results["Sections"].append({
                            "counter": counter,
                            "LawIdentifier": law_identifiers,
                            "approvedDate": approved_date,
                            "LawTitle": law_title,
                            "LawType": law_type,
                            "Division": div_title_text,
                            "Title": title_text,
                            "SubTitle": None,
                            "Chapter": chapter_text,
                            "SubChapter": None,
                            "SectionNumber": get_clean_text(num) if num is not None else None,
                            "SectionName": get_clean_text(heading) if heading is not None else None,
                            "Text": text if text else None,
                            "DivisionHeadingLevel1": None,
                            "DivisionHeadingLevel2": None,
                            "DivisionHeadingLevel3": None,
                        })
                        counter += 1

                    for appropriation in title.findall("uslm:appropriations", ns):
                        heading_appr = appropriation.find("uslm:heading", ns)
                        subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
                        subheading_1 = ' '
                        if subheading_appr_1:
                            for subheading_appr in subheading_appr_1:
                                subheading_1_text = str(
                                    get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
                        appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
                        if appropriation_intermediate:
                            for appropriation_level2 in appropriation_intermediate:
                                heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                                subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                                subheading_2 = ' '
                                if subheading_appr_2:
                                    for subheading_appr in subheading_appr_2:
                                        subheading_2_text = str(
                                            get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                        subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                                appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                                if appropriation_small:
                                    for appropriation_level3 in appropriation_small:
                                        heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                                        subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                                        subheading_3 = ' '
                                        if subheading_appr_3:
                                            for subheading_appr in subheading_appr_3:
                                                subheading_3_text = str(
                                                    get_clean_text(
                                                        subheading_appr)) if subheading_appr is not None else ''
                                                subheading_3 = str(subheading_3 or "") + str(subheading_3_text or "")
                                        appr3_content = appropriation_level3.find("uslm:content", ns)
                                        if appr3_content:
                                            appr_small_text = get_clean_text(appr3_content)
                                        else:
                                            appr_small_text = get_clean_text(appropriation_level3, "appr")
                                        results["Divisions"].append({
                                            "counter": counter,
                                            "LawIdentifier": law_identifiers,
                                            "approvedDate": approved_date,
                                            "LawTitle": law_title,
                                            "LawType": law_type,
                                            "Division": div_title_text,
                                            "Title": title_text,
                                            "SubTitle": None,
                                            "Chapter": chapter_text,
                                            "SubChapter": None,
                                            "SectionNumber": None,
                                            "SectionName": None,
                                            "Text": appr_small_text,
                                            "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                                subheading_1 or "")).strip() if heading_appr is not None else None,
                                            "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                                subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                            "DivisionHeadingLevel3": (str(get_clean_text(heading_appr_3) or "") + str(
                                                subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                                        })
                                        counter += 1
                                else:
                                    appr2_content = appropriation_level2.find("uslm:content", ns)
                                    if appr2_content:
                                        appr_inter_text = get_clean_text(appr2_content)
                                    else:
                                        appr_inter_text = get_clean_text(appropriation_level2, "appr")

                                    results["Divisions"].append({
                                        "counter": counter,
                                        "LawIdentifier": law_identifiers,
                                        "approvedDate": approved_date,
                                        "LawTitle": law_title,
                                        "LawType": law_type,
                                        "Division": div_title_text,
                                        "Title": title_text,
                                        "SubTitle": None,
                                        "Chapter": chapter_text,
                                        "SubChapter": None,
                                        "SectionNumber": None,
                                        "SectionName": None,
                                        "Text": appr_inter_text,
                                        "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                            subheading_1 or "")).strip() if heading_appr is not None else None,
                                        "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                            subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                        "DivisionHeadingLevel3": None,
                                    })
                                    counter += 1

                        else:
                            appr_content = appropriation.find("uslm:content", ns)
                            if appr_content:
                                division_text = get_clean_text(appr_content)
                            else:
                                division_text = get_clean_text(appropriation, "appr")

                            results["Divisions"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": div_title_text,
                                "Title": title_text,
                                "SubTitle": None,
                                "Chapter": chapter_text,
                                "SubChapter": None,
                                "SectionNumber": None,
                                "SectionName": None,
                                "Text": division_text,
                                "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                    subheading_1 or "")).strip() if heading_appr is not None else None,
                                "DivisionHeadingLevel2": None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

                for part in title.findall("uslm:part", ns):
                    for chapter in part.findall("uslm:chapter", ns):
                        num_chapter = chapter.find("uslm:num", ns)
                        chapter_text = num_chapter.text if num_chapter is not None else None

                        for level in title.findall("uslm:level", ns):
                            for section in level.findall("uslm:section", ns):
                                num, heading, text = process_section(section, ns)
                                results["Sections"].append({
                                    "counter": counter,
                                    "LawIdentifier": law_identifiers,
                                    "approvedDate": approved_date,
                                    "LawTitle": law_title,
                                    "LawType": law_type,
                                    "Division": div_title_text,
                                    "Title": title_text,
                                    "SubTitle": None,
                                    "Chapter": chapter_text,
                                    "SubChapter": None,
                                    "SectionNumber": get_clean_text(num) if num is not None else None,
                                    "SectionName": get_clean_text(heading) if heading is not None else None,
                                    "Text": text if text else None,
                                    "DivisionHeadingLevel1": None,
                                    "DivisionHeadingLevel2": None,
                                    "DivisionHeadingLevel3": None,
                                })
                                counter += 1

                        for section in title.findall("uslm:section", ns):
                            num, heading, text = process_section(section, ns)
                            results["Sections"].append({
                                "counter": counter,
                                "LawIdentifier": law_identifiers,
                                "approvedDate": approved_date,
                                "LawTitle": law_title,
                                "LawType": law_type,
                                "Division": div_title_text,
                                "Title": title_text,
                                "SubTitle": None,
                                "Chapter": chapter_text,
                                "SubChapter": None,
                                "SectionNumber": get_clean_text(num) if num is not None else None,
                                "SectionName": get_clean_text(heading) if heading is not None else None,
                                "Text": text if text else None,
                                "DivisionHeadingLevel1": None,
                                "DivisionHeadingLevel2": None,
                                "DivisionHeadingLevel3": None,
                            })
                            counter += 1

                        for appropriation in title.findall("uslm:appropriations", ns):
                            heading_appr = appropriation.find("uslm:heading", ns)
                            subheading_appr_1 = appropriation.findall("uslm:subheading", ns)
                            subheading_1 = ' '
                            if subheading_appr_1:
                                for subheading_appr in subheading_appr_1:
                                    subheading_1_text = str(
                                        get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                    subheading_1 = str(subheading_1 or "") + str(subheading_1_text or "")
                            appropriation_intermediate = appropriation.findall("uslm:appropriations", ns)
                            if appropriation_intermediate:
                                for appropriation_level2 in appropriation_intermediate:
                                    heading_appr_2 = appropriation_level2.find("uslm:heading", ns)
                                    subheading_appr_2 = appropriation_level2.findall("uslm:subheading", ns)
                                    subheading_2 = ' '
                                    if subheading_appr_2:
                                        for subheading_appr in subheading_appr_2:
                                            subheading_2_text = str(
                                                get_clean_text(subheading_appr)) if subheading_appr is not None else ''
                                            subheading_2 = str(subheading_2 or "") + str(subheading_2_text or "")
                                    appropriation_small = appropriation_level2.findall("uslm:appropriations", ns)
                                    if appropriation_small:
                                        for appropriation_level3 in appropriation_small:
                                            heading_appr_3 = appropriation_level3.find("uslm:heading", ns)
                                            subheading_appr_3 = appropriation_level3.findall("uslm:subheading", ns)
                                            subheading_3 = ' '
                                            if subheading_appr_3:
                                                for subheading_appr in subheading_appr_3:
                                                    subheading_3_text = str(
                                                        get_clean_text(
                                                            subheading_appr)) if subheading_appr is not None else ''
                                                    subheading_3 = str(subheading_3 or "") + str(
                                                        subheading_3_text or "")
                                            appr3_content = appropriation_level3.find("uslm:content", ns)
                                            if appr3_content:
                                                appr_small_text = get_clean_text(appr3_content)
                                            else:
                                                appr_small_text = get_clean_text(appropriation_level3, "appr")
                                            results["Divisions"].append({
                                                "counter": counter,
                                                "LawIdentifier": law_identifiers,
                                                "approvedDate": approved_date,
                                                "LawTitle": law_title,
                                                "LawType": law_type,
                                                "Division": div_title_text,
                                                "Title": title_text,
                                                "SubTitle": None,
                                                "Chapter": chapter_text,
                                                "SubChapter": None,
                                                "SectionNumber": None,
                                                "SectionName": None,
                                                "Text": appr_small_text,
                                                "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                                    subheading_1 or "")).strip() if heading_appr is not None else None,
                                                "DivisionHeadingLevel2": (
                                                            str(get_clean_text(heading_appr_2) or "") + str(
                                                        subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                                "DivisionHeadingLevel3": (
                                                            str(get_clean_text(heading_appr_3) or "") + str(
                                                        subheading_3 or "")).strip() if heading_appr_3 is not None else None,
                                            })
                                            counter += 1
                                    else:
                                        appr2_content = appropriation_level2.find("uslm:content", ns)
                                        if appr2_content:
                                            appr_inter_text = get_clean_text(appr2_content)
                                        else:
                                            appr_inter_text = get_clean_text(appropriation_level2, "appr")

                                        results["Divisions"].append({
                                            "counter": counter,
                                            "LawIdentifier": law_identifiers,
                                            "approvedDate": approved_date,
                                            "LawTitle": law_title,
                                            "LawType": law_type,
                                            "Division": div_title_text,
                                            "Title": title_text,
                                            "SubTitle": None,
                                            "Chapter": chapter_text,
                                            "SubChapter": None,
                                            "SectionNumber": None,
                                            "SectionName": None,
                                            "Text": appr_inter_text,
                                            "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                                subheading_1 or "")).strip() if heading_appr is not None else None,
                                            "DivisionHeadingLevel2": (str(get_clean_text(heading_appr_2) or "") + str(
                                                subheading_2 or "")).strip() if heading_appr_2 is not None else None,
                                            "DivisionHeadingLevel3": None,
                                        })
                                        counter += 1

                            else:
                                appr_content = appropriation.find("uslm:content", ns)
                                if appr_content:
                                    division_text = get_clean_text(appr_content)
                                else:
                                    division_text = get_clean_text(appropriation, "appr")

                                results["Divisions"].append({
                                    "counter": counter,
                                    "LawIdentifier": law_identifiers,
                                    "approvedDate": approved_date,
                                    "LawTitle": law_title,
                                    "LawType": law_type,
                                    "Division": div_title_text,
                                    "Title": title_text,
                                    "SubTitle": None,
                                    "Chapter": chapter_text,
                                    "SubChapter": None,
                                    "SectionNumber": None,
                                    "SectionName": None,
                                    "Text": division_text,
                                    "DivisionHeadingLevel1": (str(get_clean_text(heading_appr) or "") + str(
                                        subheading_1 or "")).strip() if heading_appr is not None else None,
                                    "DivisionHeadingLevel2": None,
                                    "DivisionHeadingLevel3": None,
                                })
                                counter += 1

    return results

def create_xlsx_output_from_json(jsonfile,final_output_dir,uslm_basename,formatted_time):

    # Convert to DataFrames
    sections_df = pd.DataFrame(jsonfile["Sections"])
    divisions_df = pd.DataFrame(jsonfile["Divisions"])

    sections_df["EntryType"] = "Section"
    divisions_df["EntryType"] = "Division"

    all_columns = ["EntryType", "counter", "LawIdentifier", "approvedDate", "LawTitle", "LawType",
                   "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
                   "SectionName", "Text", "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3"]

    sections_df = sections_df.reindex(columns=all_columns)
    divisions_df = divisions_df.reindex(columns=all_columns)

    combined_df = pd.concat([sections_df, divisions_df], ignore_index=True)
    combined_df["LawNumber"] = combined_df["LawIdentifier"].str.extract(r'(\d+)$').astype(int)
    combined_df = combined_df.sort_values(["LawNumber", "counter"])

    ##--- Classification Logic Sampling

    exclude_section_names = ["sense of congress.", "sunset.", "severability.", "short title.", "table of contents.", "short title; table of contents."]
    considered_entries = ~combined_df["SectionName"].fillna("").str.lower().isin([x.lower() for x in exclude_section_names])

    exclude_joint_res_wording = ["providing for congressional disapproval under chapter 8 of title 5"]
    joint_res_pattern = "|".join([re.escape(x.lower()) for x in exclude_joint_res_wording])


    considered_entries2 = ~combined_df["LawTitle"].fillna("").str.lower().str.contains(joint_res_pattern, regex=True)
    # print(considered_entries2)

    combined_filter = considered_entries & considered_entries2
    considered_sample_idx = combined_df[combined_filter].sample(n=600).index

    combined_df["Selection"] = 0
    combined_df.loc[considered_sample_idx, "Selection"] = 1

    random_order = np.random.permutation(np.arange(1, 601))
    combined_df["Order"] = None
    combined_df.loc[considered_sample_idx, "Order"] = random_order

    df_size = len(combined_df)

    combined_df["OriginalOrder"] = np.arange(1,df_size+1)

    combined_df = combined_df[["OriginalOrder","EntryType", "Selection", "Order", "LawIdentifier", "LawType", "LawTitle", "approvedDate",
                               "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
                               "SectionName", "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
                               "Text"]]

    # Save to Excel
    combined_df.to_excel(final_output_dir + os.path.sep + uslm_basename + '_' + formatted_time + ".xlsx", index=False,
                         engine='openpyxl')
    print("File Saved Successfully : ")
    print("Directory: {}".format(final_output_dir))
    print("Filename: {}".format(uslm_basename + '_' + formatted_time + ".xlsx"))
    return combined_df


if __name__ == "__main__":
    timestamp = time.time()
    formatted_time = datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y-%HH-%MM-%SS')

    config = configparser.ConfigParser()
    config.read("config.conf")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    mode = config['Dataset']['Mode']
    process_agency_list = config['Dataset']['agency']

    if mode =="Range":
        VolumeRange = config['Dataset']['VolumeRange']
        start = VolumeRange.split('-')[0]
        end = VolumeRange.split('-')[1]
        VolumeNumber = [i for i in range(int(start), int(end) + 1)]
    else:
        VolumeNumber = config['Dataset']['VolumeNumber'].split(',')
    datadir = config['Dataset']['datapath']
    outputdir = config['Dataset']['outputdir']

    for vol in VolumeNumber:
        print("-"*60)
        subdir = 'Volume-'+str(vol)
        uslm_basename = 'STATUTE-'+str(vol)
        file_directory = datadir
        uslm_file = file_directory + os.path.sep + uslm_basename + ".xml"

        final_output_dir = outputdir + os.path.sep + subdir
        os.makedirs(final_output_dir, exist_ok=True)

        proceed = False

        if os.path.isdir(file_directory):
            print("Directory Exists for {} - Proceeding to Check for XML File".format(subdir))
            if os.path.isfile(uslm_file):
                print("XML File Exists for {} - Proceeding to Extract Data".format(subdir))
                proceed = True
                final_output_dir = outputdir + os.path.sep + subdir
                os.makedirs(final_output_dir, exist_ok=True)
            else:
                print("XML File does not exist - Please add the correct xml file - '{}' to path : '{}'".format(uslm_basename+'.xml',file_directory))
        else:
            print("Folder does not exist - Please Create appropriate folder named : '{}' in directory : '{}' and add its corresponding xml file : '{}'".format(subdir, datadir, uslm_basename+'.xml'))

        if proceed:
            try:
                output_json = extract_public_law_from_uslm(uslm_file,vol)
                print("Extracted Data")
            except Exception:
                logger.exception("Failed to extract public laws from %s; skipping volume %s", uslm_file, vol)
                continue

            try:
                base_output_df = create_xlsx_output_from_json(output_json, final_output_dir, uslm_basename, formatted_time)
                print("Created Base Data Frame")
            except Exception:
                logger.exception("Failed to build base DataFrame for volume %s; skipping", vol)
                continue


            df_with_grouped = pd.DataFrame()
            if process_agency_list=='True' or process_agency_list:
                print("Adding Agency Related Information")
                agency_list = fetch_agency_list()
                text_columns = ['Text','DivisionHeadingLevel1','DivisionHeadingLevel2','DivisionHeadingLevel3']
                df_with_grouped = add_grouped_agencies(base_output_df, group_col='LawIdentifier', text_cols=text_columns, agency_list=agency_list)


            if df_with_grouped.empty:
                df_with_grouped = base_output_df

            df_with_grouped = df_with_grouped.fillna('(blank)')
            df_with_id = generate_and_process_id(df_with_grouped,"BaseRun")

            latest_dir = outputdir + os.path.sep + "latest"
            os.makedirs(latest_dir, exist_ok=True)

            latest_dir_vol = latest_dir + os.path.sep + subdir

            if os.path.exists(latest_dir_vol):
                shutil.rmtree(latest_dir_vol)

            # Recreate empty directory
            os.makedirs(latest_dir_vol, exist_ok=True)

            df_with_id = df_with_id[
                ["OriginalOrder", "EntryType", "Selection", "Order","UniqueKey","KeyVersion",
                 "LawIdentifier", "LawType", "LawTitle",
                 "approvedDate",
                 "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
                 "SectionName", "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
                 "Text","Agencies_Row", "Agencies_Law"]]

            df_with_id.to_excel(latest_dir_vol + os.path.sep + uslm_basename + '_' + formatted_time + ".xlsx",
                                                         index=False,
                                                         engine='openpyxl')
            print("File Saved Successfully : ")
            print("Directory: {}".format(latest_dir_vol))
            print("Filename: {}".format(uslm_basename + '_' + formatted_time + ".xlsx"))


            # repeated_keys = df_with_id['UniqueKey'].value_counts() > 1
            # repeated_keys = repeated_keys[repeated_keys]
            # if repeated_keys.empty:
            #     # Save to Excel
            #     df_with_id.to_excel(latest_dir_vol + os.path.sep + uslm_basename + '_' + formatted_time + ".xlsx",
            #                          index=False,
            #                          engine='openpyxl')
            #     print("File Saved Successfully : ")
            #     print("Directory: {}".format(latest_dir_vol))
            #     print("Filename: {}".format(uslm_basename + '_' + formatted_time + ".xlsx"))
            # else:
            #     print("")
            #     print("\n------ERROR!!! : Unique Keys are repeating----------\n")
            #     print("Count of each repeated key:\n", repeated_keys)
            #
            #     dup_rows = df_with_id[df_with_id['UniqueKey'].isin(repeated_keys.index)]
            #
            #     print("\nRows with repeated UniqueKeys:\n")
            #     print(dup_rows[['OriginalOrder', 'UniqueKey']].reset_index().rename(columns={'index': 'RowNumber'}))
            #
            #     grouped = (
            #         dup_rows.reset_index()
            #         .groupby('UniqueKey')['index']
            #         .apply(list)
            #         .reset_index(name='RowNumbers')
            #     )
            #     print("\nGrouped Row Numbers by Key:\n")
            #     print(grouped)
            #
            #     df_with_id.to_excel(latest_dir_vol + os.path.sep + uslm_basename + '_' + formatted_time + ".xlsx",
            #                         index=False,
            #                         engine='openpyxl')
            #     print("File Saved Successfully : ")
            #     print("Directory: {}".format(latest_dir_vol))
            #     print("Filename: {}".format(uslm_basename + '_' + formatted_time + ".xlsx"))


    update_all_directories()