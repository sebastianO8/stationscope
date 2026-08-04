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
import streamlit as st

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"
GEOJSON_PATH = PROCESSED / "ny_ems_station_density_by_county.geojson"

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


def main() -> None:
    inject_styles()
    geojson, frame = load_data()

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

    # Filter row sits above everything it scopes.
    st.markdown('<p class="ss-eyebrow">Color counties by</p>', unsafe_allow_html=True)
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
    st.markdown(
        f'<p class="ss-caption">{METRICS[metric_key]["caption"]}</p>',
        unsafe_allow_html=True,
    )

    st.plotly_chart(
        build_map(geojson, frame, metric_key),
        width="stretch",
        config={"displayModeBar": False, "scrollZoom": False},
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
