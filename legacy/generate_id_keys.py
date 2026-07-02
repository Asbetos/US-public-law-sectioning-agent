import pandas as pd
import re
import os
import glob
import numpy as np
import configparser
import shutil
import time
from datetime import datetime
from pathlib import Path


def division_to_code(value):
    if pd.isna(value) or not str(value).strip():
        return "000"
    value = str(value).strip().upper()
    match = re.match(r"DIVISION\s+([A-Z])", value)
    if match:
        return f"{ord(match.group(1)) - ord('A') + 1:03d}"
    match = re.match(r"([A-Z])", value)
    if match:
        return f"{ord(match.group(1)) - ord('A') + 1:03d}"
    return "000"

def subtitle_to_code(value):
    if pd.isna(value) or not str(value).strip():
        return "000"
    value = str(value).strip().upper()
    match = re.match(r"SUBTITLE\s+([A-Z])", value)
    if match:
        return f"{ord(match.group(1)) - ord('A') + 1:03d}"
    match = re.match(r"([A-Z])", value)
    if match:
        return f"{ord(match.group(1)) - ord('A') + 1:03d}"
    return "000"

def full_roman_to_int(roman):
    roman_numerals = {
        'M': 1000, 'CM': 900, 'D': 500, 'CD': 400,
        'C': 100, 'XC': 90, 'L': 50, 'XL': 40,
        'X': 10, 'IX': 9, 'V': 5, 'IV': 4, 'I': 1
    }
    roman = str(roman).strip().upper()
    i, result = 0, 0
    while i < len(roman):
        if i+1 < len(roman) and roman[i:i+2] in roman_numerals:
            result += roman_numerals[roman[i:i+2]]
            i += 2
        elif roman[i] in roman_numerals:
            result += roman_numerals[roman[i]]
            i += 1
        else:
            return 0
    return result

def alpha_code(value, prefix=None):
    if pd.isna(value) or not str(value).strip():
        return "000"
    value = str(value).strip().upper()
    if prefix:
        match = re.match(rf"{prefix}\s+([A-Z]+)", value)
        if match:
            letters = match.group(1)
        else:
            letters = value
    else:
        letters = value
    code = 0
    for i, ch in enumerate(reversed(letters)):
        if 'A' <= ch <= 'Z':
            code += (ord(ch) - ord('A') + 1) * (26 ** i)
        else:
            return "000"
    return f"{code:03d}"

def roman_or_numeric_code(value, prefix=None):
    """Handles values that may be roman numerals or numbers (for Title/Chapter)."""
    if pd.isna(value) or not str(value).strip():
        return "000"
    value = str(value).strip().upper()

    # Remove prefix if present, e.g., "TITLE IV" or "CHAPTER 5"
    if prefix:
        match = re.match(rf"{prefix}\s+([A-Z0-9]+)", value)
        if match:
            value = match.group(1)

    # --- Numeric case ---
    if value.isdigit():
        return f"{int(value):03d}"

    # --- Roman numeral case ---
    roman_numerals = {'I', 'V', 'X', 'L', 'C', 'D', 'M'}
    if all(ch in roman_numerals for ch in value):
        return f"{full_roman_to_int(value):03d}"

    # --- Fallback ---
    return "000"



def clean_and_format_section_fixed(text):
    if pd.isna(text) or text=='(blank)':
        return '000000000000001'
        return '000000'
    text = str(text).strip().upper()
    text = re.sub(r'^(SECTION|SEC\.?)\s*', '', text)
    text = ''.join(filter(str.isalnum, text))

    match = re.match(r"^(\d+)([A-Z]*)$", text)
    if match:
        num_part = match.group(1)
        alpha_part = match.group(2)

        total_len = 15
        num_len = total_len - len(alpha_part)
        num_part = num_part.zfill(num_len)[:num_len]  # ensure numeric fits
        return num_part + alpha_part[:total_len - len(num_part)]
    else:
        return text[:6].zfill(6)

def handle_division_headings(text):
    if pd.isna(text):
        return '00001'

    return str(division_mapper_json.get(text.lower())).zfill(5)


# --- Congress/Session derivation (legacy vols <=63; matches
#     cleaned_unique_key_processing.py so a single volume may span sessions) ---

def clean_date_col(s):
    """Parse a Series of approved-date strings to Timestamps (tolerant)."""
    def parse_one_date(x):
        if pd.isna(x):
            return pd.NaT
        x = str(x).replace("\xa0", " ").strip()
        x = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", x, flags=re.IGNORECASE)
        match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", x)
        if match:
            month, day, year = match.groups()
            return pd.to_datetime(f"{month} {day} {year}", errors="coerce")
        return pd.to_datetime(x, errors="coerce")

    return s.apply(parse_one_date)


def map_approved_date_to_congress(approved_dates, congress_df):
    """Map each approved date to (Congress, Session) via the date-range table.

    ``congress_df`` columns: Congress, Session, BeginDate, AdjournDate|EndDate.
    On a boundary date, the session with the latest BeginDate wins.
    """
    congress_lookup = congress_df.copy()
    end_col = "AdjournDate" if "AdjournDate" in congress_lookup.columns else "EndDate"
    congress_lookup["BeginDate"] = clean_date_col(congress_lookup["BeginDate"])
    congress_lookup[end_col] = clean_date_col(congress_lookup[end_col]).fillna(pd.Timestamp.max)

    approved_dates = clean_date_col(approved_dates)
    results = []
    for date in approved_dates:
        if pd.isna(date):
            results.append({"Congress": None, "Session": None})
            continue
        match = congress_lookup[
            (congress_lookup["BeginDate"] <= date) & (congress_lookup[end_col] >= date)
        ]
        if match.empty:
            results.append({"Congress": None, "Session": None})
        else:
            match = match.sort_values("BeginDate", ascending=False)
            results.append({
                "Congress": match.iloc[0]["Congress"],
                "Session": match.iloc[0]["Session"],
            })
    return pd.DataFrame(results, index=approved_dates.index)


def generate_unique_key_legacy(row):
    """Updated 11-segment key for legacy volumes (<=63):
    VOL-CONGRESS-SESSION-LAW-DIV-TITLE-SUBTITLE-CHAP-SUBCHAP-{S|D}-{sec/div}.
    Congress+Session disambiguate laws that share a number across sessions.
    """
    volume = f"{int(row['VolumeNumber']):03d}"
    match = re.search(r'(\d+)[–-](\d+)', str(row['LawIdentifier']))
    law = int(match.group(2)) if match else 0

    congress = row.get('Congress')
    session = row.get('Session')
    Congress = f"{int(congress):03d}" if pd.notna(congress) else "000"
    if pd.isna(session):
        Session = "0"
    else:
        try:
            Session = str(int(session))          # regular session: 1,2,3,4
        except (ValueError, TypeError):
            Session = str(session).strip()        # special session label: S1, S2
    Law = f"{law:03d}"

    DDD = alpha_code(row.get('Division'), prefix="DIVISION")
    TTT = roman_or_numeric_code(row.get('Title'), prefix="TITLE")
    SSS = alpha_code(row.get('SubTitle'), prefix="SUBTITLE")
    CCC = roman_or_numeric_code(row.get('Chapter'), prefix="CHAPTER")
    UUU = alpha_code(row.get('SubChapter'), prefix="Subchapter")

    I = 'S' if str(row['EntryType']).strip().lower() == 'section' else 'D'
    if I == 'S':
        sec_div_id = clean_and_format_section_fixed(row.get('SectionNumber'))
    else:
        sec_div_id = (
            handle_division_headings(row.get('DivisionHeadingLevel1')) + '-'
            + handle_division_headings(row.get('DivisionHeadingLevel2')) + '-'
            + handle_division_headings(row.get('DivisionHeadingLevel3'))
        )

    return (
        f"{volume}-{Congress}-{Session}-{Law}-{DDD}-{TTT}-{SSS}-"
        f"{CCC}-{UUU}-{I}-{sec_div_id}"
    )


# --- Key Generation Function ---

def generate_unique_key(row):
    # Extract Volume and Law Number
    match = re.search(r'(\d+)[–-](\d+)', str(row['LawIdentifier']))
    volume = int(match.group(1)) if match else 0
    law = int(match.group(2)) if match else 0

    VVV = f"{volume:03d}"
    LLL = f"{law:03d}"
    # DDD = division_to_code(row.get('Division'))
    DDD = alpha_code(row.get('Division'), prefix="DIVISION")

    # # Title - Roman numeral
    # title_raw = row.get('Title')
    # if pd.notna(title_raw):
    #     match = re.search(r'TITLE\s+([A-Z]+)', str(title_raw).upper())
    #     title_num = full_roman_to_int(match.group(1)) if match else 0
    # else:
    #     title_num = 0
    # TTT = f"{title_num:03d}" if title_num > 0 else "000"

    # Title (Roman numerals or numbers)
    TTT = roman_or_numeric_code(row.get('Title'), prefix="TITLE")

    # Subtitle - Alphabetical
    # SSS = subtitle_to_code(row.get('SubTitle'))
    SSS = alpha_code(row.get('SubTitle'), prefix="SUBTITLE")

    # # Chapter and Subchapter
    # CCC = alpha_code(row.get('Chapter'), prefix="Chapter")
    # Chapter (Roman numerals or numbers)
    CCC = roman_or_numeric_code(row.get('Chapter'), prefix="CHAPTER")
    UUU = alpha_code(row.get('SubChapter'), prefix="Subchapter")

    # Entry Type: Section or Division
    I = 'S' if str(row['EntryType']).strip().lower() == 'section' else 'D'
    if I =='S':
        # Section Number / Division ID
        sec_div_id = clean_and_format_section_fixed(row.get('SectionNumber'))
    else:
        div_id_1 = handle_division_headings(row.get('DivisionHeadingLevel1'))
        div_id_2 = handle_division_headings(row.get('DivisionHeadingLevel2'))
        div_id_3 = handle_division_headings(row.get('DivisionHeadingLevel3'))

        sec_div_id = div_id_1 + '-' + div_id_2 + '-' + div_id_3

    return f"{VVV}-{LLL}-{DDD}-{TTT}-{SSS}-{CCC}-{UUU}-{I}-{sec_div_id}"

division_mapper_json = {}

def generate_and_process_id(df,version='BaseVersion'):
    # time.sleep(3)
    config = configparser.ConfigParser()
    config.read('config.conf')

    division_mapping_root = config['Divisions']['datapath']
    division_mapping_filename = config['Divisions']['filename']

    # print("FILENAME ------ : ",os.path.join(division_mapping_root,division_mapping_filename))

    division_mapping_df = pd.read_excel(os.path.join(division_mapping_root,division_mapping_filename) + '.xlsx',engine='openpyxl')
    divisionheadings_json = dict(
        zip(division_mapping_df['Text_Heading'].str.lower(), division_mapping_df['Mapping_ID'])
    )

    divisionheadings1 = df['DivisionHeadingLevel1'].unique()
    divisionheading2 = df['DivisionHeadingLevel2'].unique()
    divisionheadings3 = df['DivisionHeadingLevel3'].unique()

    divisionheadings = list(divisionheadings1) + list(divisionheading2) + list(divisionheadings3)

    divisionheadings = pd.Series(divisionheadings).dropna().str.lower().unique()


    for heading in divisionheadings:
        mapping_id = divisionheadings_json.get(heading, None)
        if not mapping_id:
            divisionheadings_json[heading] = len(divisionheadings_json)+1

    division_mapping_df = pd.DataFrame(list(divisionheadings_json.items()), columns=['Text_Heading', 'Mapping_ID'])
    division_mapping_df.to_excel(os.path.join(division_mapping_root,division_mapping_filename) + '.xlsx', index=False)

    path = os.path.join(division_mapping_root, division_mapping_filename) + ".xlsx"
    division_mapping_df = pd.DataFrame(list(divisionheadings_json.items()),
                                       columns=["Text_Heading", "Mapping_ID"])
    # atomic_to_excel(division_mapping_df, path)

    global division_mapper_json
    division_mapper_json = divisionheadings_json  # the actual dictionary mapping

    df['UniqueKey'] = df.apply(generate_unique_key, axis=1)
    df['KeyVersion'] = version

    # df = df.fillna(value='(blank)')

    return df




def update_all_directories():
    timestamp = time.time()
    formatted_time = datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y-%HH-%MM-%SS')

    config = configparser.ConfigParser()
    config.read('config.conf')
    dir_latest = config['ExcelDir']['base_latest']
    dir_coded = config['ExcelDir']['base_coded']

    xlsx_files_latest = glob.glob(os.path.join(dir_latest, "**", "*.xlsx"), recursive=True)
    xlsx_files_coded = glob.glob(os.path.join(dir_coded, "**", "*.xlsx"), recursive=True)

    xlsx_files = xlsx_files_latest + xlsx_files_coded
    xlsx_files = sorted(xlsx_files)

    for filename in xlsx_files:
        print("-------------")
        print(filename)

        # CURRENT_DIR = Path(filename).resolve().parent
        # print(CURRENT_DIR)
        # print(df.head())

        if "/appr" in str(filename):
            continue

        # if not any(v in str(filename) for v in ["Volume-45", "Volume-50", "Volume-55", "Volume-65", "Volume-60", "Volume-70", "Volume-75", "Volume-80", "Volume-85", "Volume-90", "Volume-95", "Volume-100", "Volume-105",]):
        #     continue

        if not any(str(v) in str(filename) for v in [70]):
            continue

        df = pd.read_excel(filename, engine='openpyxl')
        df_with_id = generate_and_process_id(df)
        # time.sleep(3)
        columns = df_with_id.columns
        col_list = []
        for col in columns:
            # print(col)
            if col == 'UniqueKey' or col == 'KeyVersion':
                continue
            col_list.append(col)
        col_list = ["UniqueKey", "KeyVersion"] + col_list
        df_with_id = df_with_id[col_list]
        # print(col_list)

        # df_with_id = df_with_id[
        #     ["OriginalOrder", "EntryType", "Selection", "Order", "UniqueKey", "KeyVersion",
        #      "LawIdentifier", "LawType", "LawTitle",
        #      "approvedDate",
        #      "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
        #      "SectionName", "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
        #      "Text", "Agencies_Row", "Agencies_Law"]]

        repeated_keys = df_with_id['UniqueKey'].value_counts() > 1
        repeated_keys = repeated_keys[repeated_keys]
        if repeated_keys.empty:
            df_with_id['KeyVersion'] = formatted_time
            df_with_id.fillna('(blank)', inplace=True)
            df_with_id.to_excel(filename, index=False, engine='openpyxl')
            print("File Saved Successfully : ")
            print("Filename: {}".format(filename))

        else:
            print("\n------ERROR!!! : Unique Keys are repeating----------\n")


            dup_rows = df_with_id[df_with_id['UniqueKey'].isin(repeated_keys.index)]
            grouped = (
                dup_rows.reset_index()
                .groupby('UniqueKey')['index']
                .apply(list)
                .reset_index(name='RowNumbers')
            )
            print("\nGrouped Row Numbers by Key:\n")
            print(grouped)

            # --- FIX DUPLICATES BY APPENDING SUFFIX AFTER S/D ---
            print("\n------Proceeding with De-Duplication Logic----------\n")
            key_counts = {}
            fixed_keys = []

            for key in df_with_id["UniqueKey"]:
                if key not in key_counts:
                    key_counts[key] = 0
                    fixed_keys.append(key)
                else:
                    key_counts[key] += 1
                    suffix = key_counts[key]

                    # Insert suffix right after the S or D segment (8th position)
                    parts = key.split("-")
                    # parts structure:
                    # [VVV, LLL, DDD, TTT, SSS, CCC, UUU, I, sec_div]

                    I = parts[7]  # "S" or "D"
                    parts[7] = f"{I}{suffix}"  # S → S1, S2, D → D1, D2

                    new_key = "-".join(parts)
                    fixed_keys.append(new_key)

            df_with_id["UniqueKey"] = fixed_keys

            # Check if keys have actually gotten fixed
            repeated_keys = df_with_id['UniqueKey'].value_counts() > 1
            repeated_keys = repeated_keys[repeated_keys]

            if repeated_keys.empty:
                print("\nDuplicate keys have been fixed by adding suffixes after S/D.\n")
                df_with_id['KeyVersion'] = formatted_time
                df_with_id.fillna('(blank)', inplace=True)
                df_with_id.to_excel(filename, index=False, engine='openpyxl')
                print("File Saved Successfully (after fixing duplicates):")
                print("Filename: {}".format(filename))

            else:
                print("\n------ERROR!!! : Unique Keys are repeating----------\n")

                dup_rows = df_with_id[df_with_id['UniqueKey'].isin(repeated_keys.index)]
                grouped = (
                    dup_rows.reset_index()
                    .groupby('UniqueKey')['index']
                    .apply(list)
                    .reset_index(name='RowNumbers')
                )
                print("\nGrouped Row Numbers by Key:\n")
                print(grouped)







if __name__ == '__main__':
    update_all_directories()

    # timestamp = time.time()
    # formatted_time = datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y-%HH-%MM-%SS')
    #
    # config = configparser.ConfigParser()
    # config.read('config.conf')
    # print("here")
    # dir_to_check = config['KeyUpdate']['folder_to_update']
    # xlsx_files = glob.glob(os.path.join(dir_to_check, "*.xlsx"),recursive=True)
    # for filename in xlsx_files:
    #     # print(filename)
    #     df = pd.read_excel(filename, engine='openpyxl')
    #     CURRENT_DIR = Path(filename).resolve().parent
    #     print(CURRENT_DIR)
    #     filename = filename.replace('.xlsx','')
    #     filename = filename.replace(str(CURRENT_DIR) ,'')
    #     filename = filename.replace('/' ,'')
    #     print(filename)
    #     print("-------------")
    #     df_with_id = generate_and_process_id(df)
    #
    #     # df_with_id = df_with_id[
    #     #     ["OriginalOrder", "EntryType", "Selection", "Order", "UniqueKey",
    #     #      "LawIdentifier", "LawType", "LawTitle",
    #     #      "approvedDate",
    #     #      "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
    #     #      "SectionName", "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
    #     #      "Text", "Agencies_Row", "Agencies_Law"]]
    #
    #     # Save to Excel
    #     df_with_id.to_excel(str(CURRENT_DIR / filename) + '_' + formatted_time + ".xlsx",
    #                         index=False,
    #                         engine='openpyxl')
    #     print("File Saved Successfully : ")
    #     # print("Directory: {}".format(latest_dir_vol))
    #     print("Filename: {}".format(str(CURRENT_DIR / filename) + '_' + formatted_time + ".xlsx"))


# if __name__ == '__main__':
#
#     timestamp = time.time()
#     formatted_time = datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y-%HH-%MM-%SS')
#
#     config = configparser.ConfigParser()
#     config.read('config.conf')
#
#     mode = config['Dataset']['Mode']
#     division_mapping_root = config['Divisions']['datapath']
#     division_mapping_filename = config['Divisions']['filename']
#
#     if mode == "Range":
#         # print("here")
#         VolumeRange = config['Dataset']['VolumeRange']
#         start = VolumeRange.split('-')[0]
#         end = VolumeRange.split('-')[1]
#         # print(start)
#         # print(end)
#         VolumeNumber = [i for i in range(int(start), int(end) + 1)]
#         # print(VolumeNumber)
#     else:
#         VolumeNumber = config['Dataset']['VolumeNumber'].split(',')
#
#     datadir = config['Appropriations']['datapath']
#     outputdir = config['Dataset']['outputdir']
#
#     for vol in VolumeNumber:
#         print("-" * 60)
#         subdir = 'Volume-' + str(vol)
#         uslm_basename = 'STATUTE-' + str(vol)
#         file_directory = datadir + os.path.sep + subdir
#
#         print(file_directory)
#
#         xlsx_files = glob.glob(os.path.join(file_directory, "*.xlsx"))
#         df = pd.read_excel(xlsx_files[0], engine='openpyxl')
#
#         division_mapping_df = pd.read_excel(os.path.join(division_mapping_root, division_mapping_filename) + '.xlsx',
#                                             engine='openpyxl')
#         divisionheadings_json = dict(
#             zip(division_mapping_df['Text_Heading'].str.lower(), division_mapping_df['Mapping_ID'])
#         )
#
#         divisionheadings1 = df['DivisionHeadingLevel1'].unique()
#         divisionheading2 = df['DivisionHeadingLevel2'].unique()
#         divisionheadings3 = df['DivisionHeadingLevel3'].unique()
#
#         divisionheadings = list(divisionheadings1) + list(divisionheading2) + list(divisionheadings3)
#
#         divisionheadings = pd.Series(divisionheadings).dropna().str.lower().unique()
#
#         for heading in divisionheadings:
#             mapping_id = divisionheadings_json.get(heading, None)
#             if not mapping_id:
#                 divisionheadings_json[heading] = len(divisionheadings_json) + 1
#
#         division_mapping_df = pd.DataFrame(list(divisionheadings_json.items()), columns=['Text_Heading', 'Mapping_ID'])
#         division_mapping_df.to_excel(os.path.join(division_mapping_root, division_mapping_filename) + '.xlsx', index=False)
#
#         division_mapper_json = divisionheadings_json  # the actual dictionary mapping
#
#         df_with_id = generate_and_process_id(df)
#
#         latest_dir = outputdir + os.path.sep + "latest"
#         os.makedirs(latest_dir, exist_ok=True)
#
#         latest_dir_vol = latest_dir + os.path.sep + subdir
#
#         if os.path.exists(latest_dir_vol):
#             shutil.rmtree(latest_dir_vol)
#
#         # Recreate empty directory
#         os.makedirs(latest_dir_vol, exist_ok=True)
#
#         df_with_id = df_with_id[
#             ["OriginalOrder", "EntryType", "Selection", "Order", "UniqueKey",
#              "LawIdentifier", "LawType", "LawTitle",
#              "approvedDate",
#              "Division", "Title", "SubTitle", "Chapter", "SubChapter", "SectionNumber",
#              "SectionName", "DivisionHeadingLevel1", "DivisionHeadingLevel2", "DivisionHeadingLevel3",
#              "Text", "Agencies_Row", "Agencies_Law"]]
#
#         # Save to Excel
#         df_with_id.to_excel(latest_dir_vol + os.path.sep + uslm_basename + '_' + formatted_time + ".xlsx",
#                             index=False,
#                             engine='openpyxl')
#         print("File Saved Successfully : ")
#         print("Directory: {}".format(latest_dir_vol))
#         print("Filename: {}".format(uslm_basename + '_' + formatted_time + ".xlsx"))
