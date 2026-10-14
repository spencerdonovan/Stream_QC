# -*- coding: utf-8 -*-
"""Beginner-friendly MRMS + SNOTEL time-series map.

What this script does:
1) checks whether the MRMS files for your date range are already on disk
2) asks before downloading any missing dates
3) filters the station list by your SITE_CONFIG
4) reads local MRMS GRIB2 files and matches them to the stations
5) merges in SNOTEL precipitation values
6) builds an interactive map with one popup per station

How to use it:
- change START_DATE_STR, END_DATE_STR, and SITE_CONFIG near the top
- run this file in Python
- answer 'yes' or 'no' if files are missing
"""

from pathlib import Path
import re

import folium
import pandas as pd
import plotly.graph_objects as go
import xarray as xr

from SNTL_Precip import SNTL_Precip


# -----------------------------------------------------------------------------
# 1) User settings
# -----------------------------------------------------------------------------
START_DATE_STR = "2026-09-10"
END_DATE_STR = "2026-09-27"
HOUR_STR = "080000"
SITE_CONFIG = "utdco"
LOCAL_DATA_DIR = Path("mrms_local_archive")
SITES_PATH = Path("SiteList.csv")


def state_line_style(feature):
    """Return a static Folium style for the U.S. state outline layer."""
    return {"color": "rgba(70,70,70,0.9)", "weight": 1, "fillOpacity": 0.0, "opacity": 0.9}


# -----------------------------------------------------------------------------
# 2) Archive check
# -----------------------------------------------------------------------------
def get_missing_dates(start_date, end_date, hour_string):
    """Return a list of dates missing either the QPE or RQI file."""
    missing_dates = []

    for current_day in pd.date_range(start=start_date, end=end_date, freq="D"):
        date_text = current_day.strftime("%Y%m%d")
        timestamp = f"{date_text}-{hour_string}"

        qpe_file = LOCAL_DATA_DIR / "qpe" / f"MRMS_RadarOnly_QPE_24H_{timestamp}.grib2"
        rqi_file = LOCAL_DATA_DIR / "rqi" / f"MRMS_RQI_{timestamp}.grib2"

        if not qpe_file.exists() or not rqi_file.exists():
            missing_dates.append(current_day.strftime("%Y-%m-%d"))

    return missing_dates


def ensure_mrms_files_exist(start_date, end_date, hour_string):
    """Check for missing MRMS files, then ask before downloading anything."""
    missing_dates = get_missing_dates(start_date, end_date, hour_string)

    if not missing_dates:
        print(f"All MRMS files are available from {start_date} to {end_date}.")
        return

    print(f"Missing MRMS files for: {', '.join(missing_dates)}")

    while True:
        answer = input("Would you like to download the missing MRMS dates and continue? (yes/no): ").strip().lower()

        if answer in {"yes", "y"}:
            from MRMS_downloader import sync_mrms_archive

            first_missing = pd.Timestamp(missing_dates[0]).to_pydatetime()
            last_missing = pd.Timestamp(missing_dates[-1]).to_pydatetime()
            print(f"Downloading MRMS data from {first_missing.date()} to {last_missing.date()}...")
            sync_mrms_archive(first_missing, last_missing)
            return

        if answer in {"no", "n"}:
            raise SystemExit("User chose not to download missing MRMS files. Script stopped.")

        print("Please type 'yes' or 'no'.")


# -----------------------------------------------------------------------------
# 3) Station filtering
# -----------------------------------------------------------------------------
def load_station_table():
    """Read the station list from SiteList.csv."""
    return pd.read_csv(SITES_PATH)


def filter_station_table(stations_df, site_config):
    """Keep only stations that match the site config.

    site_config can be:
    - UTDCO
    - a region like SWUT
    - a station triplet like 1309:UT:SNTL
    - an exact station name
    """
    config_text = str(site_config).strip()

    if config_text.upper() == "UTDCO":
        print("Using all stations from SiteList.csv.")
        return stations_df.copy()

    tokens = [token.strip() for token in config_text.split(",") if token.strip()]
    if not tokens:
        print("SITE_CONFIG was blank. Using all stations.")
        return stations_df.copy()

    matches = pd.Series(False, index=stations_df.index)

    for token in tokens:
        upper_token = token.upper()

        region_match = stations_df["editingRegion"].astype(str).str.strip().str.upper().eq(upper_token)
        triplet_match = stations_df["stationTriplet"].astype(str).str.replace(r"\s+", "", regex=True).str.upper().str.contains(upper_token, na=False)
        name_match = stations_df["stationName"].astype(str).str.strip().str.upper().eq(upper_token)

        matches = matches | region_match | triplet_match | name_match

    selected = stations_df.loc[matches].copy()

    if selected.empty:
        print(f"No stations matched '{site_config}'. Using all stations instead.")
        return stations_df.copy()

    print(f"SITE_CONFIG matched {len(selected)} stations.")
    return selected.reset_index(drop=True)


# -----------------------------------------------------------------------------
# 4) MRMS data collection
# -----------------------------------------------------------------------------
def build_mrms_station_frames(stations_df):
    """Open each local MRMS file and collect daily values for each station."""
    date_range = pd.date_range(start=START_DATE_STR, end=END_DATE_STR, freq="D")

    # Convert longitude values into the 0-360 format used by MRMS
    target_lons = xr.DataArray(
        stations_df["longitude"].apply(lambda lon: lon if lon >= 0 else 360 + lon),
        dims="station",
    )
    target_lats = xr.DataArray(stations_df["latitude"], dims="station")

    rows_by_station = {name: [] for name in stations_df["stationName"]}

    for current_day in date_range:
        date_text = current_day.strftime("%Y%m%d")
        timestamp = f"{date_text}-{HOUR_STR}"

        qpe_path = LOCAL_DATA_DIR / "qpe" / f"MRMS_RadarOnly_QPE_24H_{timestamp}.grib2"
        rqi_path = LOCAL_DATA_DIR / "rqi" / f"MRMS_RQI_{timestamp}.grib2"

        if not qpe_path.exists() or not rqi_path.exists():
            continue

        datasets = {}
        try:
            datasets["qpe"] = xr.open_dataset(qpe_path, engine="cfgrib")
            datasets["rqi"] = xr.open_dataset(rqi_path, engine="cfgrib")

            qpe_var = list(datasets["qpe"].data_vars)[0]
            rqi_var = list(datasets["rqi"].data_vars)[0]

            lat_key = "latitude" if "latitude" in datasets["qpe"].coords else "lat"
            lon_key = "longitude" if "longitude" in datasets["qpe"].coords else "lon"

            qpe_values = datasets["qpe"][qpe_var].sel(
                **{lat_key: target_lats, lon_key: target_lons}, method="nearest"
            ).values
            rqi_values = datasets["rqi"][rqi_var].sel(
                **{lat_key: target_lats, lon_key: target_lons}, method="nearest"
            ).values

            for row_index, station_row in stations_df.iterrows():
                station_name = station_row["stationName"]
                rows_by_station[station_name].append(
                    {
                        "date_pst": current_day.strftime("%Y-%m-%d"),
                        "elevation_ft": station_row["elevation"],
                        "latitude": station_row["latitude"],
                        "longitude": station_row["longitude"],
                        "network": station_row["NETWORK_CHAR"],
                        "radar_only_qpe_mm": max(qpe_values[row_index] / 25.4, 0.0),
                        "radar_quality_index": max(rqi_values[row_index], 0.0),
                    }
                )

        except Exception as exc:
            print(f"Error reading MRMS files for {date_text}: {exc}")
        finally:
            for ds in datasets.values():
                ds.close()

    station_frames = {}
    for station_name, rows in rows_by_station.items():
        if rows:
            station_frames[station_name] = pd.DataFrame(rows).sort_values("date_pst").reset_index(drop=True)

    return station_frames


# -----------------------------------------------------------------------------
# 5) SNOTEL merge
# -----------------------------------------------------------------------------
def get_snotel_data(stations_df, progress_callback=None):
    """Download the SNOTEL precipitation data for the date range."""
    return SNTL_Precip(
        df_sites=stations_df,
        start_date=START_DATE_STR,
        end_date=END_DATE_STR,
        elements="PREC::1",
        periodRef="START",
        interval="DAILY",
        returnFlags="true",
        returnOriginalValues="true",
        returnSuspectData="true",
        progress_callback=progress_callback,
    )


def merge_snotel_data(station_frames, snotel_data):
    """Attach SNOTEL values to each station's MRMS table."""
    for station_name, frame in station_frames.items():
        if station_name not in snotel_data:
            continue

        snotel_frame = snotel_data[station_name][["date_pst", "snotel_accum_in", "snotel_precip_in"]].copy()
        station_frames[station_name] = pd.merge(frame, snotel_frame, on="date_pst", how="left")

    return station_frames


# -----------------------------------------------------------------------------
# 6) Plotting and map output
# -----------------------------------------------------------------------------
def get_marker_color(avg_rqi):
    """Map average RQI to a semi-transparent green/yellow/red ring color."""
    if avg_rqi >= 0.75:
        return "rgba(46, 139, 87, 0.7)"
    if avg_rqi >= 0.5:
        return "rgba(214, 169, 0, 0.7)"
    return "rgba(214, 69, 69, 0.7)"


def get_precipitation_color(accumulation, maximum):
    """Map radar-only accumulation from white at zero to blue at the maximum."""
    color_stops = [
        (0.00, (255, 255, 255)),
        (0.17, (236, 236, 140)),
        (0.33, (166, 216, 84)),
        (0.50, (74, 203, 96)),
        (0.67, (54, 180, 168)),
        (0.83, (49, 134, 232)),
        (1.00, (70, 48, 175)),
    ]
    fraction = 0.0 if maximum <= 0 else min(max(accumulation / maximum, 0.0), 1.0)

    for index in range(1, len(color_stops)):
        upper_position, upper_color = color_stops[index]
        if fraction <= upper_position:
            lower_position, lower_color = color_stops[index - 1]
            blend = (fraction - lower_position) / (upper_position - lower_position)
            rgb = tuple(
                round(lower + blend * (upper - lower))
                for lower, upper in zip(lower_color, upper_color)
            )
            return "#{:02x}{:02x}{:02x}".format(*rgb)

    return "#{:02x}{:02x}{:02x}".format(*color_stops[-1][1])


def build_accumulation_legend(maximum):
    """Create a compact map legend for the selected radar-only accumulation range."""
    return f"""
    <div style="position:fixed;bottom:36px;left:12px;z-index:9999;background:rgba(255,255,255,0.94);
                padding:8px 10px;border:1px solid #777;border-radius:3px;font:12px Arial,sans-serif;
                color:#222;box-shadow:0 1px 4px rgba(0,0,0,0.25);">
    <div style="font-weight:bold;margin-bottom:5px;">Radar-only <br>accumulation (in)</div>
      <div style="display:flex;align-items:stretch;gap:7px;height:112px;">
        <div style="width:14px;border:1px solid #555;background:linear-gradient(to top,
          #ffffff 0%,#ecec8c 17%,#a6d854 33%,#4acb60 50%,#36b4a8 67%,#3186e8 83%,#4630af 100%);"></div>
        <div style="display:flex;flex-direction:column;justify-content:space-between;line-height:1.1;">
          <span>{maximum:.2f}</span><span>0.00</span>
        </div>
      </div>
    </div>
    """


def build_station_chart(station_name, station_df, avg_rqi):
    """Create the Plotly figure used inside each station popup."""
    fig = go.Figure(
        data=[
            go.Scatter(
                x=station_df["date_pst"],
                y=station_df["MRMS Radar Only"],
                mode="markers",
                name="MRMS Radar Only",
                marker={
                    "size": 10,
                    "color": station_df["radar_quality_index"],
                    "colorscale": [[0, "#ff0000"], [1, "#00aa00"]],
                    "cmin": 0,
                    "cmax": 1,
                    "colorbar": {"title": "RQI", "thickness": 18, "len": 0.8, "x": 1.02, "y": 0.65, "yanchor": "middle", "outlinewidth": 0},
                    "line": {"width": 0.5, "color": "rgba(25,25,25,0.35)"},
                },
                hovertemplate="<b>%{fullData.name}</b><br>Date: %{x}<br>Total Accumulation: %{y:.2f} in<br>RQI: %{marker.color:.2f}<extra></extra>",
            ),
            go.Scatter(
                x=station_df["date_pst"],
                y=station_df["SNOTEL Gauge"],
                mode="markers",
                name="SNOTEL Gauge",
                marker={"size": 9, "color": "#5B8FBF", "line": {"width": 0.8, "color": "black"}},
                hovertemplate="<b>%{fullData.name}</b><br>Date: %{x}<br>Total Accumulation: %{y:.2f} in<extra></extra>",
            ),
        ]
    )

    fig.update_layout(
        title=f"{station_name}<br>Avg RQI: {avg_rqi:.2f}",
        xaxis_title="Timeline (PST)",
        yaxis_title="Total Accumulation (inches)",
        template="plotly_white",
        legend_title_text="Data Source",
        hovermode="closest",
        dragmode="zoom",
        width=680,
        height=480,
        margin={"l": 60, "r": 90, "t": 60, "b": 60},
        legend={"orientation": "v", "y": 0.-15, "x": 1.02, "xanchor": "left", "yanchor": "top"},
    )
    fig.update_xaxes(type="date")
    return fig


def build_interactive_map(station_frames, snotel_data):
    """Build the final Folium map, save it to disk, and return the map object."""
    if not station_frames:
        raise SystemExit("No MRMS station data was created. Check your files and date range.")

    all_lats = [frame["latitude"].iloc[0] for frame in station_frames.values() if not frame.empty]
    all_lons = [frame["longitude"].iloc[0] for frame in station_frames.values() if not frame.empty]
    center = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]

    max_accumulation = max(
        (
            frame.loc[
                (frame["date_pst"] >= START_DATE_STR) & (frame["date_pst"] <= END_DATE_STR),
                "radar_only_qpe_mm",
            ].sum()
            for frame in station_frames.values()
            if not frame.empty
        ),
        default=0.0,
    )

    map_object = folium.Map(location=center, zoom_start=6, tiles=None, control_scale=True)
    map_object.get_root().html.add_child(
        folium.Element(build_accumulation_legend(max_accumulation))
    )

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
        name="Esri Hillshade",
        opacity=0.55,
        overlay=False,
    ).add_to(map_object)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
        name="Esri Topographic",
        opacity=0.85,
        overlay=False,
    ).add_to(map_object)

    folium.GeoJson(
        "https://raw.githubusercontent.com/python-visualization/folium/main/examples/data/us-states.json",
        name="State Lines",
        style_function=state_line_style,
    ).add_to(map_object)

    folium.LayerControl(collapsed=False).add_to(map_object)

    snotel_lookup = {str(name).strip().lower(): frame for name, frame in snotel_data.items()}

    for station_name, frame in station_frames.items():
        if frame.empty:
            continue

        filtered = frame[(frame["date_pst"] >= START_DATE_STR) & (frame["date_pst"] <= END_DATE_STR)].copy()
        if filtered.empty:
            continue

        lookup_name = station_name.strip().lower()
        if lookup_name in snotel_lookup and not snotel_lookup[lookup_name].empty:
            snotel_frame = snotel_lookup[lookup_name].copy()
            filtered["date_pst_dt"] = pd.to_datetime(filtered["date_pst"])
            snotel_frame["date_pst_dt"] = pd.to_datetime(snotel_frame["date_pst"])
            merged = pd.merge(filtered[["date_pst_dt"]], snotel_frame[["date_pst_dt", "snotel_precip_in"]], on="date_pst_dt", how="left")
            filtered["snotel_precip_in"] = merged["snotel_precip_in"].fillna(0.0)
        else:
            filtered["snotel_precip_in"] = 0.0

        avg_rqi = filtered["radar_quality_index"].mean()
        filtered["MRMS Radar Only"] = filtered["radar_only_qpe_mm"].cumsum()
        filtered["SNOTEL Gauge"] = filtered["snotel_precip_in"].cumsum()
        total_radar_accumulation = filtered["MRMS Radar Only"].iloc[-1]

        chart = build_station_chart(station_name, filtered, avg_rqi)

        station_chart_dir = Path("station_charts")
        station_chart_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", station_name).strip("_")
        chart_path = station_chart_dir / f"{safe_name}_full_chart.html"
        chart.write_html(
            chart_path,
            include_plotlyjs="cdn",
            full_html=True,
            config={"responsive": True, "scrollZoom": True, "displaylogo": False, "displayModeBar": True, "doubleClick": "reset+autosize"},
        )

        popup_chart_html = chart.to_html(
            include_plotlyjs="cdn",
            full_html=False,
            config={"responsive": True, "scrollZoom": True, "displaylogo": False, "displayModeBar": True, "doubleClick": "reset+autosize"},
        )

        # Wrap the popup HTML in an IFrame so Plotly scripts and DOM elements
        # are isolated from the main document. This prevents the charts from
        # being rendered as a stacked list outside the map container.
        iframe_html = f"""
        <div style='font-family: Arial, sans-serif; width: 760px; max-width: 95vw; padding: 6px;'>
            <h4 style='margin:0 0 5px 0; color:#2c3e50;'>{station_name}</h4>
            <p style='margin:0 0 8px 0; font-size:12px; color:#7f8c8d;'><b>Average RQI:</b> {avg_rqi:.2f}</p>
            <div style='margin: 0; border: 1px solid #d9d9d9; border-radius: 8px; overflow: hidden; background: white; min-height: 400px;'>
                {popup_chart_html}
            </div>
        </div>
        """

        iframe = folium.IFrame(iframe_html, width=760, height=560)
        popup = folium.Popup(iframe, max_width=760)

        folium.Marker(
            location=[filtered["latitude"].iloc[0], filtered["longitude"].iloc[0]],
            popup=popup,
            tooltip=f"Click to view {station_name}",
            icon=folium.DivIcon(
                icon_size=(22, 22),
                icon_anchor=(11, 11),
                html=(
                    '<div style="width:20.8px;height:20.8px;box-sizing:border-box;'
                    f'border:3.5px solid {get_marker_color(avg_rqi)};border-radius:50%;position:relative;">'
                    '<span style="position:absolute;width:10.4px;height:10.4px;box-sizing:border-box;'
                    'border:1.3px solid #000;border-radius:50%;'
                    f'background:{get_precipitation_color(total_radar_accumulation, max_accumulation)};'
                    'top:50%;left:50%;transform:translate(-50%,-50%);"></span></div>'
                ),
            ),
        ).add_to(map_object)

    output_file = "mrms_station_time_series_map.html"
    map_object.save(output_file)
    return map_object
    print(f"Map saved to {output_file}.")
    return map_object


# -----------------------------------------------------------------------------
# 7) Main script
# -----------------------------------------------------------------------------
def main():
    """Run the full workflow."""
    ensure_mrms_files_exist(START_DATE_STR, END_DATE_STR, HOUR_STR)

    stations_df = load_station_table()
    stations_df = filter_station_table(stations_df, SITE_CONFIG)

    station_frames = build_mrms_station_frames(stations_df)
    snotel_data = get_snotel_data(stations_df)
    station_frames = merge_snotel_data(station_frames, snotel_data)

    if not station_frames:
        raise SystemExit("No station data was created. Please check your date range or SITE_CONFIG.")

    print(f"Prepared {len(station_frames)} stations for plotting.")
    build_interactive_map(station_frames, snotel_data)


if __name__ == "__main__":
    main()
