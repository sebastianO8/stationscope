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
# The geocoded file is a superset of ny_ems_agencies.csv (same rows, same
# order, plus geocode columns), so it drives both the pin layer and the
# full drill-down list -- one load, and the two can't drift apart.
AGENCIES_CSV_PATH = PROCESSED / "ny_ems_agencies_geocoded.csv"

NO_COUNTY_SELECTED = "— All counties —"
AGENCY_TYPES = [
    ("ambulance_als", "Ambulance / ALS"),
    ("bls_nontransport", "BLS non-transport"),
]
# Census batch geocoder statuses. "Match" covers both Exact and Non_Exact
# (interpolated) results; "Tie" (ambiguous) and "No_Match" have no usable
# coordinate and are deliberately not plotted.
MAPPABLE_STATUS = "Match"

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
PIN = "#c2410c"

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


def mappable_agencies(agency_frame: pd.DataFrame, county: str) -> pd.DataFrame:
    """Agencies in `county` that have a usable geocoded coordinate."""
    county_rows = agency_frame[agency_frame["county"] == county]
    return county_rows[county_rows["match_status"] == MAPPABLE_STATUS].dropna(
        subset=["longitude", "latitude"]
    )


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

    if not points.empty:
        figure.add_trace(
            go.Scattergeo(
                lon=points["longitude"],
                lat=points["latitude"],
                mode="markers",
                marker=dict(
                    size=11,
                    color=PIN,
                    opacity=0.9,
                    line=dict(width=1.4, color=SURFACE),
                ),
                customdata=points[["agency_name", "street", "city", "type_label"]].to_numpy(),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "<span style='color:" + INK_MUTED + "'>%{customdata[3]}</span><br>"
                    "%{customdata[1]}<br>%{customdata[2]}"
                    "<extra></extra>"
                ),
                name="",
            )
        )

    # The pin count travels with the map itself, not just the caption around
    # it -- a sparse or empty county has to explain itself when the map is
    # read on its own (or screenshotted) rather than reading as "no stations."
    annotations = [
        dict(
            text=f"{len(points)} of {total} agencies mapped",
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
        showlegend=False,
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

    st.markdown(
        f'<p class="ss-caption"><b>{county} County</b> — '
        f"{mapped} of {total} registered agencies shown as pins.</p>",
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
    if mapped == 0:
        note = (
            f"<b>No pins available for {county} County.</b> None of its {total} "
            "registered agencies could be placed on the map — every one lists a "
            "PO Box or other non-street mailing address, which has no point to "
            "geocode against. <b>This is missing address data, not missing "
            "coverage:</b> all {total} agencies are listed in full below."
        ).replace("{total}", str(total))
    elif unmapped:
        note = (
            f"{unmapped} of this county's {total} agencies could not be placed on "
            "the map — their registered addresses are PO Boxes or otherwise did "
            "not geocode. <b>The pins undercount stations; they don't measure "
            "coverage.</b> The full list of all agencies, mapped or not, is below."
        )
    else:
        note = (
            f"All {total} registered agencies in this county have a geocoded "
            "street address. Pins mark the registered mailing address, which is "
            "not always a staffed station."
        )
    st.markdown(f'<p class="ss-note">{note}</p>', unsafe_allow_html=True)
    handle_map_click(map_event, county, set(frame["county"]))


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
