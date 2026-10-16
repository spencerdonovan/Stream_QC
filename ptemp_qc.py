

"""Streamlit dashboard for USDA AWDB PTEMP and SNWD data.

This app fetches temperature and snow depth data from the USDA AWDB REST API,
remaps PTEMP from Fahrenheit to Celsius, and renders an interactive Plotly chart.
The chart supports zooming and lets the user toggle PTEMP depth layers and SNWD.
"""

import requests
import pandas as pd
import datetime
import time
import streamlit as st
import numpy as np

# %% Map station names to AWDB station triplets.
SITE_OPTIONS = {
    'Powder Mountain': '1300:UT:SNTL',
    'Midway Valley': '626:UT:SNTL',
    'Trial Lake': '828:UT:SNTL',
    'Heavenly Valley': '518:CA:SNTL'
}

# The API query requests all PTEMP depths plus SNWD for the selected station.
ELEMENTS = 'PTEMP:*, SNWD::1, WTEQ::1, TOBS::1'


@st.cache_data(show_spinner=False)
def fetch_json(url, timeout=30, retries=3, backoff=1.5):
    """Fetch JSON from the AWDB API with simple retry/backoff behavior."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            st.warning(f'HTTP {r.status_code} from API call')
        except requests.exceptions.ReadTimeout as e:
            st.warning(f'Read timeout (attempt {attempt}/{retries}): {e}')
        except Exception as e:
            st.warning(f'Request failed (attempt {attempt}/{retries}): {e}')

        # Exponential backoff between retries.
        if attempt < retries:
            sleep_time = backoff ** attempt
            time.sleep(sleep_time)

    st.error('Failed to fetch data after retries.')
    return None


@st.cache_data(show_spinner=False)
def build_df_dict(site_triplet, start_date, end_date, interval, elements=ELEMENTS):
    """Build a dictionary of pandas DataFrames from API response data."""
    url = (
        'https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?'
        f'stationTriplets={site_triplet}&elements={elements}&duration={interval}'
        f'&beginDate={start_date}&endDate={end_date}&periodRef=END'
        '&centralTendencyType=NONE&returnFlags=true'
        '&returnOriginalValues=true&returnSuspectData=true'
    )

    json_data = fetch_json(url)
    if json_data is None:
        return {}

    data = json_data[0].get('data', [])
    df_dict = {}

    # Each item contains a station element and a time series of values.
    for item in data:
        elem = item['stationElement']['elementCode']

        # Build a unique key for each PTEMP sensor depth, but only one key for SNWD.
        if elem == 'PTEMP':
            hd = item['stationElement']['heightDepth']
            dict_key = f'{elem}_{hd}'
        elif elem in ['SNWD', 'WTEQ', 'TOBS']:
            dict_key = elem
        else:
            continue

        values = item.get('values', [])
        if not values:
            continue

        df = pd.DataFrame({
            'date': [v.get('date') for v in values],
            'value': [v.get('value') for v in values],
            'origValue': [v.get('origValue') for v in values],
            'qaFlag': [v.get('qaFlag') for v in values],
            'qcFlag': [v.get('qcFlag') for v in values]
        })
        df_dict[dict_key] = df

    return df_dict


def merge_time_series(df_dict):
    """Convert each series to a datetime index and merge into one DataFrame."""
    proc = {}
    for key, df in df_dict.items():
        d = df.copy()
        if 'date' not in d.columns:
            continue
        d['date'] = pd.to_datetime(d['date'])
        d['value'] = pd.to_numeric(d['value'], errors='coerce')
        d = d.set_index('date').sort_index()
        proc[key] = d['value']

    if not proc:
        return pd.DataFrame()

    # Resulting DataFrame has a column for each sensor series.
    return pd.concat(proc, axis=1)


def build_plotly_figure(merged, selected_layers, show_snwd, title):
    """Build the Plotly figure with SNWD on a secondary y-axis and PTEMP depth lines."""
    import plotly.graph_objects as go

    # Use an HSL palette for PTEMP traces so each line is visually distinct.
    ptemp_cols = [c for c in merged.columns if c.startswith('PTEMP')]
    colors = [
        f'hsl({int(i * 137.508) % 360}, 70%, 45%)' for i in range(len(ptemp_cols))]

    # Keep original data untouched; convert only for plotting.
    merged = merged.copy()
    temp_cols = ptemp_cols + (['TOBS'] if 'TOBS' in merged.columns else [])
    if temp_cols:
        merged[temp_cols] = (merged[temp_cols] - 32.0) * 5.0 / 9.0

    fig = go.Figure()

    # Add TOBS trace if available
    if 'TOBS' in merged.columns:
        fig.add_trace(
            go.Scatter(
                x=merged.index,
                y=merged['TOBS'],
                name='TOBS',
                line=dict(color='palevioletred', width=2, dash='dot'),
                mode='lines',
                visible='legendonly',
                hovertemplate='TOBS: %{y:.2f} °C<br>%{x|%Y-%m-%d %H:%M}<extra></extra>'
            )
        )

    # Add SNWD to the secondary axis if requested.
    if show_snwd and 'SNWD' in merged.columns:
        fig.add_trace(
            go.Scatter(
                x=merged.index,
                y=merged['SNWD'],
                name='SNWD',
                line=dict(color='black', width=2),
                mode='lines',
                hovertemplate='%{x|%Y-%m-%d %H:%M}: SNWD=%{y:.2f}<extra></extra>',
                yaxis='y2'
            )
        )

    # Use midnight values to determine periods where snow depth covers each PTEMP height.
    if 'SNWD' in merged.columns:
        midnight_idx = merged[merged.index.hour == 0].index.tolist()
        max_midnight_snwd = merged.loc[midnight_idx,
                                       'SNWD'].max() if midnight_idx else None
    else:
        midnight_idx = []
        max_midnight_snwd = None

    for i, col in enumerate(ptemp_cols):
        if col not in selected_layers:
            continue

        series = merged[col]
        color = colors[i % len(colors)]

        # Attempt to parse the sensor depth from the column name.
        try:
            height = int(col.split('_', 1)[1])
        except Exception:
            height = None

        # Plot the full PTEMP series in grey as a baseline line.
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                name=f'{col} baseline',
                line=dict(color='lightgrey', width=1),
                mode='lines',
                hoverinfo='skip',
                showlegend=False
            )
        )

        # Highlight periods where snow depth was greater than or equal to the sensor height.
        colored_mask = pd.Series(False, index=series.index, dtype=bool)
        if height is not None and midnight_idx:
            for midnite in midnight_idx:
                snwd_val = merged.loc[midnite, 'SNWD']
                if pd.isna(snwd_val):
                    continue
                next_midnight = midnite + pd.Timedelta(hours=24)
                window = (series.index >= midnite) & (
                    series.index < next_midnight)
                if snwd_val >= height:
                    colored_mask.loc[window] = True

        colored_points = series.where(colored_mask)
        has_coverage = colored_mask.any()

        if has_coverage:
            # Buried layers: show colored trace by default
            fig.add_trace(
                go.Scatter(
                    x=colored_points.index,
                    y=colored_points.values,
                    name=col,
                    legendgroup=col,
                    line=dict(color=color, width=2),
                    mode='lines',
                    hovertemplate=f'{col}: %{{y:.2f}} °C<br>%{{x|%Y-%m-%d %H:%M}}<extra></extra>'
                )
            )
        else:
            # Non-buried layers: keep the plot grey by default, but use a hidden colored
            # trace for the legend so behavior matches buried PTEMP traces.
            fig.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    name=col,
                    legendgroup=col,
                    showlegend=True,
                    visible='legendonly',
                    line=dict(color=color, width=2),
                    mode='lines',
                    hovertemplate=f'{col}: %{{y:.2f}} °C<br>%{{x|%Y-%m-%d %H:%M}}<extra></extra>'
                )
            )

    fig.update_layout(
        title={'text': title, 'y': 0.99, 'x': 0.01,
               'xanchor': 'left', 'yanchor': 'top'},
        xaxis=dict(title='Date', uirevision='static'),
        yaxis=dict(title='PTEMP (°C)', uirevision='static'),
        yaxis2=dict(title='SNWD (in)', overlaying='y',
                    side='right', uirevision='static'),
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='top', y=-0.18,
                    xanchor='center', x=0.5, groupclick='togglegroup'),
        margin=dict(l=40, r=40, t=100, b=120),
        height=828,
        dragmode='zoom',
        uirevision='static'
    )

    return fig


def build_heatmap_figure(merged, selected_layers, show_snwd, title):
    """PTEMP heatmap with SNWD on primary y-axis, WTEQ on secondary y-axis.
    Heatmap extends up to two PTEMP layers above max SNWD.
    Adds vertical buffers on both axes and places legend below the plot.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # Expect PTEMP columns like 'PTEMP_<depth_in_inches>'
    ptemp_cols = [c for c in merged.columns if c.startswith('PTEMP')]
    if not ptemp_cols:
        return go.Figure()

    merged = merged.copy()

    # Convert PTEMP (F) -> (C)
    merged[ptemp_cols] = (merged[ptemp_cols] - 32.0) * 5.0 / 9.0

    # Collect depths from PTEMP column names
    depth_pairs = []
    for c in ptemp_cols:
        try:
            depth = int(c.split('_', 1)[1])
        except Exception:
            depth = None
        if depth is not None and depth >= 0 and c in merged.columns:
            depth_pairs.append((c, depth))
    if not depth_pairs:
        return go.Figure()

    # Sort by height (inches)
    depth_pairs.sort(key=lambda x: x[1])
    col_order = [p[0] for p in depth_pairs]
    depths = np.array([p[1] for p in depth_pairs], dtype=float)
    depths_unique = np.sort(np.unique(depths))

    # Interpolation grid for a smooth vertical profile
    if len(depths_unique) > 1:
        min_gap = np.min(np.diff(depths_unique))
        resolution = min(1.0, float(min_gap) / 4.0)
    else:
        resolution = 1.0

    interp_heights = np.arange(depths_unique.min(),
                               depths_unique.max() + resolution,
                               resolution)
    interp_heights = np.round(interp_heights, 3)

    # Build source matrix (rows=depths, cols=time)
    z = np.full((len(interp_heights), len(merged.index)), np.nan)
    for col_idx, col in enumerate(col_order):
        z_src = merged[col].to_numpy(dtype=float)
        if col_idx == 0:
            source_values = np.vstack([z_src])
        else:
            source_values = np.vstack([source_values, z_src])

    # Interpolate along height for each timestamp
    for time_index in range(z.shape[1]):
        valid = ~np.isnan(source_values[:, time_index])
        if np.count_nonzero(valid) >= 2:
            z[:, time_index] = np.interp(
                interp_heights,
                depths[valid],
                source_values[valid, time_index],
                left=source_values[valid, time_index][0],
                right=source_values[valid, time_index][-1]
            )
        elif np.count_nonzero(valid) == 1:
            z[:, time_index] = source_values[valid, time_index][0]

    # Determine max SNWD (for axis and overlay). If hidden or missing, fall back.
    if show_snwd and ('SNWD' in merged.columns or 'SNWD::1' in merged.columns):
        snwd_col = 'SNWD' if 'SNWD' in merged.columns else 'SNWD::1'
        max_snwd = pd.to_numeric(merged[snwd_col], errors='coerce').max()
        if pd.isna(max_snwd):
            max_snwd = 204
    else:
        max_snwd = 204

    # Extend the heatmap up to TWO PTEMP layers above max SNWD, if present
    above_idxs = np.where(depths_unique > max_snwd)[0]
    if len(above_idxs) >= 2:
        target_top = depths_unique[above_idxs[1]]   # second layer above
    elif len(above_idxs) == 1:
        target_top = depths_unique[above_idxs[0]]   # one layer above
    else:
        target_top = max_snwd

    # Cap at the maximum available sensor height
    target_top = float(min(target_top, depths_unique[-1]))

    # Clip the heatmap vertical grid to target_top
    interp_mask = interp_heights <= target_top
    interp_heights = interp_heights[interp_mask]
    z = z[:len(interp_heights), :]
    z_min = np.nanmin(z)
    z_max = np.nanmax(z)

    # Buffers: primary (height) and secondary (WTEQ)
    buffer_height_inches = max(
        6, round(float(target_top) * 0.10, 1))  # ≥ 6", ~10% headroom

    # Create figure with secondary y-axis (for WTEQ only)
    fig = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])

    # Heatmap on primary y-axis
    fig.add_trace(
        go.Heatmap(
            x=merged.index,
            y=interp_heights,
            z=z,
            colorscale='RdBu_r',
            zmid=0,
            zmin=z_min,
            zmax=z_max,
            colorbar=dict(
                title='PTEMP (°C)',
                len=0.82,
                y=0.39,
                yanchor='middle'
            ),
            xgap=0,
            ygap=0,
            zsmooth='best',
            hoverongaps=False,
            hovertemplate='Height: %{y} in<br>%{x|%Y-%m-%d %H:%M}<br>PTEMP: %{z:.2f} °C<extra></extra>'
        ),
        secondary_y=False
    )

    # SNWD overlay: stays on PRIMARY y-axis (height in inches)
    if show_snwd and ('SNWD' in merged.columns or 'SNWD::1' in merged.columns):
        snwd_col = 'SNWD' if 'SNWD' in merged.columns else 'SNWD::1'
        snwd_series = pd.to_numeric(merged[snwd_col], errors='coerce')
        if np.isfinite(snwd_series).any():
            fig.add_trace(
                go.Scatter(
                    x=merged.index,
                    y=snwd_series,
                    name='SNWD',
                    line=dict(color='royalblue', width=2),
                    mode='lines',
                    hovertemplate='%{x|%Y-%m-%d %H:%M}: SNWD=%{y:.2f} in<extra></extra>'
                ),
                secondary_y=False  # primary axis
            )

    # WTEQ overlay: goes on SECONDARY y-axis (independent scale) with buffer
    wteq_col = None
    wteq_candidates = [
        c for c in merged.columns if c.upper().startswith('WTEQ')]
    if wteq_candidates:
        preferred = [
            c for c in wteq_candidates if '::1' in c or c.endswith('1')]
        wteq_col = preferred[0] if preferred else wteq_candidates[0]

    wteq_max = None
    if wteq_col is not None:
        wteq_series = pd.to_numeric(merged[wteq_col], errors='coerce')
        if np.isfinite(wteq_series).any():
            wteq_max = float(np.nanmax(wteq_series))
            fig.add_trace(
                go.Scatter(
                    x=merged.index,
                    y=wteq_series,
                    name='WTEQ (in SWE)',
                    mode='lines',
                    line=dict(color='deeppink', width=2),
                    hovertemplate='%{x|%Y-%m-%d %H:%M}: WTEQ=%{y:.2f} in<extra></extra>'
                ),
                secondary_y=True  # secondary axis
            )

    # Layout & axes
    layout = dict(
        title={'text': f'{title} — PTEMP heatmap', 'y': 0.99, 'x': 0.01,
               'xanchor': 'left', 'yanchor': 'top'},
        xaxis=dict(title='Date', type='date', uirevision='static'),
        yaxis=dict(
            title='Height (in)',
            autorange=False,
            # primary axis with buffer
            range=[0, target_top + buffer_height_inches],
            tickmode='array',
            tickvals=[v for v in depths_unique if v <= target_top],
            ticktext=[str(int(v)) if float(v).is_integer() else str(v)
                      for v in depths_unique if v <= target_top],
            uirevision='static'
        ),
        # extra bottom space for legend
        margin=dict(l=60, r=60, t=100, b=140),
        height=800,
        hovermode='x unified',
        legend=dict(
            orientation='h',
            yanchor='top',
            y=-0.22,            # below the plot
            xanchor='center',
            x=0.5
        )
    )
    fig.update_layout(**layout)

    # Secondary y-axis (WTEQ) title + range buffer (if WTEQ was plotted)
    fig.update_yaxes(title_text="WTEQ (in SWE)", secondary_y=True)
    if wteq_max is not None and np.isfinite(wteq_max):
        wteq_buffer = max(0.5, round(wteq_max * 0.10, 2)
                          )  # ≥ 0.5", ~10% headroom
        fig.update_yaxes(autorange=False,
                         range=[0, wteq_max + wteq_buffer],
                         secondary_y=True)

    return fig


def render_profile_dashboard(show_sidebar: bool = True):
    st.title('🌡️ PTEMP + SNWD Dashboard')
    st.markdown(
        'Select Super Site, compare snow depth to buried beadedstream temperature layers.')

    # Inject CSS to move only the tooltip data box to the right, keeping the vertical hover line at the cursor
    if show_sidebar:
        with st.sidebar:
            st.header('Data selection')

            # User controls in the sidebar.
            station_name = st.selectbox(
                'Station', list(SITE_OPTIONS.keys()), index=0)
            site_triplet = SITE_OPTIONS[station_name]
            interval = st.radio('Interval', ['HOURLY', 'DAILY'], index=0)

            default_end = datetime.date.today()
            default_start = default_end - datetime.timedelta(days=30)
            start_date = st.date_input('Start date', default_start)
            end_date = st.date_input('End date', default_end)

    else:
        station_name = list(SITE_OPTIONS.keys())[0]
        site_triplet = SITE_OPTIONS[station_name]
        interval = 'HOURLY'
        default_end = datetime.date.today()
        default_start = default_end - datetime.timedelta(days=30)
        start_date = default_start
        end_date = default_end

    if start_date > end_date:
        st.error('Start date must be on or before end date.')
        return

    df_dict = build_df_dict(
        site_triplet, start_date.isoformat(), end_date.isoformat(), interval)
    if not df_dict:
        st.warning('No data available for the selected station/date range.')
        return

    merged = merge_time_series(df_dict)
    if merged.empty:
        st.warning('No valid time series could be created from the API results.')
        return

    # List available PTEMP depth traces and allow user selection.
    ptemp_cols = []
    for c in merged.columns:
        if not c.startswith('PTEMP'):
            continue
        try:
            if int(c.split('_', 1)[1]) >= 0:
                ptemp_cols.append(c)
        except Exception:
            ptemp_cols.append(c)

    if not ptemp_cols:
        st.warning('No PTEMP series found for this station/date range. Adjust the dates or select a different station to see the vertical PTEMP heatmap.')

    # Determine which PTEMP layers are ever buried (based on midnight SNWD)
    never_buried = []
    if 'SNWD' in merged.columns:
        try:
            midnight_idx = merged[merged.index.hour == 0].index.tolist()
        except Exception:
            midnight_idx = []

        for col in ptemp_cols:
            try:
                h = int(col.split('_', 1)[1])
            except Exception:
                h = None
            if h is None or not midnight_idx:
                # treat as potentially buried unless we can prove otherwise
                continue

            # Check if any midnight snow depth >= sensor height
            snw_at_midnights = merged.loc[midnight_idx, 'SNWD']
            if not (snw_at_midnights >= h).any():
                never_buried.append(col)

    if show_sidebar:
        with st.sidebar:
            st.header('Display options')

            hide_never_buried = st.checkbox(
                'Hide never-buried PTEMP layers', value=False)
            available_cols = [c for c in ptemp_cols if not (
                hide_never_buried and c in never_buried)]
            if not available_cols:
                available_cols = ptemp_cols.copy()

            selected_layers = st.multiselect(
                'PTEMP layers to show', available_cols, default=available_cols)

            if hide_never_buried and never_buried:
                st.caption(f'Hiding {len(never_buried)} never-buried layer(s)')

            show_snwd = st.checkbox('Show SNWD', value=True)

            # NEW: control for SWE
            show_wteq = st.checkbox("Show SWE (WTEQ)", value=True)

            show_data_table = st.checkbox('Show raw data', value=False)
    else:
        hide_never_buried = False
        selected_layers = ptemp_cols.copy()
        show_snwd = True
        show_data_table = False

    title = f'PTEMP heights & SNWD for {station_name} ({interval})'
    fig = build_plotly_figure(merged, selected_layers, show_snwd, title)

    # Render the Plotly figure in the app with a static key to preserve zoom/pan state.
    st.plotly_chart(fig, config={'scrollZoom': True}, key='ptemp_snwd_chart')

    heatmap_fig = build_heatmap_figure(
        merged, selected_layers, show_snwd, title)

    if heatmap_fig.data:
        st.markdown('---')
        st.subheader('PTEMP vertical profile heatmap')
        st.plotly_chart(heatmap_fig, config={
                        'scrollZoom': True}, key='ptemp_heatmap_chart')

    if show_data_table:
        st.subheader('Raw merged time series')
        st.dataframe(merged)

    st.markdown('---')
    st.markdown('### Notes')
    st.markdown(
        '- PTEMP sensor heights are shown as colored segments when the 00:00 QC snow depth value was greater than or equal to the temperature sensor height.\n'
        '- Use the legend or the sidebar multiselect to hide/show individual PTEMP traces.\n'
        '- The dashboard uses USDA AWDB REST API data for the selected station and date range.'
    )


if __name__ == '__main__':
    st.set_page_config(page_title='PTEMP / SNWD Dashboard', layout='wide')
    render_profile_dashboard()
