import requests
import pandas as pd
import xml.etree.ElementTree as ET
import time
from datetime import datetime

URL = "https://www.govinfo.gov/bulkdata/xml/STATUTE"
timestamp = datetime.now().strftime("%Y%m%d")
OUTPUT_FILE = f"GOVINFO_Modification_Timeline_{timestamp}.xlsx"


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

        # Keep only the volume folders like 137, 136, 135...
        if is_folder == "true" and display_label and display_label.isdigit():
            rows.append({
                "Name": int(display_label),
                "Last Modified (GMT)": last_modified or ""
            })

    df = pd.DataFrame(rows).drop_duplicates()

    if not df.empty:
        df = df.sort_values("Name", ascending=False).reset_index(drop=True)

    return df


def main():
    df = scrape_name_last_modified(URL)

    if df.empty:
        print("No rows found.")
        return

    df.to_excel(OUTPUT_FILE, index=False)
    print(f"Saved {len(df)} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()