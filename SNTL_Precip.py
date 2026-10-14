# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
Created on Mon Jul 27 16:08:53 2026

@author: Charles.Donovan

This script interacts directly with the USDA SNOTEL REST API to pull daily precipitation 
values for a list of stations, calculates 24-hour differences, and maps the data back 
to the original station table.
"""

# from pathlib import Path
# import pandas as pd
# import requests
# from generic_fetch import fetch_json

# # File and API settings
# SITES_PATH = Path("SiteList.csv")


# # Baseline API parameters
# start_date = '2026-01-01'
# end_date = '2026-02-01'
# elements = 'PREC::1'
# interval = 'DAILY'
# periodRef = 'START'
# returnFlags = 'true'
# returnOriginalValues = 'true'
# returnSuspectData = 'true'


# # Read stations
# df_sites = pd.read_csv(SITES_PATH)
# results = []

# # Fetch data using PreparedRequest
# for site_triplet in df_sites["stationTriplet"]:

#     base_url = 'https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?'

#     url = f'{base_url}stationTriplets={site_triplet}&elements={elements}&duration={interval}&beginDate={start_date}&endDate={end_date}&periodRef={periodRef}&centralTendencyType=NONE&returnFlags={returnFlags}&returnOriginalValues={returnOriginalValues}&returnSuspectData={returnSuspectData}'

#     data = fetch_json(url)
#     print(f'fetching data from {start_date} to {end_date} for {site_triplet}')

#     if data is not None:
#         results.append(data)


# # 1. Start with an empty dictionary
# site_prec = {}
# # 2. Loop through each station name
# for name in df_sites['stationName']:
#     # 3. Create a bucket INSIDE the dictionary using the name as the key
#     site_prec[name] = []

# %%

from pathlib import Path
import pandas as pd
import requests
from generic_fetch import fetch_json


def SNTL_Precip(df_sites, start_date, end_date, elements, interval, periodRef, returnFlags, returnOriginalValues, returnSuspectData, progress_callback=None):
    """
    Fetches raw SNOTEL JSON payloads using your loop structure, extracts the data dictionary,
    and assigns float('nan') to missing records. Calculates daily precipitation from cumulative.
    """
    results = []

    # --- YOUR ORIGINAL LOOP (Kept completely basic) ---
    for site_triplet in df_sites["stationTriplet"]:
        base_url = 'https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?'
        url = f'{base_url}stationTriplets={site_triplet}&elements={elements}&duration={interval}&beginDate={start_date}&endDate={end_date}&periodRef={periodRef}&centralTendencyType=NONE&returnFlags={returnFlags}&returnOriginalValues={returnOriginalValues}&returnSuspectData={returnSuspectData}'
        message = f'fetching data from {start_date} to {end_date} for {site_triplet}'
        data = fetch_json(url)
        print(message)
        if progress_callback is not None:
            progress_callback(message)
        if data is not None:
            results.append(data)
    # --------------------------------------------------

    snotel_dict = {}

    # Parallel parsing loop matching your original code style
    for (_, row), station_json in zip(df_sites.iterrows(), results):
        station_name = row['stationName']
        rows_list = []

        # 1. Unpack top-level list
        if station_json and isinstance(station_json, list) and len(station_json) > 0:
            top_block = station_json[0]

            # 2. Unpack 'data' list array
            data_list = top_block.get('data', [])
            if data_list and isinstance(data_list, list) and len(data_list) > 0:
                inner_block = data_list[0]

                # 3. Pull the 'values' list safely
                if 'values' in inner_block and inner_block['values']:
                    for entry in inner_block['values']:
                        raw_date = entry['date'].split(
                            " ")[0] if " " in entry['date'] else entry['date']

                        # --- STRICT 'VALUE' EXTRACTION ONLY (NO CLIP, NO ORIGVALUE) ---
                        if 'value' in entry and entry['value'] is not None:
                            val_inches = float(entry['value'])
                        else:
                            # Assign actual NaN marker for missing entries
                            val_inches = float('nan')

                        rows_list.append({
                            'date_pst': str(raw_date),
                            'snotel_accum_in': val_inches  # Re-labeled as cumulative accumulator
                        })

        # Convert to a DataFrame and map the tracking trend
        df_sntl = pd.DataFrame(rows_list) if rows_list else pd.DataFrame(
            columns=['date_pst', 'snotel_accum_in'])

        if not df_sntl.empty:
            # Sort chronologically to make sure diff calculations are sequential
            df_sntl = df_sntl.sort_values(by='date_pst').reset_index(drop=True)

            # Calculate daily interval data by subtracting the previous day's value
            df_sntl['snotel_precip_in'] = df_sntl['snotel_accum_in'].diff()

            # The first day of the request will natively become NaN because it has no historical baseline day
            # If you want to assume the first day's increment equals its baseline total, uncomment below:
            # df_sntl['snotel_precip_in'] = df_sntl['snotel_precip_in'].fillna(df_sntl['snotel_accum_in'])

        else:
            df_sntl['snotel_precip_in'] = float('nan')

        snotel_dict[station_name] = df_sntl

    return snotel_dict


if __name__ == "__main__":
    SITES_PATH = Path("SiteList.csv")

    # Baseline API parameters matching your precise configuration
    start_date = '2026-01-01'
    end_date = '2026-02-01'
    elements = 'PREC::1'
    interval = 'DAILY'
    periodRef = 'START'
    returnFlags = 'true'
    returnOriginalValues = 'true'
    returnSuspectData = 'true'

    df_sites = pd.read_csv(SITES_PATH)
    sntl_data = SNTL_Precip(df_sites, start_date, end_date, elements,
                            interval, returnFlags, returnOriginalValues, returnSuspectData)

    print("\n--- Final Verification Check ---")
    for name, df in sntl_data.items():
        print(f"Station: {name} | Saved Records Count: {len(df)}")
