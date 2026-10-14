"""Standalone Streamlit app for running the MRMS + SNOTEL workflow.

This file intentionally stays independent from the QC dashboard files so the
MRMS functionality can be developed and tested separately before wrapping it
into a larger dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def load_module(module_name: str, file_name: str):
    """Load a module from the workspace when the filename contains dots or is not a standard package name."""
    module_path = Path(__file__).resolve().with_name(file_name)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Could not load module {file_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mrms_25 = load_module("mrms_25", "MRMS_2.5.py")
mrms_dl = load_module("mrms_downloader_module", "MRMS_downloader.py")


APP_TITLE = "MRMS + SNOTEL Dashboard"
LOCAL_DATA_DIR = Path("mrms_local_archive")
OUTPUT_MAP_PATH = Path("mrms_station_time_series_map.html")
HOUR_STRING = "080000"


@st.cache_data(show_spinner=False)
def load_station_options() -> pd.DataFrame:
    """Return the station list used by the MRMS workflow."""
    return mrms_25.load_station_table()


def prepare_mrms_data(start_date: str, end_date: str, site_config: str, hour_string: str = HOUR_STRING, download_missing: bool = False, _progress_callback=None):
    """Load the station list, optionally download missing files, and build the merged station frames."""
    mrms_25.START_DATE_STR = start_date
    mrms_25.END_DATE_STR = end_date
    mrms_25.HOUR_STR = hour_string
    mrms_25.LOCAL_DATA_DIR = LOCAL_DATA_DIR
    mrms_25.SITES_PATH = Path("SiteList.csv")

    missing_dates = mrms_25.get_missing_dates(start_date, end_date, hour_string)
    if missing_dates and download_missing:
        first_missing = pd.Timestamp(missing_dates[0]).to_pydatetime()
        last_missing = pd.Timestamp(missing_dates[-1]).to_pydatetime()
        mrms_dl.sync_mrms_archive(first_missing, last_missing)

    stations_df = mrms_25.load_station_table()
    selected = mrms_25.filter_station_table(stations_df, site_config)

    station_frames = mrms_25.build_mrms_station_frames(selected)
    snotel_data = mrms_25.get_snotel_data(selected, progress_callback=_progress_callback)
    merged = mrms_25.merge_snotel_data(station_frames, snotel_data)

    return selected, merged, snotel_data


def build_map_object(start_date: str, end_date: str, site_config: str, hour_string: str = HOUR_STRING, progress_callback=None):
    """Build the Folium map object for the selected site configuration and date range."""
    mrms_25.START_DATE_STR = start_date
    mrms_25.END_DATE_STR = end_date
    mrms_25.HOUR_STR = hour_string
    mrms_25.LOCAL_DATA_DIR = LOCAL_DATA_DIR
    mrms_25.SITES_PATH = Path("SiteList.csv")

    stations_df = mrms_25.load_station_table()
    selected = mrms_25.filter_station_table(stations_df, site_config)
    station_frames = mrms_25.build_mrms_station_frames(selected)
    snotel_data = mrms_25.get_snotel_data(selected, progress_callback=progress_callback)
    station_frames = mrms_25.merge_snotel_data(station_frames, snotel_data)

    if not station_frames:
        return None

    return mrms_25.build_interactive_map(station_frames, snotel_data)


def build_map_html(start_date: str, end_date: str, site_config: str, hour_string: str = HOUR_STRING):
    """Create and return a fresh HTML representation of the generated MRMS map."""
    map_obj = build_map_object(start_date, end_date, site_config, hour_string)
    if map_obj is None:
        return None
    html = map_obj.get_root().render()
    OUTPUT_MAP_PATH.write_text(html, encoding="utf-8")
    return html


def render_sidebar():
    st.sidebar.header("MRMS options")

    default_end = datetime.today()
    default_start = default_end - timedelta(days=30)

    with st.sidebar.form(key="mrms_form"):
        site_config = st.text_input(
            "Site config",
            value="utdco",
            help="Examples: utdco, SWUT, 1309:UT:SNTL, or a station name.",
        )
        hour_string = st.text_input("MRMS hour", value=HOUR_STRING, max_chars=6)
        start_date = st.date_input("Start date", value=default_start)
        end_date = st.date_input("End date", value=default_end)
        run_requested = st.form_submit_button(
            "Run MRMS query",
            type="primary",
            key="run_mrms_query_button",
        )

    return site_config.strip(), start_date, end_date, hour_string.strip(), run_requested


def render_summary(stations_df: pd.DataFrame, station_frames: dict):
    station_count = len(station_frames)
    st.subheader("Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Stations matched", len(stations_df))
    col2.metric("Stations with MRMS data", station_count)
    col3.metric("Date range", f"{stations_df['stationName'].nunique()} total")

    if station_frames:
        frame_list = []
        for station_name, frame in station_frames.items():
            if frame.empty:
                continue
            frame_list.append({
                "station_name": station_name,
                "rows": len(frame),
                "avg_rqi": frame["radar_quality_index"].mean() if "radar_quality_index" in frame.columns else float("nan"),
            })

        summary_df = pd.DataFrame(frame_list)
        if not summary_df.empty:
            st.dataframe(summary_df.sort_values("station_name").reset_index(drop=True), width="stretch")


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption("Independent MRMS + SNOTEL app built from the existing archive and station helpers.")

    site_config, start_date, end_date, hour_string, run_requested = render_sidebar()

    if start_date > end_date:
        st.error("Start date must be on or before the end date.")
        return

    missing_dates = mrms_25.get_missing_dates(start_date.isoformat(), end_date.isoformat(), hour_string)
    download_complete = bool(st.session_state.get("mrms_download_complete", False))
    download_choice = "No"

    if missing_dates:
        st.warning(f"Missing MRMS archive dates: {', '.join(missing_dates)}")
        download_choice = st.radio(
            "Download missing MRMS dates?",
            ("No", "Yes"),
            index=0,
            horizontal=True,
            key="mrms_download_choice",
            help="Only appears when the selected date range includes files that are not already in the local archive.",
        )

        if download_choice == "Yes":
            if st.button("Download missing MRMS dates", key="download_missing_mrms_dates"):
                try:
                    first_missing = pd.Timestamp(missing_dates[0]).to_pydatetime()
                    last_missing = pd.Timestamp(missing_dates[-1]).to_pydatetime()
                    with st.spinner("Downloading missing MRMS dates..."):
                        mrms_dl.sync_mrms_archive(first_missing, last_missing)
                    st.session_state.mrms_download_complete = True
                    st.success("MRMS downloads complete. The Run MRMS query button is now available.")
                except Exception as exc:
                    st.session_state.mrms_download_complete = False
                    st.error(f"MRMS download failed: {exc}")

            download_complete = st.session_state.get("mrms_download_complete", False)
            if download_complete:
                st.progress(1.0, text="MRMS downloads complete — Run MRMS query is available.")
            else:
                st.info("Toggle is set to Yes. Click the Download missing MRMS dates button above before running the query.")
        else:
            st.session_state.mrms_download_complete = False

    if not run_requested:
        if missing_dates and download_choice == "Yes" and not download_complete:
            st.info("The MRMS query will stay disabled until the missing files are downloaded and marked complete.")
        else:
            st.info("Adjust the MRMS settings and click Run MRMS query to generate the map and station summary.")
        return

    status_placeholder = st.empty()

    def report_status(message: str):
        status_placeholder.caption(message)

    status_placeholder.caption("Fetching SNOTEL data from the USDA API...")

    with st.spinner("Preparing MRMS + SNOTEL data..."):
        try:
            stations_df, station_frames, snotel_data = prepare_mrms_data(
                start_date.isoformat(),
                end_date.isoformat(),
                site_config,
                hour_string,
                download_missing=(download_choice == "Yes" and bool(st.session_state.get("mrms_download_complete", False))),
                _progress_callback=report_status,
            )
        except Exception as exc:
            status_placeholder.empty()
            st.error(f"Unable to load MRMS data: {exc}")
            return

    status_placeholder.empty()

    if not station_frames:
        st.warning("No station data was produced for the selected filters. Try a wider date range or a different site configuration.")
        return

    st.subheader("Station map")
    map_obj = mrms_25.build_interactive_map(station_frames, snotel_data)
    map_html = map_obj.get_root().render()
    OUTPUT_MAP_PATH.write_text(map_html, encoding="utf-8")
    if map_obj is not None and map_html:
        st.download_button(
            label="Download map HTML",
            data=map_html,
            file_name="mrms_station_time_series_map.html",
            mime="text/html",
        )
        components.html(map_html, height=760, scrolling=True)
    else:
        st.info("No station map was generated for the current selection.")

    render_summary(stations_df, station_frames)

    st.subheader("Data preview")
    preview_rows = []
    for station_name, frame in station_frames.items():
        if frame.empty:
            continue
        preview_rows.append(frame.head(5).assign(station_name=station_name))

    if preview_rows:
        preview_df = pd.concat(preview_rows, ignore_index=True)
        preview_df = preview_df.rename(columns={"radar_only_qpe_mm": "radar_only_qpe_in"})
        st.dataframe(preview_df, width="stretch")
    else:
        st.write("No station data is available to preview.")


if __name__ == "__main__":
    main()
