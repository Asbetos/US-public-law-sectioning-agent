import os
import glob
import configparser

import pandas as pd

config = configparser.ConfigParser()
config.read('config.conf')

mode = config['Dataset']['Mode']

if mode == "Range":
    start, end = config['Dataset']['VolumeRange'].split('-')
    VolumeNumber = list(range(int(start), int(end) + 1))
else:
    VolumeNumber = config['Dataset']['VolumeNumber'].split(',')

datadir = config['Appropriations']['datapath']
outputdir = config['Appropriations']['outputdir']


for vol in VolumeNumber:
    print("-" * 60)
    subdir = f'Volume-{vol}'
    file_directory = os.path.join(datadir, subdir)

    xlsx_files = glob.glob(os.path.join(file_directory, "*.xlsx"))
    if not xlsx_files:
        print(f"Skipping Volume {vol}: no .xlsx files found in {file_directory}")
        continue
    data = pd.read_excel(xlsx_files[0], engine='openpyxl')

    divisions = data[data['EntryType'] == 'Division'][['LawIdentifier', 'LawTitle']].drop_duplicates()
    df_sections = data[data['EntryType'] == 'Section'][['LawIdentifier', 'LawTitle']].drop_duplicates()
    appr_laws = divisions['LawIdentifier'].unique()
    df_sections["isAppropriation"] = df_sections['LawIdentifier'].isin(appr_laws)

    output_path = os.path.join(outputdir, f"Appropriations_{subdir}.xlsx")
    df_sections.to_excel(output_path, index=False)
    print(f"Appropriation Excel for Volume {vol} Generated")
