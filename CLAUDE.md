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

- [2026-08-05] Geocoding the ~1,770 individual agency addresses (via the US
  Census Bureau's free batch geocoder, `scripts/geocode_agencies.py` ->
  `data/processed/ny_ems_agencies_geocoded.csv`) required first extracting a
  *street* address per agency, not just city/state/zip — the mailing-address
  row (the 2nd of each record's 3 wrapped lines) wasn't captured by the
  original agency extraction. It uses the same left-of-column boundary trick
  as `split_name_id` (same fixed column x-position, ~257pt ALS / ~267pt
  BLS), just without needing to isolate a trailing ID: whatever text sits
  left of that column on the address row is the street. One wrinkle:
  columns after the street aren't always in strict left-to-right stream
  order (the BLS PDF draws phone before ownership on this row for some
  records), but that doesn't matter — we only need to know where column 1
  *ends*, not what follows it.

  Match rate: 881/1,770 (49.8%) matched (772 exact, 109 non-exact), 10 ties,
  879 no-match. Of the 889 unmatched/tied, 791 (89%) are PO Box addresses —
  expected and not a geocoder failure, since a PO Box has no street-network
  entry to geocode against; ~45% of all registered agency addresses in this
  dataset are PO Boxes, so a ~50% overall match rate is close to the
  ceiling for street-only geocoding. The remaining 98 are genuine street
  addresses that still failed (non-standard formats like "One City Plaza"
  or "Floyd Bennett Field", abbreviation mismatches, rural routes) or tied
  on multiple equally-good candidates (e.g. "2502 Rt 52" — TIGER likely has
  more than one matching segment) — these are flagged per-row in the output
  CSV's `needs_manual_review` / `review_reason` columns rather than silently
  dropped. A PO-Box-aware fallback (e.g. geocoding to a city/zip centroid
  instead of a street point) would recover most of the remaining ~45% but
  was deliberately left out of this pass — it changes the precision
  semantics of the resulting points and deserves its own explicit decision
  rather than being bundled into "geocode the addresses."

- [2026-08-05] **The geocoded agency points are not a random sample of
  stations — they skew away from rural counties, which matters for any
  future coverage-desert analysis.** PO Box addresses (the dominant reason
  a record fails to geocode, see above) are not evenly distributed: in the
  20 lowest-population-density counties, 61.0% of agencies list a PO Box,
  versus 31.3% in the 20 highest-density counties (Pearson correlation
  between county population density and PO Box rate: -0.46). Hamilton
  County — already flagged above as a small-sample outlier — is 100% PO
  Box (7/7 agencies); Essex, Lewis, Franklin, and Delaware are all above
  65%. This tracks with how rural EMS is actually organized: small
  volunteer fire departments and ambulance corps commonly register a PO
  Box rather than a station street address, whereas urban/municipal
  services (city fire departments, hospital-based EMS) more often register
  a real street address.

  Net effect: a map or analysis built only from the successfully geocoded
  points (881/1,770, see above) will systematically under-represent rural
  counties' station counts more than urban ones — not because rural
  counties have fewer stations, but because a larger share of their real
  stations simply didn't produce a point. Any future "coverage desert"
  analysis built on the geocoded point layer needs to account for this
  skew explicitly (e.g. by working from the county-level DOH-registry
  counts already in `ny_ems_station_density_by_county.csv` for the
  *denominator*, rather than treating geocoded-point density as a proxy
  for station density) — otherwise rural counties would look artificially
  under-served on the point map even in counties where the registry-based
  per-capita/per-area metrics show adequate coverage.

- [2026-08-07] The app's county drill-down now plots geocoded agency pins
  (`render_county_map` in `app/streamlit_app.py`), which puts the rural
  geocoding skew above directly in front of users — so the pin layer is
  built to never let a missing point read as a missing station:
  * Every county view states "X of Y registered agencies shown as pins" in
    the caption **and** as an annotation baked into the map figure itself,
    so the caveat survives a screenshot or a glance at the map alone.
  * Counties where *nothing* geocoded get a centered on-map panel instead
    of an empty outline. This is not hypothetical: **Hamilton is 0 of 7**
    (100% PO Box), and Essex is 2 of 16 — without the panel, Hamilton
    renders as a blank county, the exact "looks like no coverage" failure.
  * The drill-down list below the map is still built from *all* agencies,
    mapped or not, so the address-only listing remains the complete record.
  Only `match_status == "Match"` rows are plotted (both Exact and
  Non_Exact/interpolated); Tie and No_Match have no usable coordinate.

  Two implementation notes worth keeping. (1) The county map is built with
  `graph_objects`, not `px.choropleth`, because px splits one frame into a
  trace per color class, which fights the "one county highlighted, rest
  muted" treatment. (2) The map has multiple clickable layers, so the click
  handler validates the clicked `customdata` against the real county list
  before treating it as a selection — otherwise clicking an agency pin
  feeds an *agency name* into the county selector. Both the pin-click guard
  and the "click a faded neighbour to jump counties" path were verified in
  the browser.

- [2026-08-08] **Similarity scoring was circular for the HIFLD name-match, so
  matches are tiered by evidence instead.** Recovering coordinates for the
  ~889 agencies the Census geocoder could not place
  (`scripts/match_hifld_agencies.py` -> `ny_ems_agencies_located.csv`) works
  by name-matching them to the HIFLD combined Fire/EMS layer, restricted to
  the same county (via point-in-polygon — HIFLD has no county field) and the
  same city. That city filter is exactly what makes a name-similarity
  threshold worthless here: once filler words (fire, department, volunteer,
  inc, ...) are stripped, most agency names reduce to just their town name,
  which the filter already guaranteed matches. "Delmar Volunteer Ambulance
  Service, Inc." vs "Delmar Fire District" scored **100/100** while carrying
  no evidence beyond "both are in Delmar" — 71% of the top-scoring band rested
  on a single shared token, and for 327 of those that token *was* the city.
  The score is also **inverted**: richer names have more tokens that must all
  agree, so a true match like "Findley Lake Volunteer Firemans Association" vs
  "Findlay Lake Volunteer Fire Department" scored only 75. Ranking by score
  therefore surfaces the *weakest* evidence first. If this is ever revisited,
  don't reach for a better string metric — the filter and the score are
  measuring the same thing.

  What was accepted instead, on what the evidence actually is:
  * **Tier A (429)** — the two names denote the same organisation: either both
    are fire bodies, or they share a distinctive token that isn't the city.
  * **Tier B corroborated (3)** — DOH lists an ambulance corps and HIFLD a fire
    station, but the HIFLD name *itself* names an ambulance/rescue service
    (e.g. "Long Lake Volunteer Fire Department **and Rescue Squad**").
  * **Rejected (376)** — 150 sharing only the town name across organisation
    types (asserting a specific building we have no evidence for), 223 below a
    similarity floor, 3 with a station/district number conflict (right
    organisation, wrong firehouse). A further 81 had no candidate at all.

  Coverage went 881 -> 1,313 of 1,770 (49.8% -> 74.2%). These points are a
  **different kind of fact** from Census ones and are stored and drawn as
  such: `coordinate_source` is `census_street` (the agency's own registered
  address, geocoded) or `hifld_station_name_match` (a third-party station
  matched by name). The app counts them separately in every disclosure and
  draws them hollow vs solid — never pooled into one "mapped" number.

  Two known imprecisions, both accepted deliberately and flagged per-row:
  * **38 matches have a near-tied runner-up** (`hifld_ambiguous_runner_up`) —
    typically "X Fire District" vs "X Fire District: Station 2" scoring
    identically, so which one is picked is arbitrary. The resulting offset is
    well below the resolution of a drive-time analysis, which is why they were
    kept rather than dropped.
  * **1 station receives 2 agencies** (`hifld_shared_station`): St. Regis Falls
    Ambulance and St. Regis Falls Fire Department both land on Saint Regis
    Falls Volunteer Fire Department. Note this was **17 stations / 35 agencies**
    when measured across Tier A *and* Tier B together — nearly every collision
    was a fire department and an ambulance corps landing on the same firehouse,
    so excluding Tier B removed 16 of them. Sharing a firehouse is often
    genuine, but a shared point is also how a wrong match would look, so they
    are flagged rather than deduped.

- [2026-08-09] **Ambulance-desert analysis** (`scripts/build_ambulance_deserts.py`
  -> `ambulance_deserts_by_block_group.csv`; MRHRC definition: >25 min drive,
  station -> block group, from the nearest *transporting* ambulance/ALS
  agency — BLS non-transport agencies deliberately excluded). Routing is
  OSRM on a Geofabrik NY extract, run locally in Docker
  (`scripts/setup_osrm.sh`; the pbf is filtered to `w/highway r/type=restriction`
  first, which is what keeps osrm-extract inside an 8 GB machine's Docker
  VM). Demand points are CenPop2020 population-weighted block-group
  centroids (15,739 populated). Results: strict scenario (495
  `census_street` stations only) 546,536 people in deserts (2.71% of NY);
  full scenario (+195 HIFLD-matched) 310,062 (1.53%); 50/62 counties
  contain a desert under strict vs 51/62 in MRHRC-derived published
  figures — a close external check. Hamilton verifies at 100%/84.5%,
  Westchester at 0%/0%. Lessons and quirks, in rough order of importance:

  * **A chunking bug survived the F⊆S invariant and was only caught by
    county-level verification.** Batching sliced a lat-band-sorted centroid
    list into consecutive runs; a run straddling one band's eastern end and
    the next band's western end got a midpoint hundreds of km from its
    extremes, and the nearest-to-midpoint candidate cap then starved
    edge centroids of their local stations (western Chautauqua was assigned
    Owego, Tioga County — 250+ km away — as "nearest", inflating the first
    run's statewide numbers by ~200k people). The full-vs-strict invariant
    was blind to it because both scenarios were starved identically. Fixed
    by chunking strictly within grid cells plus a runtime assert that a
    chunk spans ≤45 km. Moral: invariants that compare two outputs of the
    same code path do not check the code path; verify against known ground
    truth (Chautauqua has Jamestown and Dunkirk; 67.5% desert was absurd).
  * **OSRM's default car profile is conservative on rural roads.** Four
    spot-checks vs Google Maps matched road *distance* exactly (network and
    snapping are right) but ran +4% to +37% slower on time. Bias direction:
    more area classified desert. Consistent with the analysis being an
    upper bound, but do not compare our minutes to posted response-time
    standards without noting it.
  * **4 Shelter Island block groups (pop 3,253) are unroutable by
    construction**: ferry-only island, no located station on it — its own
    EMS agency is one of the PO-Box unlocated. They are classified desert
    with `drive_min` empty, and the app labels them "no road route" rather
    than a number. Fishers Island nearly hit the same fate but its fire
    district was HIFLD-matched onto the island, so within-island routing
    works (4.9 min under full; desert under strict).
  * Out-of-state stations are absent from the registry, so border block
    groups are overstated — annotated on the map, not corrected.
  * The desert figures inherit the rural PO-Box skew logged on 2026-08-05:
    353 unlocated ALS agencies can only *shrink* deserts if located. Both
    scenario figures are upper bounds; the strict-vs-full gap (236,474
    people) is the visible cost of not trusting the HIFLD name-match.
