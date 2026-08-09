"""
StationScope — interactive map of EMS station access across New York State.

Reads only the precomputed GeoJSON in data/processed/ (see CLAUDE.md: the app
never talks to an external API or database at runtime).

Run with:
    streamlit run app/streamlit_app.py
"""

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"
GEOJSON_PATH = PROCESSED / "ny_ems_station_density_by_county.geojson"
# The located file is a superset of ny_ems_agencies.csv (same rows, same
# order, plus geocode and station-match columns), so it drives both the pin
# layer and the full drill-down list -- one load, and the two can't drift apart.
AGENCIES_CSV_PATH = PROCESSED / "ny_ems_agencies_located.csv"
DESERTS_CSV_PATH = PROCESSED / "ambulance_deserts_by_block_group.csv"

NO_COUNTY_SELECTED = "— All counties —"
AGENCY_TYPES = [
    ("ambulance_als", "Ambulance / ALS"),
    ("bls_nontransport", "BLS non-transport"),
]

# A pin's coordinate comes from one of two sources, and they do not mean the
# same thing -- so they are counted and drawn separately rather than pooled.
# `census_street` is the agency's OWN registered street address, geocoded.
# `hifld_station_name_match` is a third-party fire/EMS station that matched the
# agency by name -- the right building for that organisation, but not a
# geocode of anything the agency itself registered.
SOURCE_CENSUS = "census_street"
SOURCE_HIFLD = "hifld_station_name_match"
SOURCE_LABELS = {
    SOURCE_CENSUS: "Own registered address",
    SOURCE_HIFLD: "Matched fire/EMS station",
}

# --- Design tokens -----------------------------------------------------------
# Chrome/ink and the blue sequential ramp come from the shared viz palette.
# Sequential encoding = one hue, light -> dark (never a rainbow / multi-hue).
PAGE = "#f9f9f7"  # page plane
SURFACE = "#fcfcfb"  # chart surface
INK = "#0b0b0b"  # primary ink
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"  # axis / labels
HAIRLINE = "rgba(11,11,11,0.10)"

# Blue sequential ramp, steps 100 / 200 / 300 / 400 / 550 / 700 — monotone
# light -> dark, so class order is legible as a gradient.
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab", "#0d366b"]
N_CLASSES = len(RAMP)

# County-detail view: unselected counties drop to a near-background fill so
# they read as context, not data; the selected county keeps a mid-ramp blue
# and the pins sit on top in a warm accent that can't be confused with the
# blue sequential scale.
CONTEXT_FILL = "#ececea"
SELECTED_FILL = "#cde2fb"
SELECTED_LINE = "#3987e5"
# Solid pin = the agency's own address. Hollow pin = a station matched by name;
# hollow reads as "less certain" without introducing a second hue that would
# compete with the blue county fill.
PIN = "#c2410c"
PIN_STATION = "#c2410c"

# Ambulance-desert classes. Darker = desert regardless of provenance; the
# lighter amber marks block groups whose only coverage is a HIFLD-matched
# station -- i.e. where the map's answer depends on trusting the name-match.
DESERT_BOTH = "#991b1b"
DESERT_STRICT_ONLY = "#d97706"

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'

METRICS = {
    "Per capita": {
        "column": "stations_per_10k_residents",
        "legend": "Stations per 10,000 residents",
        "unit": "per 10k residents",
        "caption": (
            "Coverage relative to population load — how many stations serve "
            "each 10,000 people."
        ),
    },
    "Per land area": {
        "column": "stations_per_100_sq_mi",
        "legend": "Stations per 100 sq mi",
        "unit": "per 100 sq mi",
        "caption": (
            "Coverage relative to geographic response distance — how many "
            "stations cover each 100 square miles of land."
        ),
    },
}


st.set_page_config(
    page_title="StationScope — NY EMS station access",
    page_icon="🚑",
    layout="wide",
)


@st.cache_data
def load_data() -> tuple[dict, pd.DataFrame]:
    with open(GEOJSON_PATH) as f:
        geojson = json.load(f)
    frame = pd.DataFrame([feature["properties"] for feature in geojson["features"]])
    return geojson, frame


@st.cache_data
def load_agency_data() -> pd.DataFrame:
    return pd.read_csv(AGENCIES_CSV_PATH)


@st.cache_data
def load_desert_data() -> pd.DataFrame:
    return pd.read_csv(
        DESERTS_CSV_PATH, dtype={"geoid": str, "county_fips": str}
    )


def mappable_agencies(agency_frame: pd.DataFrame, county: str) -> pd.DataFrame:
    """Agencies in `county` that have a usable coordinate, from either source."""
    county_rows = agency_frame[agency_frame["county"] == county]
    located = county_rows[county_rows["coordinate_source"].isin(SOURCE_LABELS)]
    return located.dropna(subset=["longitude", "latitude"])


@st.cache_data
def county_bounds(county_fips: str) -> tuple[float, float, float, float]:
    """(min_lon, max_lon, min_lat, max_lat) of one county's geometry."""
    geojson, _ = load_data()
    lons: list[float] = []
    lats: list[float] = []

    def walk(coords) -> None:
        # GeoJSON nests coordinates to varying depth (Polygon vs MultiPolygon);
        # recurse until we hit a bare [lon, lat] pair.
        if coords and isinstance(coords[0], (int, float)):
            lons.append(coords[0])
            lats.append(coords[1])
            return
        for part in coords:
            walk(part)

    for feature in geojson["features"]:
        if feature["properties"]["county_fips"] == county_fips:
            walk(feature["geometry"]["coordinates"])
            break
    if not lons:
        raise ValueError(f"No geometry found for county_fips {county_fips!r}")
    return min(lons), max(lons), min(lats), max(lats)


def zoom_ranges(county_fips: str) -> tuple[list[float], list[float]]:
    """Lon/lat axis ranges framing one county, padded to the map's aspect.

    The geo subplot is roughly twice as wide as it is tall, so a county's raw
    bounding box is widened toward that ratio before padding -- otherwise a
    tall, narrow county (or a tiny one like New York County) renders with the
    state squeezed into a sliver of the available width.
    """
    min_lon, max_lon, min_lat, max_lat = county_bounds(county_fips)
    lon_span = max(max_lon - min_lon, 0.05)
    lat_span = max(max_lat - min_lat, 0.05)

    target_ratio = 2.0
    if lon_span / lat_span < target_ratio:
        lon_span = lat_span * target_ratio

    lon_pad = lon_span * 0.18
    lat_pad = lat_span * 0.18
    lon_mid = (min_lon + max_lon) / 2
    lat_mid = (min_lat + max_lat) / 2
    return (
        [lon_mid - lon_span / 2 - lon_pad, lon_mid + lon_span / 2 + lon_pad],
        [lat_mid - lat_span / 2 - lat_pad, lat_mid + lat_span / 2 + lat_pad],
    )


def build_county_detail_map(
    geojson: dict, frame: pd.DataFrame, points: pd.DataFrame, county: str, total: int
):
    """Zoomed county view: faded statewide context, the county, and its pins.

    Built with graph_objects rather than px because the three layers need
    independent styling -- px.choropleth splits one frame into a trace per
    color class, which fights a "one county highlighted, the rest muted"
    treatment.
    """
    county_row = frame[frame["county"] == county].iloc[0]
    county_fips = county_row["county_fips"]
    figure = go.Figure()

    # Context layer: every county, flat neutral fill. Still clickable, so the
    # neighbouring counties in view double as a way to move between counties.
    figure.add_trace(
        go.Choropleth(
            geojson=geojson,
            locations=frame["county_fips"],
            featureidkey="properties.county_fips",
            z=[0] * len(frame),
            colorscale=[[0, CONTEXT_FILL], [1, CONTEXT_FILL]],
            showscale=False,
            marker_line_color=SURFACE,
            marker_line_width=0.5,
            customdata=frame[["county"]].to_numpy(),
            hovertemplate="%{customdata[0]} County<extra></extra>",
            name="",
        )
    )

    # The selected county, lifted out of the context layer.
    figure.add_trace(
        go.Choropleth(
            geojson=geojson,
            locations=[county_fips],
            featureidkey="properties.county_fips",
            z=[0],
            colorscale=[[0, SELECTED_FILL], [1, SELECTED_FILL]],
            showscale=False,
            marker_line_color=SELECTED_LINE,
            marker_line_width=1.1,
            hoverinfo="skip",
        )
    )

    # One trace per coordinate source, so the legend can state what each pin
    # actually represents instead of implying all pins are equally precise.
    for source, marker, hover_tail in (
        (
            SOURCE_CENSUS,
            dict(size=11, color=PIN, opacity=0.9, symbol="circle",
                 line=dict(width=1.4, color=SURFACE)),
            "%{customdata[1]}<br>%{customdata[2]}",
        ),
        (
            SOURCE_HIFLD,
            dict(size=11, color=PIN_STATION, opacity=0.95, symbol="circle-open",
                 line=dict(width=2.6, color=PIN_STATION)),
            "<i>at %{customdata[4]}</i><br>"
            "<span style='color:" + INK_MUTED + "'>matched station — registered address "
            "is %{customdata[1]}</span>",
        ),
    ):
        subset = points[points["coordinate_source"] == source]
        if subset.empty:
            continue
        figure.add_trace(
            go.Scattergeo(
                lon=subset["longitude"],
                lat=subset["latitude"],
                mode="markers",
                marker=marker,
                customdata=subset[
                    ["agency_name", "street", "city", "type_label", "hifld_station_name"]
                ].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "<span style='color:" + INK_MUTED + "'>%{customdata[3]}</span><br>"
                    + hover_tail
                    + "<extra></extra>"
                ),
                name=SOURCE_LABELS[source],
                showlegend=True,
            )
        )

    # The pin count travels with the map itself, not just the caption around
    # it -- a sparse or empty county has to explain itself when the map is
    # read on its own (or screenshotted) rather than reading as "no stations."
    n_census = int((points["coordinate_source"] == SOURCE_CENSUS).sum()) if not points.empty else 0
    n_station = int((points["coordinate_source"] == SOURCE_HIFLD).sum()) if not points.empty else 0
    annotations = [
        dict(
            text=(
                f"{len(points)} of {total} agencies located "
                f"({n_census} own address, {n_station} matched station)"
            ),
            showarrow=False,
            xref="paper",
            yref="paper",
            x=0.01,
            y=0.02,
            xanchor="left",
            yanchor="bottom",
            font=dict(family=FONT_STACK, size=11.5, color=INK_MUTED),
        )
    ]
    if points.empty:
        annotations.append(
            dict(
                text=(
                    "<b>No mappable addresses</b><br>"
                    f"All {total} registered agencies here list a PO Box or other<br>"
                    "non-street address. This is missing address data,<br>"
                    "not missing coverage — see the full list below."
                ),
                showarrow=False,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                xanchor="center",
                yanchor="middle",
                align="center",
                font=dict(family=FONT_STACK, size=13, color=INK_SECONDARY),
                bgcolor="rgba(252,252,251,0.92)",
                bordercolor=HAIRLINE,
                borderwidth=1,
                borderpad=12,
            )
        )

    lon_range, lat_range = zoom_ranges(county_fips)
    figure.update_layout(annotations=annotations)
    figure.update_geos(
        visible=False,
        bgcolor=SURFACE,
        showframe=False,
        showcoastlines=False,
        showland=False,
        lonaxis_range=lon_range,
        lataxis_range=lat_range,
    )
    figure.update_layout(
        height=580,
        margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        showlegend=not points.empty,
        legend=dict(
            font=dict(size=11.5, color=INK_SECONDARY),
            bgcolor="rgba(252,252,251,0.85)",
            borderwidth=0,
            x=0.985,
            xanchor="right",
            y=0.02,
            yanchor="bottom",
            itemsizing="constant",
            itemclick=False,
            itemdoubleclick=False,
        ),
        font=dict(family=FONT_STACK, color=INK_SECONDARY, size=12.5),
        hoverlabel=dict(
            bgcolor=SURFACE,
            bordercolor=HAIRLINE,
            font=dict(family=FONT_STACK, size=13, color=INK),
            align="left",
        ),
    )
    return figure


def build_classes(frame: pd.DataFrame, column: str) -> tuple[pd.Series, list[str]]:
    """Bin a metric into quantile classes labelled with their real value ranges.

    Both metrics are heavily right-skewed (one county sits several times above
    the median on each), so a linear ramp would collapse most of the state into
    the two lightest steps. Quantile classes spread counties evenly across the
    ramp; the legend carries the actual numeric range of every class so the
    classification stays transparent rather than implied.
    """
    codes, edges = pd.qcut(frame[column], N_CLASSES, labels=False, retbins=True)
    labels = [f"{edges[i]:.2f} – {edges[i + 1]:.2f}" for i in range(N_CLASSES)]
    return codes.map(dict(enumerate(labels))), labels


def inject_styles() -> None:
    st.markdown(
        f"""
        <style>
          .stApp {{ background: {PAGE}; }}
          .block-container {{ max-width: 1180px; padding: 2.6rem 2rem 3.5rem; }}
          [data-testid="stDecoration"], footer {{ display: none; }}
          [data-testid="stElementToolbar"] {{ display: none; }}

          /* Streamlit ships its own face; state ours on every element we own. */
          .ss-eyebrow, .ss-title, .ss-sub, .ss-caption, .ss-note,
          .ss-tile, .ss-tile-label, .ss-tile-value, .ss-tile-unit,
          [data-testid="stRadioGroup"], [data-testid="stSegmentedControl"],
          [data-testid="stDataFrame"] {{
            font-family: {FONT_STACK} !important;
          }}

          .ss-eyebrow {{
            font-size: 11px; font-weight: 600; letter-spacing: 0.09em;
            text-transform: uppercase; color: {INK_MUTED}; margin: 0 0 0.55rem;
          }}
          .ss-title {{
            font-size: 30px; font-weight: 600; letter-spacing: -0.02em;
            color: {INK}; margin: 0 0 0.4rem; line-height: 1.15;
          }}
          .ss-sub {{
            font-size: 15px; color: {INK_SECONDARY}; margin: 0; max-width: 62ch;
            line-height: 1.55;
          }}
          .ss-rule {{
            height: 1px; background: {HAIRLINE}; border: 0;
            margin: 1.9rem 0 1.6rem;
          }}
          .ss-tile {{
            background: {SURFACE}; border: 1px solid {HAIRLINE};
            border-radius: 10px; padding: 15px 17px 16px;
          }}
          .ss-tile-label {{
            font-size: 11px; font-weight: 600; letter-spacing: 0.07em;
            text-transform: uppercase; color: {INK_MUTED}; margin: 0 0 0.5rem;
          }}
          .ss-tile-value {{
            font-size: 27px; font-weight: 600; letter-spacing: -0.02em;
            color: {INK}; line-height: 1; margin: 0;
          }}
          .ss-tile-unit {{
            font-size: 12px; color: {INK_MUTED}; margin: 0.4rem 0 0;
          }}
          .ss-caption {{
            font-size: 13px; color: {INK_SECONDARY}; margin: 0.15rem 0 0;
            line-height: 1.5;
          }}
          .ss-note {{
            font-size: 12px; color: {INK_MUTED}; line-height: 1.6; margin: 0;
          }}
          .ss-note a {{ color: {INK_SECONDARY}; }}

          [data-testid="stSegmentedControl"] button {{
            font-size: 13.5px; letter-spacing: 0.005em;
          }}
          div[data-testid="stDataFrame"] {{ font-variant-numeric: tabular-nums; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def stat_tile(label: str, value: str, unit: str) -> str:
    return (
        f'<div class="ss-tile"><p class="ss-tile-label">{label}</p>'
        f'<p class="ss-tile-value">{value}</p>'
        f'<p class="ss-tile-unit">{unit}</p></div>'
    )


def render_county_drilldown(frame: pd.DataFrame, agency_frame: pd.DataFrame) -> None:
    """Selecting a county (map click or dropdown) shows its individual agencies.

    The dropdown owns `st.session_state["county_selectbox"]` via its `key`.
    A map click seeds that same session_state entry *before* this widget is
    created (see `main()`), which is the supported way to drive a keyed
    widget programmatically — passing a separately-computed `index` here
    instead would make the widget's identity unstable across reruns and
    silently drop the pending selection.
    """
    st.markdown('<p class="ss-eyebrow">County detail</p>', unsafe_allow_html=True)

    county_options = [NO_COUNTY_SELECTED] + sorted(frame["county"])
    st.session_state.setdefault("county_selectbox", NO_COUNTY_SELECTED)
    choice = st.selectbox(
        "Choose a county",
        county_options,
        key="county_selectbox",
        label_visibility="collapsed",
    )
    selected_county = None if choice == NO_COUNTY_SELECTED else choice

    if selected_county is None:
        st.markdown(
            '<p class="ss-note">Click a county on the map above, or choose one '
            "here, to see its individually registered EMS agencies.</p>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<p class="ss-caption" style="margin-top:0.9rem;"><b>{selected_county} '
        "County</b></p>",
        unsafe_allow_html=True,
    )
    county_agencies = agency_frame[agency_frame["county"] == selected_county]

    for type_key, type_label in AGENCY_TYPES:
        subset = (
            county_agencies[county_agencies["agency_type"] == type_key][["agency_name", "city"]]
            .sort_values("agency_name")
        )
        st.markdown(
            f'<p class="ss-caption">{type_label} ({len(subset)})</p>',
            unsafe_allow_html=True,
        )
        if subset.empty:
            st.markdown(
                f'<p class="ss-note">No {type_label} agencies registered in '
                f"{selected_county} County.</p>",
                unsafe_allow_html=True,
            )
            continue
        st.dataframe(
            subset,
            hide_index=True,
            width="stretch",
            height=min(38 * (len(subset) + 1) + 3, 320),
            column_config={
                "agency_name": st.column_config.TextColumn("Agency", width="large"),
                "city": st.column_config.TextColumn("City", width="medium"),
            },
        )


def build_map(geojson: dict, frame: pd.DataFrame, metric_key: str):
    metric = METRICS[metric_key]
    column = metric["column"]

    plot_frame = frame.copy()
    plot_frame["class"], labels = build_classes(plot_frame, column)

    figure = px.choropleth(
        plot_frame,
        geojson=geojson,
        locations="county_fips",
        featureidkey="properties.county_fips",
        color="class",
        color_discrete_map=dict(zip(labels, RAMP)),
        # Darkest (highest) class first, so the legend reads top-down as the
        # ramp does.
        category_orders={"class": labels[::-1]},
        custom_data=[
            "county",
            "stations_per_10k_residents",
            "stations_per_100_sq_mi",
            "total_station_count",
            "population_2025",
            "land_area_sq_mi",
        ],
        fitbounds="locations",
        basemap_visible=False,
    )

    # Hover always carries BOTH metrics, with the active one emphasised — the
    # reader never has to toggle to compare the two.
    active_capita = metric_key == "Per capita"
    capita_row = (
        f"{'<b>' if active_capita else ''}%{{customdata[1]:.2f}} per 10k residents"
        f"{'</b>' if active_capita else ''}"
    )
    area_row = (
        f"{'<b>' if not active_capita else ''}%{{customdata[2]:.2f}} per 100 sq mi"
        f"{'</b>' if not active_capita else ''}"
    )
    context_row = (
        "<span style='color:" + INK_MUTED + "'>"
        "%{customdata[3]} stations · %{customdata[4]:,} residents · "
        "%{customdata[5]:,.0f} sq mi</span>"
    )
    figure.update_traces(
        marker_line_color=SURFACE,
        marker_line_width=0.6,
        hovertemplate=(
            "<b>%{customdata[0]} County</b><br>"
            + capita_row
            + "<br>"
            + area_row
            + "<br>"
            + context_row
            + "<extra></extra>"
        ),
    )

    figure.update_geos(
        visible=False,
        bgcolor=SURFACE,
        showframe=False,
        showcoastlines=False,
        showland=False,
    )
    figure.update_layout(
        height=580,
        margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_STACK, color=INK_SECONDARY, size=12.5),
        legend=dict(
            title=dict(
                text=f"<b>{metric['legend']}</b>",
                font=dict(size=11.5, color=INK_MUTED),
            ),
            font=dict(size=12, color=INK_SECONDARY),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            x=0.985,
            xanchor="right",
            y=0.5,
            yanchor="middle",
            itemsizing="constant",
            itemclick=False,
            itemdoubleclick=False,
        ),
        hoverlabel=dict(
            bgcolor=SURFACE,
            bordercolor=HAIRLINE,
            font=dict(family=FONT_STACK, size=13, color=INK),
            align="left",
        ),
    )
    return figure


def handle_map_click(map_event, selected_county: str | None, valid_counties: set[str]) -> None:
    """Apply a map click to the shared selection, then redraw.

    The chart's `key` is derived from the current selection, so changing the
    selection swaps in a fresh chart widget with no retained selection state.
    That's what keeps the two inputs from fighting: without it, a stale click
    event would replay on every later rerun and stomp the dropdown's value.

    Clicks are validated against the real county list because the county
    detail map has more than one clickable layer -- a click on an agency pin
    carries an agency name in the same customdata slot, and must not be
    mistaken for a county selection.
    """
    clicked_points = map_event["selection"]["points"] if map_event else []
    if not clicked_points:
        return
    clicked = clicked_points[0].get("customdata")
    if not clicked or clicked[0] not in valid_counties:
        return
    if clicked[0] != selected_county:
        st.session_state["county_selectbox"] = clicked[0]
        st.rerun()


def render_statewide_map(geojson: dict, frame: pd.DataFrame, metric_key: str) -> None:
    map_event = st.plotly_chart(
        build_map(geojson, frame, metric_key),
        width="stretch",
        config={"displayModeBar": False, "scrollZoom": False},
        on_select="rerun",
        selection_mode=["points"],
        key="county_map::all",
    )
    st.markdown(
        '<p class="ss-note">Counties are grouped into six equal-count '
        "(quantile) classes; each legend entry shows that class's actual value "
        "range. Both metrics are strongly right-skewed, so equal-width classes "
        "would leave most of the state in a single shade. Per-capita outliers "
        "in very low-population counties (e.g., Hamilton, population ~5,000) "
        "may reflect small-sample noise rather than genuine service "
        "differences — interpret extreme values in sparse counties "
        "cautiously.</p>",
        unsafe_allow_html=True,
    )
    handle_map_click(map_event, None, set(frame["county"]))


def render_county_map(
    geojson: dict, frame: pd.DataFrame, agency_frame: pd.DataFrame, county: str
) -> None:
    """Zoomed county view with agency pins, plus an explicit coverage caveat."""
    type_labels = dict(AGENCY_TYPES)
    points = mappable_agencies(agency_frame, county).copy()
    points["type_label"] = points["agency_type"].map(type_labels)
    total = int((agency_frame["county"] == county).sum())
    mapped = len(points)
    n_census = int((points["coordinate_source"] == SOURCE_CENSUS).sum()) if mapped else 0
    n_station = mapped - n_census

    st.markdown(
        f'<p class="ss-caption"><b>{county} County</b> — {mapped} of {total} '
        f"registered agencies shown as pins: {n_census} at their own registered "
        f"address, {n_station} at a fire/EMS station matched by name.</p>",
        unsafe_allow_html=True,
    )

    map_event = st.plotly_chart(
        build_county_detail_map(geojson, frame, points, county, total),
        width="stretch",
        config={"displayModeBar": False, "scrollZoom": False},
        on_select="rerun",
        selection_mode=["points"],
        key=f"county_map::{county}",
    )

    # The gap between `mapped` and `total` is a geocoding artifact, not a
    # coverage finding -- say so on the map itself, since an empty or sparse
    # county otherwise reads as "no stations here."
    unmapped = total - mapped
    station_note = (
        f" {n_station} pin{'s' if n_station != 1 else ''} mark"
        f"{'' if n_station != 1 else 's'} a fire/EMS station matched to the agency "
        "by name (hollow pins) rather than the agency's own address, so the point "
        "is that station's location, not a geocode of anything the agency "
        "registered."
        if n_station
        else ""
    )
    if mapped == 0:
        note = (
            f"<b>No pins available for {county} County.</b> None of its {total} "
            "registered agencies could be placed on the map — they list PO Boxes "
            "or other non-street addresses with no point to geocode against, and "
            "none matched a fire/EMS station by name. <b>This is missing address "
            f"data, not missing coverage:</b> all {total} agencies are listed in "
            "full below."
        )
    elif unmapped:
        note = (
            f"{unmapped} of this county's {total} agencies could not be placed on "
            "the map — their registered addresses are PO Boxes or otherwise did "
            "not geocode, and no station matched them by name. <b>The pins "
            "undercount stations; they don't measure coverage.</b>"
            + station_note
            + " The full list of all agencies, mapped or not, is below."
        )
    else:
        note = (
            f"All {total} registered agencies in this county are placed."
            + station_note
            + " Pins mark a registered or matched address, which is not always a "
            "staffed station."
        )
    st.markdown(f'<p class="ss-note">{note}</p>', unsafe_allow_html=True)
    handle_map_click(map_event, county, set(frame["county"]))


def build_desert_map(geojson: dict, frame: pd.DataFrame, deserts: pd.DataFrame):
    """Statewide three-class desert map.

    Covered block groups (95%+ of the state) are deliberately not plotted --
    the map's subject is the exception, and 15,000 "fine here" dots would
    bury the few hundred that aren't. Counties render as neutral context.
    """
    figure = go.Figure()
    figure.add_trace(
        go.Choropleth(
            geojson=geojson,
            locations=frame["county_fips"],
            featureidkey="properties.county_fips",
            z=[0] * len(frame),
            colorscale=[[0, CONTEXT_FILL], [1, CONTEXT_FILL]],
            showscale=False,
            marker_line_color=SURFACE,
            marker_line_width=0.5,
            customdata=frame[["county"]].to_numpy(),
            hovertemplate="%{customdata[0]} County<extra></extra>",
            name="",
            showlegend=False,
        )
    )

    plot = deserts[deserts["desert_class"] != "covered"].copy()

    def minutes_label(value) -> str:
        # Empty drive time = OSRM found no road route at all (ferry-only
        # islands); say so instead of rendering "nan min".
        return f"{value:.0f} min" if pd.notna(value) else "no road route"

    plot["strict_label"] = plot["drive_min_strict"].map(minutes_label)
    plot["full_label"] = plot["drive_min_full"].map(minutes_label)
    plot["nearest_label"] = plot["nearest_station_full"].fillna(
        "none reachable by road"
    )

    for class_key, label, color in (
        ("desert_both", "Desert under both scenarios", DESERT_BOTH),
        ("desert_strict_only", "Covered only by a name-matched station", DESERT_STRICT_ONLY),
    ):
        subset = plot[plot["desert_class"] == class_key]
        if subset.empty:
            continue
        figure.add_trace(
            go.Scattergeo(
                lon=subset["longitude"],
                lat=subset["latitude"],
                mode="markers",
                marker=dict(size=6, color=color, opacity=0.75,
                            line=dict(width=0.5, color=SURFACE)),
                customdata=subset[
                    ["county", "population", "strict_label", "full_label", "nearest_label"]
                ].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]} County</b> — %{customdata[1]:,} residents<br>"
                    "own-address stations only: %{customdata[2]}<br>"
                    "with name-matched stations: %{customdata[3]}<br>"
                    "<span style='color:" + INK_MUTED + "'>nearest located station: "
                    "%{customdata[4]}</span>"
                    "<extra></extra>"
                ),
                name=label,
                showlegend=True,
            )
        )

    figure.update_geos(
        visible=False,
        bgcolor=SURFACE,
        showframe=False,
        showcoastlines=False,
        showland=False,
        fitbounds="locations",
    )
    figure.update_layout(
        height=580,
        margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_STACK, color=INK_SECONDARY, size=12.5),
        legend=dict(
            font=dict(size=11.5, color=INK_SECONDARY),
            bgcolor="rgba(252,252,251,0.85)",
            borderwidth=0,
            x=0.985, xanchor="right", y=0.98, yanchor="top",
            itemsizing="constant", itemclick=False, itemdoubleclick=False,
        ),
        hoverlabel=dict(
            bgcolor=SURFACE,
            bordercolor=HAIRLINE,
            font=dict(family=FONT_STACK, size=13, color=INK),
            align="left",
        ),
        # The two caveats that must survive a screenshot of the map alone:
        # every figure is a coverage floor, and borders are blind spots.
        annotations=[
            dict(
                text=("<b>Upper bound, not a measurement:</b> computed from 690 of "
                      "1,043 registered ambulance/ALS agencies —<br>the 353 without "
                      "a usable address (mostly PO Boxes, skewing rural) can only "
                      "shrink these deserts, never grow them."),
                showarrow=False, xref="paper", yref="paper",
                x=0.01, y=0.03, xanchor="left", yanchor="bottom", align="left",
                font=dict(family=FONT_STACK, size=11.5, color=INK_SECONDARY),
                bgcolor="rgba(252,252,251,0.92)",
                bordercolor=HAIRLINE, borderwidth=1, borderpad=6,
            ),
            dict(
                text=("Out-of-state stations are not in the NY registry — "
                      "deserts hugging the PA/VT/NJ/CT/MA borders are overstated."),
                showarrow=False, xref="paper", yref="paper",
                x=0.01, y=0.145, xanchor="left", yanchor="bottom", align="left",
                font=dict(family=FONT_STACK, size=11, color=INK_MUTED),
            ),
        ],
    )
    return figure


def render_desert_analysis(geojson: dict, frame: pd.DataFrame) -> None:
    deserts = load_desert_data()
    total_pop = int(deserts["population"].sum())
    strict_pop = int(deserts.loc[deserts["desert_strict"], "population"].sum())
    full_pop = int(deserts.loc[deserts["desert_full"], "population"].sum())
    n_counties_strict = deserts.loc[deserts["desert_strict"], "county"].nunique()

    st.markdown('<p class="ss-eyebrow">Ambulance deserts</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ss-sub">Census block groups more than 25 minutes\' drive from '
        "the nearest ambulance station (the Maine Rural Health Research Center "
        "definition), computed on the real road network. Only transporting "
        "ambulance/ALS agencies count — a BLS first-response agency with no "
        "ambulance does not end a desert. Two scenarios: <b>strict</b> uses only "
        "stations at their own geocoded address; <b>full</b> adds stations "
        "located by name-matching against the HIFLD fire/EMS layer.</p>",
        unsafe_allow_html=True,
    )

    tiles = [
        ("Desert population (strict)", f"{strict_pop:,}",
         f"{100 * strict_pop / total_pop:.1f}% of NY, own-address stations only"),
        ("Desert population (full)", f"{full_pop:,}",
         f"{100 * full_pop / total_pop:.1f}% of NY, incl. name-matched stations"),
        ("Provenance gap", f"{strict_pop - full_pop:,}",
         "people whose coverage depends on the name-match"),
        ("Counties touched", f"{n_counties_strict} of 62",
         "contain at least one desert block group (strict)"),
    ]
    for column, (label, value, unit) in zip(st.columns(4, gap="small"), tiles):
        column.markdown(stat_tile(label, value, unit), unsafe_allow_html=True)

    # theme=None: every color/font in this figure is set explicitly, so
    # Streamlit's theme pass adds nothing and skipping it avoids a benign
    # console TypeError it emits on this figure. No `key`: the chart is
    # stateless (no selection events). Verified that map-click selection on
    # the charts above works with this section present.
    st.plotly_chart(
        build_desert_map(geojson, frame, deserts),
        width="stretch",
        theme=None,
        config={"displayModeBar": False, "scrollZoom": False},
    )

    st.markdown(
        '<p class="ss-note">Drive times are station → block group (the direction '
        "an ambulance travels), measured on OpenStreetMap roads via OSRM. Route "
        "spot-checks against Google Maps matched road distances exactly but ran "
        "4–37% slower on rural roads — a conservative bias that, like the "
        "unlocated agencies and the missing out-of-state stations, makes these "
        "deserts an upper bound. Four Shelter Island block groups (pop. 3,253) "
        "have no road connection to any located station and are classified "
        "desert by construction — the island's own EMS agency is registered to "
        "a PO Box and could not be placed.</p>",
        unsafe_allow_html=True,
    )


def main() -> None:
    inject_styles()
    geojson, frame = load_data()
    agency_frame = load_agency_data()

    st.markdown(
        '<p class="ss-eyebrow">StationScope</p>'
        '<h1 class="ss-title">EMS station access across New York State</h1>'
        '<p class="ss-sub">Every certified EMS agency in New York, mapped by '
        "county. Read the two densities together: a county can look well-served "
        "by population and thinly covered by geography — or the reverse.</p>",
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="ss-rule">', unsafe_allow_html=True)

    total_stations = int(frame["total_station_count"].sum())
    total_population = int(frame["population_2025"].sum())
    total_area = float(frame["land_area_sq_mi"].sum())
    tiles = [
        ("Counties", "62", "all of New York State"),
        ("EMS agencies", f"{total_stations:,}", "certified, statewide"),
        (
            "Statewide per capita",
            f"{total_stations / (total_population / 10_000):.2f}",
            "stations per 10k residents",
        ),
        (
            "Statewide per area",
            f"{total_stations / (total_area / 100):.2f}",
            "stations per 100 sq mi",
        ),
    ]
    for column, (label, value, unit) in zip(st.columns(4, gap="small"), tiles):
        column.markdown(stat_tile(label, value, unit), unsafe_allow_html=True)

    st.markdown('<hr class="ss-rule">', unsafe_allow_html=True)

    # The selected county is read *before* the map is drawn, so the map can
    # render its zoomed state on the same run the selection changes.
    selected_county = st.session_state.get("county_selectbox")
    if selected_county == NO_COUNTY_SELECTED:
        selected_county = None

    # Filter row sits above everything it scopes. It colors the statewide map
    # and orders the county table below; in the zoomed county view only the
    # table is affected, so the label follows what it's actually doing.
    st.markdown(
        f'<p class="ss-eyebrow">{"Rank counties by" if selected_county else "Color counties by"}</p>',
        unsafe_allow_html=True,
    )
    metric_key = st.segmented_control(
        "Color counties by",
        list(METRICS),
        default=next(iter(METRICS)),
        label_visibility="collapsed",
    )
    # A segmented control can be cleared by clicking the active option; keep the
    # map on a real choice rather than rendering an empty state.
    if metric_key is None:
        metric_key = next(iter(METRICS))
    if selected_county is None:
        st.markdown(
            f'<p class="ss-caption">{METRICS[metric_key]["caption"]}</p>',
            unsafe_allow_html=True,
        )

    if selected_county is None:
        render_statewide_map(geojson, frame, metric_key)
    else:
        render_county_map(geojson, frame, agency_frame, selected_county)

    st.markdown('<hr class="ss-rule">', unsafe_allow_html=True)

    render_county_drilldown(frame, agency_frame)

    st.markdown('<hr class="ss-rule">', unsafe_allow_html=True)

    render_desert_analysis(geojson, frame)

    st.markdown('<hr class="ss-rule">', unsafe_allow_html=True)

    # Table view twin — every value on the map is readable without hovering.
    st.markdown('<p class="ss-eyebrow">All 62 counties</p>', unsafe_allow_html=True)
    table = frame[
        [
            "county",
            "total_station_count",
            "ambulance_als_station_count",
            "bls_nontransport_station_count",
            "population_2025",
            "land_area_sq_mi",
            "stations_per_10k_residents",
            "stations_per_100_sq_mi",
        ]
    ].sort_values(METRICS[metric_key]["column"], ascending=False)
    # Square miles to the nearest whole mile — the decimals are noise at this scale.
    table["land_area_sq_mi"] = table["land_area_sq_mi"].round().astype(int)

    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "county": st.column_config.TextColumn("County", width="medium"),
            "total_station_count": st.column_config.NumberColumn("Stations"),
            "ambulance_als_station_count": st.column_config.NumberColumn("Ambulance / ALS"),
            "bls_nontransport_station_count": st.column_config.NumberColumn("BLS non-transport"),
            "population_2025": st.column_config.NumberColumn(
                "Population", format="localized"
            ),
            "land_area_sq_mi": st.column_config.NumberColumn(
                "Land area (sq mi)", format="localized"
            ),
            "stations_per_10k_residents": st.column_config.NumberColumn(
                "Per 10k residents", format="%.2f"
            ),
            "stations_per_100_sq_mi": st.column_config.NumberColumn(
                "Per 100 sq mi", format="%.2f"
            ),
        },
    )

    st.markdown('<hr class="ss-rule">', unsafe_allow_html=True)
    st.markdown(
        '<p class="ss-note"><b>Sources.</b> Station counts: NY State Department '
        "of Health, Bureau of EMS agency registry (ambulance/ALS and BLS "
        "non-transporting listings, 6 Jul 2026). Population: US Census Bureau "
        "Vintage 2025 county population estimates. Land area: US Census Bureau "
        "2025 Gazetteer. County boundaries: US Census Bureau TIGER/Line 2025."
        "<br>Counts reflect <i>certified agencies</i> registered with the state, "
        "which is not always the same as staffed physical stations.</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
