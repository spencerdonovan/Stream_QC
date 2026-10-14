"""
Streamlit conversion of the original Flask QC dashboard.

This file now provides a Streamlit app with two tabs:
- "QC Dashboard": runs the original QC processing and shows tables
- "Profile Temperature Dashboard": provides a link/button to open the
  existing `ptemp_qc.py` Streamlit application (run separately).

Run with: `streamlit run dmp_qc_app.py`
"""

import datetime
import os
import pandas as pd
import requests
import streamlit as st
from dmp_qc import check_qc_rules_all
from ptemp_qc import render_profile_dashboard

DASHBOARD_OPTIONS = ['QC Dashboard', 'Profile Temperature Dashboard']

# ********* Load region CSV ********
df_regions = pd.read_csv("SiteList.csv")

# Streamlit host (for opening the separate ptemp_qc app) can be overridden via env
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "http://localhost:8501")


def _norm(s: str) -> str:
    return s.upper().replace("_", "").replace(".", "").replace(" ", "").strip()


df_regions_norm = df_regions.copy()
df_regions_norm["editingRegionNorm"] = df_regions_norm["editingRegion"].apply(
    _norm)


def run_qc_for_triplets(selected_triplets, start, end, interval):
    all_station_results = []
    for site_triplet in selected_triplets:
        site_triplet_encoded = site_triplet.replace(":", "%3A")
        url = (
            "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?"
            f"stationTriplets={site_triplet_encoded}&elements=WTEQ,PREC,SNWD,SNDN&duration={interval}"
            f"&beginDate={start}&endDate={end}&periodRef=END"
            f"&centralTendencyType=NONE&returnFlags=false&returnOriginalValues=true&returnSuspectData=true"
        )
        api = requests.get(url)
        if api.status_code == 200:
            data = api.json()
            if data:
                all_station_results.append(
                    {"stationTriplet": site_triplet, "data": data})
        else:
            st.warning(f"API error {api.status_code} for {site_triplet}")

    if not all_station_results:
        return None

    return check_qc_rules_all(all_station_results, df_regions)


def qc_tab_ui(show_sidebar: bool):
    st.header("❄️ Snow, SWE, & Precipitation QC Dashboard")
    st.markdown(
        'Use the sidebar to select the station(s), date range, and interval for QC processing.')

    site_config = ''
    start = None
    end = None
    interval = 'DAILY'
    run = False

    if show_sidebar:
        with st.sidebar:
            st.header('Data selection')
            st.markdown(
                '- Enter a site configuration or region name (e.g. `UTDCO`, `UINTA`, `SEUT`), or full station triplets (e.g. `364:UT:SNTL`).\n'
                '- Use commas or spaces to separate multiple entries.\n'
                '- Adjust start date and end date, default is set to 30 days.\n'
                '- Choose either DAILY or HOURLY interval.'
            )

            default_end = datetime.date.today()
            default_start = default_end - datetime.timedelta(days=30)

            with st.form(key='qc_form'):
                site_config = st.text_input(
                    'Site config (region, code, or triplets)', '')
                col1, col2 = st.columns(2)
                with col1:
                    start = st.date_input('Start date', default_start)
                with col2:
                    end = st.date_input('End date', default_end)

                interval = st.selectbox(
                    'Interval', ['DAILY', 'HOURLY'], index=0)
                run = st.form_submit_button('Run QC')

    if not run:
        return

    if start > end:
        st.error('Start date must be on or before end date.')
        return

    tokens_raw = [t.strip()
                  for t in site_config.replace(',', ' ').split() if t.strip()]
    tokens_norm = [_norm(t) for t in tokens_raw]

    if len(tokens_norm) == 1 and tokens_norm[0] == 'UTDCO':
        selected_triplets = df_regions['stationTriplet'].tolist()
    elif tokens_raw and all(':' in t for t in tokens_raw):
        selected_triplets = tokens_raw
    elif tokens_norm and all(t in set(df_regions_norm['editingRegionNorm'].unique()) for t in tokens_norm):
        selected_triplets = df_regions_norm.loc[
            df_regions_norm['editingRegionNorm'].isin(
                tokens_norm), 'stationTriplet'
        ].tolist()
    else:
        selected_triplets = []

    st.write(f'Selected stations: {len(selected_triplets)}')
    if selected_triplets:
        st.write(', '.join(selected_triplets[:10]))

    if not selected_triplets:
        st.info('No stations selected. Enter a region, config, or triplet list.')
        return

    results = run_qc_for_triplets(
        selected_triplets, start.isoformat(), end.isoformat(), interval)
    if results is None:
        st.warning('No data returned from API for selected stations/date range.')
        return

    def show_section(title, df):
        st.subheader(title)
        if df is None or df.empty:
            st.write('No violations found')
        else:
            st.dataframe(df)

    if all((results.get(k) is None or results.get(k).empty) for k in ['rule1', 'rule3', 'rule4', 'ruleZ']):
        st.success('Huzzah! No QC rule violations were found')

    show_section(
        'Rule 1 Violations: No decreases in accumulated precipitation.', results.get('rule1'))
    show_section(
        'Rule 3 Violations: No increase in SWE without corresponding increase in precipitation.', results.get('rule3'))
    show_section(
        'Rule 4 Violations: No increase in snow depth without corresponding increase in SWE.', results.get('rule4'))
    show_section(
        'Rule Z Violations: Occurrences where rho_snow = inf.', results.get('ruleZ'))
    show_section('Skipped Stations', results.get('skipped'))


def profile_tab_ui(show_sidebar: bool):
    render_profile_dashboard(show_sidebar)


def render_dashboard_header(selected_dashboard: str):
    active_style = (
        'background-color:#0d6efd;color:#ffffff;padding:10px 14px;border-radius:8px;'
        'text-align:center;font-weight:700;'
    )
    inactive_style = (
        'background-color:#f0f2f6;color:#444444;padding:10px 14px;border-radius:8px;'
        'text-align:center;font-weight:600;'
    )

    col1, col2 = st.columns([1, 1])
    col1.markdown(
        f"<div style='{active_style if selected_dashboard == DASHBOARD_OPTIONS[0] else inactive_style}'>{DASHBOARD_OPTIONS[0]}</div>",
        unsafe_allow_html=True,
    )
    col2.markdown(
        f"<div style='{active_style if selected_dashboard == DASHBOARD_OPTIONS[1] else inactive_style}'>{DASHBOARD_OPTIONS[1]}</div>",
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title='QC / Profile Dashboards', layout='wide')

    # Always run snowfall once per session
    if "has_snowed" not in st.session_state:
        st.snow()
        st.session_state["has_snowed"] = True

    # st.title('QC Dashboards')

    with st.sidebar:
        selected_dashboard = st.radio(
            'Select dashboard', DASHBOARD_OPTIONS, key='dashboard_selector')

    render_dashboard_header(selected_dashboard)

    if selected_dashboard == DASHBOARD_OPTIONS[0]:
        qc_tab_ui(show_sidebar=True)
    else:
        profile_tab_ui(show_sidebar=True)


if __name__ == '__main__':
    main()
