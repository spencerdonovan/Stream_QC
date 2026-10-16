# MRMS 2.5 and NEXRAD + SNOTEL Guide

## Purpose

This tool builds an interactive map and time-series charts of specified regions or sites that put a radar-derived precipitation estimate beside daily (QC'd) precipitation value from SNOTEL rain gauge observations. It uses daily MRMS Radar-Only Quantitative Precipitation Estimate (QPE) from NOAA's AWS S3 bucket, downloaded to a local archive, which is sampled at each nearest grid cell (~1 km X ~1 km) to the selected SNOTEL stations.  The two cumulative series are then displayed together in the pop-up graph.

The comparison is useful for inspecting agreement, timing, and possible outliers. It is not a formal validation: the radar and gauge measurements have different spatial footprints, measurement errors, etc.

## What are NEXRAD and MRMS?

**NEXRAD** is the common name for the U.S. network of Next Generation Weather Radar, also called WSR-88D. These ground-based Doppler radars observe precipitation and atmospheric motion over broad areas.

**MRMS** means Multi-Radar Multi-Sensor. NOAA's MRMS system combines and processes information from multiple radars and other observing systems to produce gridded weather products. Its product suite includes precipitation estimates, reflectivity mosaics, and quality information. This project uses MRMS files built from the radar network, but the particular precipitation field selected here is **RadarOnly_QPE_24H**. It is intentionally a radar-only estimate rather than one corrected or blended with the SNOTEL values in this script.

The NOAA MRMS product table describes `RadarOnly_QPE_24H` as a 24-hour radar precipitation accumulation in millimeters. It separately lists `RadarQualityIndex` (RQI) as a dimensionless quality field. See [NOAA NSSL: MRMS](https://www.nssl.noaa.gov/projects/mrms/), [MRMS operational GRIB2 product tables](https://www.nssl.noaa.gov/projects/mrms/operational/tables.php), and [MRMS data access](https://www.nssl.noaa.gov/projects/mrms/MRMS_data.php).

## Inputs and settings

The primary settings are at the top of `MRMS_2.5.py`:

- `START_DATE_STR` and `END_DATE_STR`: inclusive date range to process.
- `HOUR_STR`: timestamp used to identify the daily MRMS files. The default is `080000` (08:00:00 UTC).
- `SITE_CONFIG`: station filter. It accepts `UTDCO` for all rows, comma-separated region codes, station triplets, or exact station names.
- `LOCAL_DATA_DIR`: local archive root, defaulting to `mrms_local_archive`.
- `SITES_PATH`: station metadata CSV, defaulting to `SiteList.csv`.

The station list supplies station names, triplets, region, latitude, longitude, and elevation. MRMS files are GRIB2 files organized under `mrms_local_archive/qpe` and `mrms_local_archive/rqi`.

## Processing flow

1. **Check the local archive.** `get_missing_dates()` checks each date for both a Radar-Only 24-hour QPE file and an RQI file. `ensure_mrms_files_exist()` prompts before downloading missing data. The downloader retrieves compressed files from NOAA's public MRMS S3 bucket, extracts them to GRIB2, and stores them in the archive folders.
2. **Select stations.** `load_station_table()` reads `SiteList.csv`; `filter_station_table()` filters by the configured region, triplet, or station name. A blank or unmatched filter falls back to all stations.
3. **Read each day's grids.** `build_mrms_station_frames()` opens the QPE and RQI GRIB2 files with `xarray`/`cfgrib`. For every station, it converts negative longitude to the 0–360 convention used by the grids and selects the nearest latitude/longitude grid cell. It does not interpolate between cells or account for the station's surrounding terrain.
4. **Convert and store radar values.** The selected QPE value is divided by 25.4 to convert the product's millimeters to inches, then clipped to a minimum of zero. Despite the internal column name `radar_only_qpe_mm`, the stored value is therefore in **inches**. The selected RQI value is clipped to a minimum of zero and stored with the same station/date row.
5. **Fetch and derive SNOTEL precipitation.** `get_snotel_data()` calls `SNTL_Precip` for the selected stations, `PREC::1` element, daily interval, and `periodRef="START"`. The API's daily PREC values are treated by `SNTL_Precip.py` as cumulative readings in inches. That module sorts readings by date and subtracts each prior reading (`diff`) to estimate daily precipitation. The first requested day has no prior reading in the response, so its derived daily amount is NaN.
6. **Join by station and date.** `merge_snotel_data()` left-joins SNOTEL fields to each radar station frame using `date_pst`. The chart-building code also aligns the daily gauge values by date and fills missing gauge daily amounts with zero for cumulative plotting.
7. **Build the map and charts.** `build_interactive_map()` creates a Folium map with one marker per station. Each marker's center fill represents total radar-only accumulation for the selected period; the outer ring represents average RQI. Clicking a marker opens a Plotly chart with cumulative MRMS Radar Only and SNOTEL Gauge series. Per-station chart HTML is saved under `station_charts/`, and the complete map is written to `mrms_station_time_series_map.html`.

## How the precipitation comparison works

For each station and each date, the script has a radar QPE grid value in millimeters, which it converts to inches, and a daily SNOTEL precipitation estimate in inches. The plotted series are running sums over the selected dates:

- **MRMS Radar Only** = cumulative sum of the daily RadarOnly_QPE_24H values sampled at the station's nearest grid cell.
- **SNOTEL Gauge** = cumulative sum of daily increments calculated by differencing the SNOTEL cumulative PREC readings.

Overlaying the totals helps show whether the two sources rise at similar times and end at similar totals. A growing gap can indicate a real difference between radar and gauge estimates, but it does not by itself identify which measurement is wrong. Radar pixels represent a gridded area while a gauge is a point measurement; local elevation, wind, precipitation phase, snow accumulation/melting, gauge undercatch, radar beam coverage, and differences in daily cutoff can all affect the comparison.


## What RQI means here

RQI is a dimensionless Radar Quality Index associated with radar coverage/quality. In the chart it is shown as the ring color surround each SNOTEL point, with a red-to-green scale from 0 to 1; the station title and map marker also show/use the average RQI. The map ring is green for average RQI at least 0.75, yellow for at least 0.5, and red below 0.5.

RQI is context for interpreting the radar series, not a precipitation amount. The code does **not** multiply, filter, or otherwise correct QPE using RQI. Also note that this script loads the general `RadarQualityIndex` file at the selected timestamp and uses that sampled value alongside a 24-hour accumulation. NOAA lists a distinct `RadarAccumulationQualityIndex_24H` product; this script does not read that accumulation-specific index. Accordingly, the displayed RQI should not be interpreted as a directly computed confidence score for each 24-hour total.

## Running the workflow

From the repository root:

- Run the configured Python script with `python MRMS_2.5.py`. Edit its date range, hour, and site config near the top first. If files are missing, it asks whether to download them.
- Run the Streamlit experience with `streamlit run mrms_streamlit_app.py`, or open the NEXRAD + SNOTEL option from `streamlit run dmp_qc_app.py`. The Streamlit app exposes date range and station configuration in the sidebar and offers a download action when archive dates are missing.

The Streamlit wrapper uses the same functions from `MRMS_2.5.py`, setting its date range and paths before preparing the station data.

## Important implementation limitations

- **Nearest-cell sampling:** one grid cell is used for each station. There is no spatial averaging, interpolation, or elevation correction.
- **RQI is not used to adjust QPE:** a low RQI does not remove or down-weight the corresponding radar point.
- **Different daily intervals:** matching by date does not ensure that radar and SNOTEL totals share an identical start and end time. The chart's PST label is not backed by a time-zone conversion.
- **First SNOTEL day:** differencing cumulative readings needs a prior value, which is not requested before the selected start date. The first daily increment is therefore missing and later chart code treats a missing daily value as zero.
- **Missing API responses:** `SNTL_Precip.py` only appends successful API responses and then pairs them with station rows in order. If an API request fails partway through, subsequent successful payloads can be associated with the wrong station. Check results against station triplets when a request fails.
- **Downloader time setting:** `MRMS_downloader.py` currently constructs archive keys using a fixed `080000` timestamp. Keep `HOUR_STR` at its default unless the downloader is updated to support another hour.
- **Data quality flags:** the SNOTEL API request asks for flags and original values, but the parsing code uses the `value` field and does not filter on flags or use `origValue`.
- **Negative differenced SNOTEL amounts:** differences are not clipped to zero. Sensor resets, corrections, or data revisions can yield a negative daily increment.
- **Archive gaps:** missing dates are skipped during MRMS frame creation. The plotted cumulative line therefore sums available radar days rather than guaranteeing a complete sequence.

For operational or scientific use, verify GRIB units/metadata and the actual observation windows in both products, investigate missing or flagged observations, and consider whether the accumulation-specific RQI product is more appropriate for the intended analysis.
