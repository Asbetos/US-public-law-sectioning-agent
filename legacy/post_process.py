import os.path
import configparser

import numpy as np
import pandas as pd

config = configparser.ConfigParser()
config.read('config.conf')


def fetch_agency_list():
    datapath = config['Dataset']['datapath']
    agency_sheet = pd.read_excel(os.path.join(datapath, 'AgencyList.xlsx'))

    agencies = agency_sheet['Agency'].astype(str).str.lower().unique()
    bureaus = agency_sheet['Bureau'].astype(str).str.lower().unique()

    combined = np.unique(np.concatenate([agencies, bureaus]))
    combined = combined[combined != 'nan']

    return combined.tolist()


def find_agencies_in_row(row, agency_list, text_cols):
    matched = set()
    for col in text_cols:
        text_lower = str(row[col]).lower()
        for agency in agency_list:
            if agency in text_lower:
                matched.add(agency)
    return list(matched) if matched else np.nan


def add_grouped_agencies(df, group_col, text_cols, agency_list):
    df['Agencies_Row'] = df.apply(lambda row: find_agencies_in_row(row, agency_list, text_cols), axis=1)

    grouped_df = df.groupby(group_col)['Agencies_Row'].apply(
        lambda lists: list(set(
            agency
            for sublist in lists
            if isinstance(sublist, list)
            for agency in sublist
        ))
    ).reset_index().rename(columns={'Agencies_Row': 'Agencies_Law'})

    df = df.merge(grouped_df, on=group_col, how='left')

    return df
