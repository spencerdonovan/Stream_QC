# %%-*- coding: utf-8 -*-
"""
Created on Mon May  5 11:30:00 2025

@author: Spencer.Donovan
"""

# Load region CSV
import numpy as np
import pandas as pd
import requests
import datetime

# Load region CSV
df_regions = pd.read_csv("SiteList.csv")

# --- QC Function ---


def check_qc_rules_all(all_station_results, df_regions):
    """
    Run QC rules across all stations in all_station_results.

    Rules:
    1. No decrease in accumulated precipitation (PREC only)
    3. No increase in SWE without corresponding increase in precipitation (PREC + WTEQ)
    4. No increase in snow depth without corresponding increase in SWE (SNWD + WTEQ)
    Z. No SWE with zero snow depth

    Returns:
        dict of DataFrames:
            {'rule1': df, 'rule3': df, 'rule4': df, 'ruleZ': df, 'skipped': df}
    """
    all_rule1, all_rule3, all_rule4, all_ruleZ = [], [], [], []
    skipped_log = []

    for station_index, station_result in enumerate(all_station_results):
        try:
            stationTriplet = station_result.get(
                "stationTriplet", f"index_{station_index}")

            if not station_result.get("data"):
                skipped_log.append(
                    {"stationTriplet": stationTriplet, "reason": "No data key in result"})
                continue

            if not isinstance(station_result["data"], list) or len(station_result["data"]) == 0:
                skipped_log.append(
                    {"stationTriplet": stationTriplet, "reason": "Malformed or empty data list"})
                continue

            station_data = station_result["data"][0].get("data", [])
            if not station_data:
                skipped_log.append(
                    {"stationTriplet": stationTriplet, "reason": "No element data inside data[0]"})
                continue

            # Build dict keyed by elementCode
            element_dict = {}
            for elem in station_data:
                if isinstance(elem, dict) and "stationElement" in elem and "elementCode" in elem["stationElement"]:
                    code = elem["stationElement"]["elementCode"]
                    element_dict[code] = elem.get("values", [])

            def safe_df(values, colname):
                if values:
                    df = pd.DataFrame(values).rename(
                        columns={"value": colname})
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df[colname] = pd.to_numeric(df[colname], errors="coerce")
                    return df[["date", colname]].dropna()
                return pd.DataFrame(columns=["date", colname])

            prec_df = safe_df(element_dict.get("PREC", []), "value_PREC")
            wteq_df = safe_df(element_dict.get("WTEQ", []), "value_WTEQ")
            snwd_df = safe_df(element_dict.get("SNWD", []), "value_SNWD")

            try:
                stationName = df_regions.loc[df_regions["stationTriplet"]
                                             == stationTriplet, "stationName"].values[0]
            except Exception:
                stationName = "Unknown"

            # Rule 1
            if not prec_df.empty:
                prec_df = prec_df.sort_values("date")
                prec_df["PREC_diff"] = prec_df["value_PREC"].diff()
                rule1 = prec_df[prec_df["PREC_diff"] < 0].copy()
                rule1["stationTriplet"] = stationTriplet
                rule1["stationName"] = stationName
                all_rule1.append(rule1)

            # Rule 3
            if not prec_df.empty and not wteq_df.empty:
                merged_pw = prec_df.merge(
                    wteq_df, on="date", how="inner").sort_values("date")
                merged_pw["PREC_diff"] = merged_pw["value_PREC"].diff()
                merged_pw["WTEQ_diff"] = merged_pw["value_WTEQ"].diff()
                rule3 = merged_pw[(merged_pw["WTEQ_diff"] > 0) & (
                    merged_pw["PREC_diff"] <= 0)].copy()
                rule3["stationTriplet"] = stationTriplet
                rule3["stationName"] = stationName
                all_rule3.append(rule3)

            # Rule 4
            if not snwd_df.empty and not wteq_df.empty:
                merged_sw = snwd_df.merge(
                    wteq_df, on="date", how="inner").sort_values("date")
                merged_sw["SNWD_diff"] = merged_sw["value_SNWD"].diff()
                merged_sw["WTEQ_diff"] = merged_sw["value_WTEQ"].diff()
                rule4 = merged_sw[(merged_sw["SNWD_diff"] > 0) & (
                    merged_sw["WTEQ_diff"] <= 0)].copy()
                rule4["stationTriplet"] = stationTriplet
                rule4["stationName"] = stationName
                all_rule4.append(rule4)

            # Rule Z
            if not snwd_df.empty and not wteq_df.empty:
                merged_sw_ruleZ = snwd_df.merge(
                    wteq_df, on="date", how="inner").sort_values("date")
                ruleZ = merged_sw_ruleZ[(merged_sw_ruleZ["value_SNWD"] <= 0) & (
                    merged_sw_ruleZ["value_WTEQ"] > 0)].copy()
                ruleZ["stationTriplet"] = stationTriplet
                ruleZ["stationName"] = stationName
                all_ruleZ.append(ruleZ)

        except Exception as e:
            skipped_log.append({"stationTriplet": station_result.get("stationTriplet", f"index_{station_index}"),
                                "reason": f"Exception: {e}"})
            continue

    return {
        "rule1": pd.concat(all_rule1, ignore_index=True) if all_rule1 else pd.DataFrame(),
        "rule3": pd.concat(all_rule3, ignore_index=True) if all_rule3 else pd.DataFrame(),
        "rule4": pd.concat(all_rule4, ignore_index=True) if all_rule4 else pd.DataFrame(),
        "ruleZ": pd.concat(all_ruleZ, ignore_index=True) if all_ruleZ else pd.DataFrame(),
        "skipped": pd.DataFrame(skipped_log) if skipped_log else pd.DataFrame(columns=["stationTriplet", "reason"]),
    }


# --- Script mode for debugging ---
if __name__ == "__main__":
    # Example: run QC for WASATCH region
    site_config = "WASATCH"

    # Normalize input (upper, strip underscores/dots)
    normalized = site_config.upper().replace("_", "").replace(".", "")

    if normalized == "UTDCO":
        selected_triplets = df_regions["stationTriplet"].tolist()
    elif normalized in df_regions["editingRegion"].str.upper().unique():
        selected_triplets = df_regions.loc[df_regions["editingRegion"].str.upper(
        ) == normalized, "stationTriplet"].tolist()
    else:
        selected_triplets = [site_config]

    all_station_results = []
    for site_triplet in selected_triplets:
        site_triplet_encoded = site_triplet.replace(":", "%3A")
        url = (
            f"https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?"
            f"stationTriplets={site_triplet_encoded}&elements=WTEQ,PREC,SNWD,SNDN&duration=DAILY"
            f"&beginDate=2025-12-01&endDate=2025-12-10&periodRef=END"
            f"&centralTendencyType=NONE&returnFlags=false&returnOriginalValues=true&returnSuspectData=true"
        )
        api = requests.get(url)
        if api.status_code == 200:
            data = api.json()
            if data:
                all_station_results.append(
                    {"stationTriplet": site_triplet, "data": data})

    results_all = check_qc_rules_all(all_station_results, df_regions)

    print("Skipped stations:")
    print(results_all["skipped"])

    if not results_all["rule1"].empty:
        print("Rule 1 violations: No decrease in accumulated precipitation:")
        print(results_all["rule1"][["date", "value_PREC",
              "PREC_diff", "stationTriplet", "stationName"]])

    if not results_all["rule3"].empty:
        print("Rule 3 violations: No increase in SWE without corresponding increase in precipitation")
        print(results_all["rule3"][["date", "PREC_diff", "WTEQ_diff",
              "value_PREC", "value_WTEQ", "stationTriplet", "stationName"]])

    if not results_all["rule4"].empty:
        print(
            "Rule 4 violations: No increase in SNWD without corresponding increase in SWE")
        print(results_all["rule4"][["date", "SNWD_diff", "WTEQ_diff",
              "value_SNWD", "value_WTEQ", "stationTriplet", "stationName"]])

    if not results_all["ruleZ"].empty:
        print(
            "Rule Z violations: ρ_<code>snow</code> = ∞")
        print(results_all["ruleZ"][["date", "value_SNWD",
              "value_WTEQ", "stationTriplet", "stationName"]])
