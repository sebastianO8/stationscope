# StationScope

**StationScope measures how far New Yorkers live from an ambulance.** Using
the standard research definition — a place is an *ambulance desert* if it is
more than 25 minutes' drive from the nearest ambulance station — it finds
that **between 310,062 and 546,536 New Yorkers live in an ambulance desert**,
or 1.5% to 2.7% of the state's population. The range is not uncertainty about
the arithmetic; it is the difference between two deliberately different
standards of evidence about where ambulance stations actually are, and the
gap between them is one of the findings. Both figures are *upper bounds*:
roughly a third of the state's ambulance agencies could not be placed on a
map at all, and every one of them, if located, could only shrink these
numbers.

The analysis is built on a foundation of county-level station density
metrics, which are also included here and which surfaced the data problems
that shaped the desert methodology.

---

## The headline result

| | Strict scenario | Full scenario |
|---|---|---|
| **People in ambulance deserts** | 546,536 | 310,062 |
| **Share of state population** | 2.71% | 1.53% |
| **Counties containing a desert** | 50 of 62 | 43 of 62 |
| **Ambulance stations used** | 495 | 690 |

Populations are 2020 Census block-group counts (20,201,249 statewide across
15,739 populated block groups).

### Why there are two scenarios

Every ambulance agency in New York is registered with the state, but the
registry lists **mailing addresses**, not station locations — and roughly 45%
of agencies (792 of 1,770) register a PO Box, which cannot be placed on a
map. Two different methods were used to recover locations, and they carry
genuinely different confidence:

- **`census_street`** — the agency's own registered street address, geocoded
  against the US Census Bureau's address database. The agency itself said
  where it is.
- **`hifld_station_name_match`** — the agency was matched *by name* to a
  fire/EMS station in a third-party national dataset, located in the same
  county and town. This is strong evidence about which organisation the
  station belongs to, but it is a different kind of fact: a third party's
  location for a same-named station, not something the agency reported.

Rather than pooling these and hiding the distinction, the analysis runs
twice. The **strict** scenario counts only agencies at their own registered
address (495 ambulance stations). The **full** scenario adds the
name-matched ones (690 stations).

**The 236,474-person gap between the two scenarios is the number of New
Yorkers whose ambulance coverage exists only if you accept the name-matching
as valid.** That is a substantive result, not a technical footnote: it
quantifies how much of the state's apparent ambulance coverage rests on
inference rather than on what agencies themselves reported. Counties where
the gap is widest — Lewis (63.4% desert under strict, 26.7% under full) and
Sullivan (31.5% → 19.2%) — are the places where the answer to "is this area
covered?" depends most on that judgement call.

### External validation

The Maine Rural Health Research Center's national chartbook, which
originated the 25-minute definition, reports **51 of New York's 62 counties**
containing an ambulance desert. This analysis, built independently from
different source data, finds **50 of 62** under the strict scenario — a close
agreement that provides external corroboration for the method.

### Geography

Deserts concentrate in the **Adirondacks and the North Country**, matching
the pattern the national research predicts for mountainous, sparsely
populated terrain. Ranked by share of population in a desert (full scenario):

| County | Full scenario | Strict scenario |
|---|---|---|
| Hamilton | 84.5% | 100.0% |
| Essex | 58.2% | 60.0% |
| Jefferson | 40.7% | 45.2% |
| Franklin | 28.1% | 29.5% |
| Lewis | 26.7% | 63.4% |
| Greene | 23.5% | 23.5% |

At the other end, dense suburban counties show no deserts at all:
Westchester is 0.0% under both scenarios.

Hamilton County — the state's least populous, at roughly 5,000 residents —
is the extreme case. All seven of its ambulance agencies register PO Boxes;
exactly one could be located, by name-match, and it is the sole reason
Hamilton is 84.5% rather than 100% desert under the full scenario.

---

## Limitations

**Every result here is an upper bound on ambulance deserts.** Each of the
following can only cause deserts to be *overstated*, never understated:

1. **353 of 1,043 ambulance agencies (34%) have no usable coordinate.** They
   are absent from both scenarios. If located, each would only shrink
   deserts. The full scenario uses 690 stations; the true number of
   ambulance stations in New York is 1,043.
2. **The missing agencies skew rural.** PO Box registration — the main reason
   an agency cannot be located — is far more common in rural counties: 61.0%
   of agencies in the 20 lowest-density counties versus 31.3% in the 20
   highest-density counties (correlation between county population density
   and PO Box rate: −0.46). Rural EMS is commonly run by small volunteer
   corps that register a PO Box; urban and hospital-based services more often
   register a street address. **The areas most likely to be genuine deserts
   are also the areas where coverage is most likely to be undercounted.**
3. **Drive times are conservative.** Routing uses OpenStreetMap road data via
   OSRM's default car profile. Spot-checks against a commercial routing
   service matched road *distances* essentially exactly but produced travel
   times 4–37% slower on rural secondary roads, pushing marginal areas over
   the 25-minute threshold rather than under it.
4. **Out-of-state stations are not included.** The New York registry contains
   only New York agencies, so a block group near the Pennsylvania, Vermont,
   New Jersey, Connecticut, or Massachusetts border may be served by a
   station just across the line that this analysis cannot see. Border-area
   deserts are overstated.
5. **Shelter Island is a desert by missing data, not by fact.** Four block
   groups (population 3,253) have no road route to any located station — the
   island is ferry-served, and its own EMS agency is one of the PO Box
   agencies that could not be placed. They are reported with no drive time
   rather than a fabricated one.

Two further caveats apply to the underlying registry rather than the routing:
the DOH registry counts *certified agencies*, which is not always the same as
staffed physical stations; and 38 of the name-matched locations had a
near-tied alternative candidate (typically "X Fire District" versus "X Fire
District: Station 2"), an ambiguity well below the resolution of a 25-minute
threshold but flagged per-row in the data.

---

## What counts as a station

Only **transporting ambulance/ALS agencies** count toward ending a desert —
1,043 of the 1,770 registered agencies. The remaining 727 are *BLS
non-transporting* agencies: they can dispatch a trained responder but cannot
carry a patient to a hospital. Under the research definition, an area served
only by a non-transporting agency is still an ambulance desert. Those 727
agencies are included in the county density metrics below but excluded from
the desert analysis.

---

## Method

**Demand points.** Drive times are measured to the
population-weighted centroid of every populated census block group in New
York (15,739 of them). Block groups are fine-grained enough to catch rural
pockets that a coarser unit such as a census tract would average away.

**Direction of travel.** Times are measured *from the station to the block
group* — the direction an ambulance actually travels — rather than the
reverse, which can differ on one-way road networks.

**Routing.** Real road-network routing (OSRM over an OpenStreetMap extract of
New York), not straight-line distance. The difference is substantial in
mountainous terrain: one verified Adirondack route is 21 km in a straight
line but 35 km and 34 minutes by road.

**Station locations.** Recovered in two tiers, as described above. Name
matching was restricted to candidates in the same county and the same town,
and accepted on the basis of organisational-identity evidence rather than a
string-similarity score. (Because the town was already a filter, similarity
scores were circular: two unrelated organisations in the same small town
score near-identically. The reasoning is documented in
[CLAUDE.md](CLAUDE.md).) Of 889 agencies the geocoder could not place, 432
were recovered this way, raising overall coverage from 881 to 1,313 of 1,770
agencies (49.8% → 74.2%).

**Validation.** The build asserts that the full scenario's drive time never
exceeds the strict scenario's for any block group — adding stations can only
shorten a drive — and reports any block group it cannot route rather than
silently dropping it.

---

## Data sources

| Source | Used for | Vintage | Retrieved |
|---|---|---|---|
| NY DOH Bureau of EMS agency registry (two statewide PDFs: ambulance/ALS, BLS non-transport) | Authoritative agency list, station counts, addresses | 2026-07-06 | 2026-08-03 |
| US Census Bureau geocoding service | Station coordinates from registered street addresses | — | 2026-08-05 |
| HIFLD Fire and EMS Stations (via Source Cooperative archive) | Station coordinates recovered by name-match | Jan 2025 | 2026-08-03 |
| US Census Bureau CenPop2020 block-group population-weighted centroids | Demand points and population for the desert analysis | 2020 Census | 2026-08-08 |
| Geofabrik OpenStreetMap New York extract (gitignored — re-download to rebuild) | Road network for drive-time routing | rolling OSM snapshot | 2026-08-08 |
| US Census Bureau county population estimates | Population for density metrics | Vintage 2025 | 2026-08-03 |
| US Census Bureau Gazetteer files | Land area for density metrics | 2025 | 2026-08-03 |
| US Census Bureau TIGER/Line county boundaries | Map geometry, county assignment | 2025 | 2026-08-03 |

Raw files live in `data/raw/` with source URLs; `scripts/` holds the
pipelines that turn them into `data/processed/`.

**Why the DOH registry is the primary source.** The original plan was to
build station counts from HIFLD's standalone "EMS Stations" layer, but that
dataset is no longer hosted anywhere — the HIFLD ArcGIS Online portal was
decommissioned around 2025-08-25. What remains available is a *combined*
"Fire and Emergency Medical Service Stations" layer that does not distinguish
ambulance stations from fire stations, making it unusable as a station count
or category source. New York's own DOH Bureau of EMS registry is the state's
authoritative list of certified agencies and is used for all counts and
categories. The HIFLD layer is used only as a coordinate source, joined by
name to registry agencies, and points derived from it are labelled as such
throughout.

**County assignment uses FIPS codes, not names.** County names format
inconsistently across sources ("St. Lawrence" versus "Saint Lawrence"), so
the 5-digit FIPS code is the join key. The join is validated on every run:
all 62 counties must match with no drops or duplicates, or the build fails
rather than writing a partial result. HIFLD stations, which carry no county
field, are assigned a county by point-in-polygon against the same boundaries.

---

## The county density metrics

These preceded the desert analysis and remain in the app as context. Two
measures, meant to be read together:

- **Stations per 10,000 residents** — coverage relative to population load
- **Stations per 100 square miles** — coverage relative to response distance

Statewide, using all 1,770 agencies: 0.88 stations per 10,000 residents and
3.76 per 100 square miles.

**These two measures can disagree sharply, which is the point.** The Bronx
has 8 stations for 1.41M residents — 0.057 per 10,000, the lowest rate in the
state — but packs them into 42 square miles, giving 18.96 per 100 square
miles, among the highest. Nassau shows the same inversion at a different
scale: 77 stations, 0.55 per 10,000 residents, 27.06 per 100 square miles.
Both counties look thinly covered by population and densely covered by
geography. Neither number alone would show it.

**Per-capita rates are unreliable in very small counties.** Hamilton County's
7 stations against roughly 5,000 residents produce 13.98 stations per 10,000
— about twice the next-highest county (Schuyler, 7.09) and five times the
statewide median (2.70). This is a small-denominator artifact, not evidence
that Hamilton is unusually well served. The desert analysis, which measures
actual drive times rather than ratios, finds Hamilton to be the most
underserved county in the state — the opposite conclusion, and the more
reliable one. This contrast is a large part of why the desert analysis
exists.

Density metrics are displayed with quantile (equal-count) classification
rather than a linear color scale, because both measures are strongly
right-skewed and a linear scale would collapse roughly 90% of counties into
the lightest shades.

---

## Running the app

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The app reads only precomputed files from `data/processed/`. Rebuilding the
desert analysis from raw data additionally requires a local OSRM routing
server; see `scripts/setup_osrm.sh`.

## Repository layout

```
data/raw/         source data as retrieved, with citations
data/processed/   cleaned, joined, and computed outputs consumed by the app
scripts/          data preparation pipelines (raw -> processed)
app/              Streamlit application
```

See [CLAUDE.md](CLAUDE.md) for project conventions and a running log of data
quirks, methodological decisions, and known limitations discovered during
development.
