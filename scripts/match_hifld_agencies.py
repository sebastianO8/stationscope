"""
Recover coordinates for DOH agencies the Census geocoder could not place, by
name-matching them against the HIFLD combined Fire/EMS station layer.

Inputs:
  - data/processed/ny_ems_agencies_geocoded.csv          (output of geocode_agencies.py)
  - data/raw/hifld_fire_ems_stations_2025-01_NY.geojson  (HIFLD combined Fire/EMS)
  - data/processed/ny_ems_station_density_by_county.geojson (county polygons)

Output:
  - data/processed/ny_ems_agencies_located.csv

This is a separate pipeline stage that *reads* the Census-geocoded file rather
than overwriting it: re-running `geocode_agencies.py` hits a slow external API
and would otherwise silently discard everything recovered here. The app reads
this file -- the final "located" table -- not the Census-only one.

WHY MATCHES ARE TIERED BY EVIDENCE, NOT BY SIMILARITY SCORE
-----------------------------------------------------------
Candidates are restricted to the same county and city before scoring, which
makes a raw name-similarity score circular: once filler words (fire,
department, volunteer, inc, ...) are stripped, most agency names reduce to
just their town name, which the city filter already guaranteed matches. So
"Delmar Volunteer Ambulance Service, Inc." vs "Delmar Fire District" scores
100/100 on name similarity while carrying no evidence beyond "both are in
Delmar." Worse, the score is *inverted*: organisations with richer names have
more tokens that must all agree, so a true match like "Findley Lake Volunteer
Firemans Association" vs "Findlay Lake Volunteer Fire Department" scores only
75. A score threshold therefore selects the weakest evidence first.

Matches are instead accepted on what the evidence actually is:
  TIER A  both names denote the same organisation -- either both are fire
          bodies, or they share a distinctive token that is not the city name.
  TIER B  the DOH agency is an independent ambulance/rescue corps and the
          HIFLD record is a fire station, sharing only the town name. Rejected,
          because it would assert a specific building we have no evidence for
          -- EXCEPT where the HIFLD station name itself names an ambulance or
          rescue service, which corroborates co-location.
Also rejected: station/district number conflicts (same org, wrong firehouse)
and any candidate below a name-similarity floor.

HIFLD carries no fire/EMS category field (every NY record is FCODE 74026 /
FTYPE 740), so the organisation-type signal has to come from the names.
"""

import csv
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

GEOCODED_CSV = PROCESSED / "ny_ems_agencies_geocoded.csv"
HIFLD_GEOJSON = RAW / "hifld_fire_ems_stations_2025-01_NY.geojson"
COUNTIES_GEOJSON = PROCESSED / "ny_ems_station_density_by_county.geojson"
OUTPUT_CSV = PROCESSED / "ny_ems_agencies_located.csv"

SOURCE_CENSUS = "census_street"
SOURCE_HIFLD = "hifld_station_name_match"

# Name-similarity floor. Not a confidence threshold -- just a guard against
# pairing two clearly unrelated organisations that happen to share a town.
CORE_FLOOR = 65
# A runner-up within this many points is treated as ambiguous. These are kept
# (the offset is far below the resolution of a drive-time analysis) but flagged.
RUNNER_UP_MARGIN = 3

CITY_STATE_ZIP_RE = re.compile(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})$")
FIRE_RE = re.compile(r"\bfire\b", re.IGNORECASE)
EMS_RE = re.compile(r"ambulance|rescue|\bems\b|emergency medical|medic|squad", re.IGNORECASE)
# Narrower than EMS_RE: used on the HIFLD side, where "squad"/"medic" alone are
# too loose to corroborate that a fire station also houses an ambulance.
HIFLD_EMS_RE = re.compile(r"ambulance|\bems\b|rescue|emergency medical", re.IGNORECASE)

# Words appearing in nearly every station name; they carry no discriminating
# signal, so they are excluded when deciding what evidence a match rests on.
GENERIC = {
    "fire", "department", "dept", "volunteer", "vol", "company", "co", "ems",
    "ambulance", "rescue", "squad", "district", "inc", "incorporated", "llc",
    "ltd", "corp", "corporation", "station", "service", "services", "emergency",
    "medical", "of", "the", "and", "town", "village", "city", "county",
    "association", "assoc", "no", "number", "engine", "hose", "chemical",
    "protective", "hook", "ladder", "first", "responders", "responder", "unit",
    "ny", "new", "york", "life", "support", "basic", "advanced", "joint", "area",
}
ABBREV = {
    "dept": "department", "vol": "volunteer", "fd": "fire department",
    "vfd": "volunteer fire department", "vfc": "volunteer fire company",
    "assoc": "association", "st": "saint", "mt": "mount", "ft": "fort",
    "co": "company", "twp": "township", "dist": "district",
}


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    expanded: list[str] = []
    for token in text.split():
        expanded.extend(ABBREV.get(token, token).split())
    return " ".join(expanded)


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t]


def distinctive(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in GENERIC and not t.isdigit()}


def digits(text: str) -> set[str]:
    return {t for t in tokens(text) if t.isdigit()}


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100


def token_sort_ratio(a: str, b: str) -> float:
    return ratio(" ".join(sorted(tokens(a))), " ".join(sorted(tokens(b))))


def core_similarity(a: str, b: str) -> float:
    """Similarity over distinctive tokens only, in both directions.

    Taking the minimum of the two directions stops a short name from scoring
    highly against a long one just by being a subset of it.
    """
    core_a, core_b = distinctive(a), distinctive(b)
    if not core_a or not core_b:
        return 0.0
    forward = sum(max(ratio(t, u) for u in core_b) for t in core_a) / len(core_a)
    reverse = sum(max(ratio(u, t) for t in core_a) for u in core_b) / len(core_b)
    return min(forward, reverse)


def load_hifld_with_county() -> list[dict]:
    """HIFLD stations, each assigned a county by point-in-polygon.

    HIFLD has no county field, so county comes from a spatial join against the
    same county polygons the app draws. The layers differ in CRS (HIFLD is
    EPSG:4326, TIGER is EPSG:4269); the datum shift is sub-meter in New York,
    far below county resolution, so the CRS is overridden rather than
    transformed (which would need PROJ data at runtime).
    """
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute(
        f"""
        SELECT h.NAME AS hifld_name, h.CITY AS hifld_city, c.county AS county,
               ST_X(h.geom) AS longitude, ST_Y(h.geom) AS latitude
        FROM ST_Read('{HIFLD_GEOJSON}') h
        LEFT JOIN ST_Read('{COUNTIES_GEOJSON}') c
          ON ST_Within(h.geom, ST_SetCRS(c.geom, 'EPSG:4326'))
        """
    ).fetchall()
    stations = [
        {
            "hifld_name": r[0] or "",
            "hifld_city": r[1] or "",
            "county": r[2],
            "longitude": r[3],
            "latitude": r[4],
        }
        for r in rows
    ]
    unassigned = sum(1 for s in stations if not s["county"])
    if unassigned:
        print(f"  note: {unassigned} HIFLD stations fell outside every NY county polygon")
    return stations


def best_candidate(agency: dict, city: str, candidates: list[dict]) -> dict | None:
    """Score candidates and return the best one with its supporting evidence."""
    name = agency["agency_name"]
    scored = []
    for station in candidates:
        core = core_similarity(name, station["hifld_name"])
        shared = distinctive(name) & distinctive(station["hifld_name"])
        city_tokens = set(re.split(r"[\s\-]+", city.lower()))
        agency_digits, station_digits = digits(name), digits(station["hifld_name"])
        scored.append(
            {
                "station": station,
                "core": core,
                "tsort": token_sort_ratio(name, station["hifld_name"]),
                "beyond_city": shared - city_tokens,
                "number_conflict": bool(
                    agency_digits and station_digits and agency_digits != station_digits
                ),
            }
        )
    if not scored:
        return None
    # Station name is the final tiebreak so repeated runs pick the same row.
    scored.sort(key=lambda s: (-s["core"], -s["tsort"], s["station"]["hifld_name"]))
    best = scored[0]
    best["ambiguous"] = (
        len(scored) > 1 and scored[1]["core"] >= best["core"] - RUNNER_UP_MARGIN
    )
    return best


def decide(agency: dict, best: dict) -> tuple[bool, str, str]:
    """(accept, tier, evidence) for a scored best candidate."""
    station_name = best["station"]["hifld_name"]
    if best["number_conflict"]:
        return False, "rejected_number_conflict", "station/district number differs"
    if best["core"] < CORE_FLOOR:
        return False, "rejected_low_similarity", "name similarity below floor"

    agency_is_fire = bool(FIRE_RE.search(agency["agency_name"]))
    station_is_fire = bool(FIRE_RE.search(station_name))
    if best["beyond_city"]:
        return True, "A_same_organisation", "shared distinctive name: " + ", ".join(
            sorted(best["beyond_city"])
        )
    if agency_is_fire and station_is_fire:
        return True, "A_same_organisation", "both named as the same fire body"
    if HIFLD_EMS_RE.search(station_name):
        return True, "B_corroborated", "HIFLD station name itself names an ambulance/rescue service"
    return False, "rejected_town_name_only", "shares only the town name, across organisation types"


def main() -> None:
    with open(GEOCODED_CSV, newline="") as f:
        agencies = list(csv.DictReader(f))
    print(f"Read {len(agencies)} agencies from {GEOCODED_CSV.name}")

    stations = load_hifld_with_county()
    print(f"Read {len(stations)} HIFLD stations")
    by_county_city: dict[tuple, list[dict]] = defaultdict(list)
    for station in stations:
        by_county_city[(station["county"], normalize(station["hifld_city"]))].append(station)

    tier_counts: dict[str, int] = defaultdict(int)
    ambiguous = 0
    claimed: dict[tuple, list[str]] = defaultdict(list)

    for agency in agencies:
        agency.update(
            coordinate_source=SOURCE_CENSUS if agency["match_status"] == "Match" else "",
            hifld_station_name="",
            hifld_match_tier="",
            hifld_match_evidence="",
            hifld_ambiguous_runner_up="",
        )
        if agency["match_status"] == "Match":
            tier_counts["census_street"] += 1
            continue

        match = CITY_STATE_ZIP_RE.match(agency["city"])
        city = match.group(1) if match else agency["city"]
        best = best_candidate(
            agency, city, by_county_city.get((agency["county"], normalize(city)), [])
        )
        if best is None:
            tier_counts["no_candidate"] += 1
            continue

        accept, tier, evidence = decide(agency, best)
        tier_counts[tier] += 1
        if not accept:
            continue

        station = best["station"]
        station_key = (station["hifld_name"], station["hifld_city"])
        agency.update(
            longitude=station["longitude"],
            latitude=station["latitude"],
            coordinate_source=SOURCE_HIFLD,
            hifld_station_name=station["hifld_name"],
            hifld_match_tier=tier,
            hifld_match_evidence=evidence,
            hifld_ambiguous_runner_up="TRUE" if best["ambiguous"] else "",
        )
        agency["_station_key"] = station_key
        ambiguous += int(best["ambiguous"])
        claimed[station_key].append(agency["agency_name"])

    # Several agencies can legitimately share one firehouse, but a shared point
    # is also how a wrong match shows up -- flag either way rather than dedupe.
    shared_stations = {k: v for k, v in claimed.items() if len(v) > 1}
    for agency in agencies:
        agency["hifld_shared_station"] = (
            "TRUE" if agency.pop("_station_key", None) in shared_stations else ""
        )

    fieldnames = [k for k in agencies[0].keys() if not k.startswith("_")]
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(agencies)

    recovered = tier_counts["A_same_organisation"] + tier_counts["B_corroborated"]
    total = len(agencies)
    census = tier_counts["census_street"]
    located = census + recovered

    print(f"\nWrote {total} rows to {OUTPUT_CSV}")
    print(f"  Census street matches (unchanged):        {census}")
    print(f"  Recovered from HIFLD:                     {recovered}")
    print(f"    tier A, same organisation:              {tier_counts['A_same_organisation']}")
    print(f"    tier B, corroborated by station name:   {tier_counts['B_corroborated']}")
    print(f"  Still unplaced:                           {total - located}")
    print(f"    rejected, town name only across orgs:   {tier_counts['rejected_town_name_only']}")
    print(f"    rejected, similarity below floor:       {tier_counts['rejected_low_similarity']}")
    print(f"    rejected, station number conflict:      {tier_counts['rejected_number_conflict']}")
    print(f"    no HIFLD station in same county+city:   {tier_counts['no_candidate']}")
    print(f"\n  Total located: {located}/{total} ({100 * located / total:.1f}%)")
    print(f"  Flagged ambiguous (near-tied runner-up):  {ambiguous}")
    print(f"  HIFLD stations receiving >1 agency:       {len(shared_stations)} "
          f"({sum(len(v) for v in shared_stations.values())} agencies)")


if __name__ == "__main__":
    main()
