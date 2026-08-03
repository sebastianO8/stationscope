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
