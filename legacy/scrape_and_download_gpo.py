import os
import time
from datetime import datetime

import pandas as pd
import requests
import xml.etree.ElementTree as ET

URL = "https://www.govinfo.gov/bulkdata/xml/STATUTE"
BASE_DOWNLOAD_URL = "https://www.govinfo.gov/bulkdata/STATUTE"
timestamp = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = f"/groups/brooksgrp/laws/us_federal_statutes/GOVINFO_Modification_Timeline_{timestamp}.xlsx" # do this inside the notes.txt
DOWNLOAD_DIR = f"/groups/brooksgrp/laws/us_federal_statutes/Updated_{timestamp}"

def scrape_name_last_modified(url: str) -> pd.DataFrame:
    headers = {
        "Accept": "application/xml",
        "User-Agent": "Mozilla/5.0",
    }

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    rows = []

    for file_elem in root.findall(".//file"):
        display_label = file_elem.findtext("displayLabel")
        last_modified = file_elem.findtext("formattedLastModifiedTime")
        is_folder = file_elem.findtext("folder")

        # Keep only numeric volume folders like 137, 136, ...
        if is_folder == "true" and display_label and display_label.isdigit():
            rows.append(
                {
                    "Name": int(display_label),
                    "Last Modified (GMT)": last_modified or "",
                }
            )

    df = pd.DataFrame(rows).drop_duplicates()

    if not df.empty:
        df = df.sort_values("Name", ascending=False).reset_index(drop=True)

    return df


def download_xml_files(df: pd.DataFrame, download_dir: str) -> None:
    os.makedirs(download_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    downloaded = 0
    skipped = 0
    failed = 0

    for vol in df["Name"].tolist():
        url = f"{BASE_DOWNLOAD_URL}/{vol}/STATUTE-{vol}.xml"
        output_path = os.path.join(download_dir, f"STATUTE-{vol}.xml")

        if os.path.exists(output_path):
            print(f"Already exists, skipping: STATUTE-{vol}.xml")
            skipped += 1
            continue

        try:
            resp = session.get(url, timeout=60)

            if resp.status_code == 404:
                print(f"Missing, skipping: STATUTE-{vol}.xml")
                skipped += 1
                continue

            resp.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(resp.content)

            print(f"Downloaded: STATUTE-{vol}.xml")
            downloaded += 1

            # optional small pause to be polite
            time.sleep(0.1)

        except requests.RequestException as e:
            print(f"Failed for volume {vol}: {e}")
            failed += 1

    print("\nDownload summary:")
    print(f"Downloaded: {downloaded}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")


def main():
    df = scrape_name_last_modified(URL)

    if df.empty:
        print("No rows found.")
        return

    df.to_excel(OUTPUT_FILE, index=False)
    print(f"Saved {len(df)} rows to {OUTPUT_FILE}")

    download_xml_files(df, DOWNLOAD_DIR)


if __name__ == "__main__":
    main()