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

- [2026-08-03] Per-capita outliers in very low-population counties (e.g.,
  Hamilton, population ~5,000) may reflect small-sample noise rather than
  genuine service differences — interpret extreme values in sparse counties
  cautiously. A handful of stations swings the per-10k-residents rate wildly
  when the denominator is a few thousand people; the same handful barely
  moves the rate in a populous county. This caveat is echoed in the app's
  methodology note under the map.

- [2026-08-04] Extracting individual agency *names* (not just counts) from
  the DOH PDFs required going beyond `pdfplumber`'s `extract_text()`, which
  sorts characters by x-position to reconstruct reading order. That sorting
  is exactly what causes the "service ID digits get smashed into the
  service name" quirk logged above: the 4-digit Service ID is drawn at a
  fixed column x-position regardless of name length, and when a name is
  long enough to reach that x-position, x-sorting interleaves the ID's
  digits into the name character-by-character (e.g. "Rocky Mtn Holdings
  LLC" + ID 0767 flattens to "Rocky Mtn 0H7o6l7dings LLC"). No regex over
  that flattened text can undo it. The fix (see
  `group_rows_global`/`split_name_id` in `build_ems_station_density.py`):
  read `page.chars` directly, group into rows by y-position while
  preserving each character's *original stream order* within a row (which
  keeps the full name intact ahead of the ID's digits, no interleaving),
  then find the ID by scanning for the first digit whose x-position lands
  within a few points of the known Service ID column — not by taking "the
  last digit run in the text" (which would wrongly merge in-name digits
  like "Clarence Fire District **#1**" with an adjacent real ID). Validated
  by re-deriving agency counts from the extracted records and asserting
  they match `count_agencies_by_county`'s independent, already-verified
  counts — 63/63 sections matched exactly for both PDFs once the bug below
  was also fixed.

  This same pass also found and fixed a real off-by-one in the
  already-shipped BLS non-transport counts: `count_agencies_by_county`
  counted one line per "City, ST ZIP" match, but a mailing-address line
  can incidentally match that same pattern (e.g. Jefferson County's
  "PO Box 2, **Brownville, NY 13615**" address line, immediately followed
  by that agency's real city line, "Dexter, NY 13634"), double-counting
  that one agency. Fixed by only counting a match when the *next* line
  does **not** also match — the true city line is always the last such
  match in a record — which corrected Jefferson's BLS
  `bls_nontransport_station_count` from 20 to 19 (statewide BLS total:
  728 → 727) in `data/processed/ny_ems_station_density_by_county.csv`. A
  blanket "reject lines containing PO Box" filter was tried first and
  rejected; it fixed Jefferson but incorrectly dropped a legitimate
  Orleans County record whose registered city field is literally "PO Box
  387, NY 14476" — a reminder that content-based filters are riskier than
  position/structure-based ones here.
