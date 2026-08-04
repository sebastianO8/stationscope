# StationScope

StationScope maps EMS (Emergency Medical Services) station access across New
York State, county by county. It starts with all 62 counties computed at
once (see [CLAUDE.md](CLAUDE.md) for the pilot-county framing) and renders
an interactive choropleth in a single Streamlit app.

## What it measures, and why

Two metrics, meant to be read together:

- **Station density per capita** — stations per 10,000 residents
- **Station density per land area** — stations per 100 sq mi

Per-capita density highlights coverage relative to population load; per-area
density highlights coverage relative to geographic response distance. A
county can look well-served on one and poorly-served on the other — that
gap is the thing worth surfacing, not either number alone.

## Data sources

| Source | Used for | Vintage | Downloaded |
|---|---|---|---|
| NY DOH Bureau of EMS agency registry (two statewide PDFs: ambulance/ALS, BLS non-transport) | Station counts, per county | 2026-07-06 | 2026-08-03 |
| US Census Bureau county population estimates | Population, per county | Vintage 2025 | 2026-08-03 |
| US Census Bureau Gazetteer files | Land area, per county | 2025 | 2026-08-03 |
| US Census Bureau TIGER/Line county boundaries | Map geometry | 2025 | 2026-08-03 |
| HIFLD Fire/EMS Stations (via Source Cooperative archive) | Station coordinates (not yet joined) | Jan 2025 | 2026-08-03 |

Raw files live in `data/raw/` with source URLs; see `scripts/` for the
pipelines that turn them into `data/processed/`.

## Key methodology decisions

**DOH registry as the primary station-count source, not HIFLD.** The
original plan was to build station counts from HIFLD's "EMS Stations"
layer, but that standalone dataset is no longer hosted anywhere — the HIFLD
ArcGIS Online portal was decommissioned around 2025-08-25. The dataset still
available (via a Source Cooperative archive) is a *combined* "Fire and EMS
Stations" layer that doesn't distinguish the two, so it's unsuitable as a
station count. NY's own DOH Bureau of EMS registry turned out to be a better
primary source anyway — it's the state's authoritative list of certified EMS
agencies, organized by county, and it's what the two density metrics are
built from. HIFLD is kept only as a candidate coordinate source for a future
map-marker layer, joined by address — not yet built.

**FIPS code as the county join key, not county name.** County boundaries
(TIGER/Line) are joined to the density metrics on the 5-digit county FIPS
code, not the county name string. Names format inconsistently across
sources (DOH's PDFs say "St. Lawrence"; other sources may say "Saint
Lawrence" or omit "County" entirely), so FIPS is the only reliable key. The
join is validated on every run: 62/62 counties must match with no drops and
no duplicates on either side, or the build script raises instead of writing
a partial result.

**Quantile classification, not a linear color scale.** Both metrics are
strongly right-skewed — each has one extreme outlier well above the rest of
the state. A linear (equal-width) color scale would collapse roughly 90% of
counties into the lightest one or two shades, hiding most of the real
variation. The map instead groups counties into six equal-count (quantile)
classes, with the legend showing each class's actual value range rather
than implying a uniform scale.

## Two real findings

**Bronx and Nassau invert between the two metrics.** Bronx has 8 stations
for 1.41M residents (0.057 per 10k — the lowest in the state) but only 42
sq mi of land (18.96 per 100 sq mi — among the highest). Nassau shows the
same pattern at a different scale: 77 stations for 1.40M residents (0.55
per 10k) packed into 285 sq mi (27.06 per 100 sq mi — third-highest
statewide, behind only New York and Kings counties). Both counties look
thinly covered by population and densely covered by geography — exactly
the divergence the two metrics exist to catch, and neither number alone
would show it.

**Hamilton's per-capita rate is a small-sample artifact, not a service
signal.** Hamilton County — New York's least populous, at roughly 5,000
residents — has 7 EMS stations, which works out to 13.98 stations per
10,000 residents — about 2x the next-highest county (Schuyler, 7.09) and
over 5x the statewide median (2.70). This isn't Hamilton being unusually
well-served; it's what happens when a small, mostly fixed number of rural
stations gets divided by a very small population base. The same 7 stations
would barely
register as a rate in a populous county. Per-capita outliers in sparse
counties like this should be read cautiously rather than taken as a genuine
service-level difference — a note to this effect appears both in the app
(under the map) and in CLAUDE.md's limitations log.

## Running the app

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## Architecture

See [CLAUDE.md](CLAUDE.md) for the full project conventions: a single
Streamlit app reading a precomputed data file, no backend server, no
database, and a running limitations log for data quirks discovered along
the way.
