# StationScope

StationScope is an open-source tool mapping EMS (Emergency Medical Services) station
access across New York State. It starts with a pilot set of 5-6 counties — a mix of
urban, suburban, and rural — before expanding to all 62 NY counties.

## Metrics

- **Station density per capita** — stations per 10,000 residents
- **Station density per land area** — stations per 100 sq mi

These two metrics are meant to be read together: per-capita density highlights
coverage relative to population load, while per-land-area density highlights
coverage relative to geographic response distance. A county can look well-served
on one and poorly-served on the other.

## Architecture

StationScope is intentionally simple:

- A **single Streamlit app** (`app/`) is the entire interface.
- The app reads a **precomputed data file** — there is no separate backend
  server and no hosted database.
- All data prep (cleaning, joining station/county/population data, computing
  the two density metrics) happens **offline**, via scripts in `scripts/`, and
  is written out to `data/processed/`.
- The Streamlit app never talks to external APIs or databases at runtime; it
  just loads the processed file and renders it.

This keeps deployment trivial (e.g. Streamlit Community Cloud) and keeps the
whole project understandable by a single person or small volunteer team.

## Project structure

```
data/
  raw/         # source data as obtained (EMS station lists, county boundaries,
               #  population figures) — unmodified, cite sources here
  processed/   # cleaned/joined data + computed metrics, consumed by the app
scripts/       # data prep: raw -> processed
app/           # Streamlit app (reads only from data/processed)
```

## Pilot counties

Starting scope is 5-6 counties chosen to represent NY's urban/suburban/rural
mix. When adding a new pilot county, make sure raw data sources exist and are
comparable in quality/format to the existing ones before including it —
inconsistent source data is worse than a smaller pilot set.

## Conventions

- Don't add a backend server or database. If the data needs to be queried
  more dynamically than a flat file allows, that's a sign to revisit this
  doc and discuss before building around it.
- Data prep scripts should be re-runnable: raw -> processed should be a
  repeatable, scripted pipeline, not manual edits to processed files.
- Cite the source and vintage (year/date pulled) for any new raw dataset
  added to `data/raw/`.

## Limitations / things we've learned

This section is a running log of gotchas, data quirks, and constraints
discovered while building StationScope. Add to it as they come up — future
work (including expanding to more counties) should check here first.

<!-- Add entries below as they're discovered, e.g.:
- [2026-XX-XX] County X's EMS station list double-counts stations that serve
  multiple districts — dedupe by station ID, not by name.
-->

- [2026-08-03] The standalone HIFLD "Emergency Medical Service (EMS) Stations"
  layer (the EMS-only dataset data.gov cites) is no longer hosted anywhere we
  could find — the HIFLD ArcGIS Online portal was decommissioned around
  2025-08-25. The dataset actually available (via the Source Cooperative
  archive at source.coop/seerai/hifld) is "Fire and Emergency Medical Service
  (EMS) Stations," a *combined* USGS National Structures layer that does not
  distinguish EMS/ambulance stations from fire stations. We use it only as a
  coordinate source for map display, joined against the NY DOH registry below
  — never as a station count or category source.

- [2026-08-03] NY's authoritative EMS station *count* comes from the NY DOH
  Bureau of EMS agency registry (two statewide PDFs: ambulance/ALS services
  and BLS non-transporting agencies, linked from
  health.ny.gov/professionals/ems/counties/). Both are organized by county
  with repeating "County of X" headers, so county-level counts can be pulled
  directly without needing a geographic join. See
  scripts/build_ems_station_density.py.

- [2026-08-03] The DOH PDFs have no lat/long — they're mailing-address
  listings only. Counts and the two density metrics can be computed straight
  from the registry, but map-view coordinates still require a separate
  geocoding/join step (candidate: the HIFLD combined dataset above, joined by
  address/city — not yet built).

- [2026-08-03] Parsing the DOH PDFs is heuristic, not a structured export:
  text layout has overlapping columns (service ID digits get smashed into the
  service name in naive extraction), so `build_ems_station_density.py` counts
  one agency per "City, ST ZIP" line via `pdfplumber`'s `layout=True` mode
  rather than parsing every field.

  The ambulance/ALS PDF (`agency_list_aalffrs.pdf`) prints its own per-county
  "Level of Care Totals" subtotal, so it could be validated exhaustively, not
  just spot-checked: parsed counts matched the document's own subtotal for
  **all 63 sections** (62 counties + "Out Of State"), zero mismatches —
  including Erie, Kings, Nassau, Essex, and Hamilton (smallest-population NY
  county) as diversity checks across urban/suburban/rural and small/large.

  The BLS non-transport PDF (`agency_list_blsnt.pdf`) has no such built-in
  subtotal, so 5 counties were instead verified by hand (reading the raw
  extracted text and counting agencies line-by-line): Onondaga (45, urban),
  Rensselaer (28 — this county's BLS list is larger than its ALS list, a
  "primarily BLS" case), Cortland (10), Schoharie (4, rural), and Kings (1,
  NYC borough). All 5 matched the parser exactly. Note: an ad hoc secondary
  check (counting a different per-record marker line) was tried first for
  BLSNT and gave *lower* counts for several counties (e.g. 43 vs 45 for
  Onondaga) — manual recount confirmed the parser's "City, ST ZIP" count
  (45) was correct and the secondary marker was the flawed one, undercounting
  due to its own regex fragility. Kept here as a caution against trusting a
  second automated method over careful manual verification when the two
  disagree.

  Combined: 11 distinct counties now verified exactly (Chemung, Suffolk,
  Erie, Kings, Nassau, Essex, Hamilton, Onondaga, Rensselaer, Cortland,
  Schoharie — Kings was checked in both PDFs), plus all 63 AALFFRS sections
  via the document's own subtotals. No discrepancies found anywhere.
