"""
Ambulance-desert analysis: drive time from the nearest ambulance station to
every populated census block group in New York State.

Definition (Maine Rural Health Research Center): a populated place is an
ambulance desert when it is more than 25 minutes' drive from the nearest
ambulance station. Drive time is measured station -> block group (the
direction an ambulance actually travels), on the real road network via a
local OSRM server -- never straight-line distance.

Inputs:
  - data/processed/ny_ems_agencies_located.csv   (stations; ALS only, see below)
  - data/raw/census_cenpop2020_bg_centroids_NY.txt
        (2020 Census population-weighted block-group centroids, CenPop2020)
  - a running OSRM server (see scripts/setup_osrm.sh), expected on
    http://127.0.0.1:5001

Output:
  - data/processed/ambulance_deserts_by_block_group.csv

Station set: agency_type == ambulance_als ONLY. BLS non-transporting
agencies cannot transport a patient, so under the research definition they
do not end an ambulance desert.

Two scenarios, run in one pass:
  strict -- census_street points only: the agency's own registered street
            address, geocoded. Most defensible, fewest stations.
  full   -- strict + hifld_station_name_match points: adds stations located
            via name-matching against the HIFLD layer (see CLAUDE.md).
Both scenarios OVERSTATE deserts -- 353 in-state ALS agencies have no
coordinate at all (PO Boxes, skewing rural) -- so every desert figure is an
upper bound. The strict-vs-full difference band shows exactly how much of
the map's "coverage" depends on trusting the HIFLD name-match.

Invariant checked before writing: full's station set is a superset of
strict's, so full's drive time can never exceed strict's for any block
group. A violation means a bug (bad chunking, swapped axes), not data.
"""

import csv
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

STATIONS_CSV = PROCESSED / "ny_ems_agencies_located.csv"
CENTROIDS_TXT = RAW / "census_cenpop2020_bg_centroids_NY.txt"
DENSITY_CSV = PROCESSED / "ny_ems_station_density_by_county.csv"
OUTPUT_CSV = PROCESSED / "ambulance_deserts_by_block_group.csv"

OSRM_URL = "http://127.0.0.1:5001"
DESERT_THRESHOLD_MIN = 25.0

SOURCE_CENSUS = "census_street"
SOURCE_HIFLD = "hifld_station_name_match"

# Candidate-station search radii, widened until at least one candidate is
# found. 70 km straight-line comfortably exceeds any 25-minute drive; the
# wider rungs only matter for scenario `strict` in station-poor regions
# (e.g. the Adirondacks), where the nearest census-located station can be
# far away but a finite time is still needed to report.
RADIUS_LADDER_KM = (70, 150, 300, None)  # None = all stations
DEST_CHUNK = 100
MAX_SOURCES = 250  # nearest-N cap; only ever binds in the NYC metro


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def load_stations() -> list[dict]:
    with open(STATIONS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    stations = [
        {
            "name": r["agency_name"],
            "county": r["county"],
            "source": r["coordinate_source"],
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
        }
        for r in rows
        if r["agency_type"] == "ambulance_als"
        and r["coordinate_source"] in (SOURCE_CENSUS, SOURCE_HIFLD)
    ]
    return stations


def load_centroids() -> list[dict]:
    with open(CENTROIDS_TXT, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    centroids = []
    for r in rows:
        pop = int(r["POPULATION"])
        if pop <= 0:
            continue
        centroids.append(
            {
                "geoid": r["STATEFP"] + r["COUNTYFP"] + r["TRACTCE"] + r["BLKGRPCE"],
                "county_fips": r["STATEFP"] + r["COUNTYFP"],
                "population": pop,
                "lat": float(r["LATITUDE"]),
                "lon": float(r["LONGITUDE"]),
            }
        )
    return centroids


def load_county_names() -> dict[str, str]:
    with open(DENSITY_CSV, newline="") as f:
        return {r["county_fips"]: r["county"] for r in csv.DictReader(f)}


def check_server() -> None:
    try:
        r = requests.get(
            f"{OSRM_URL}/route/v1/driving/-73.76,42.65;-73.77,42.66", timeout=10
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(
            f"OSRM server not reachable at {OSRM_URL} ({exc}).\n"
            "Run scripts/setup_osrm.sh once, then start the server with the\n"
            "docker run command in that script's header."
        )


def candidates_for(chunk: list[dict], stations: list[dict]) -> list[int]:
    """Station indices near a chunk of centroids, via the radius ladder.

    Distances are measured from the chunk's midpoint with the chunk's own
    radius added, so every centroid in the chunk is covered by the search.
    """
    mid_lat = sum(c["lat"] for c in chunk) / len(chunk)
    mid_lon = sum(c["lon"] for c in chunk) / len(chunk)
    spread = max(haversine_km(mid_lat, mid_lon, c["lat"], c["lon"]) for c in chunk)
    dists = [
        (haversine_km(mid_lat, mid_lon, s["lat"], s["lon"]), i)
        for i, s in enumerate(stations)
    ]
    for radius in RADIUS_LADDER_KM:
        if radius is None:
            hits = sorted(dists)
        else:
            hits = sorted(d for d in dists if d[0] <= radius + spread)
        if hits:
            return [i for _, i in hits[:MAX_SOURCES]]
    return []


def osrm_table(sources: list[dict], destinations: list[dict]) -> list[list]:
    """durations[source][destination] in seconds (None where unroutable)."""
    coords = ";".join(
        f"{p['lon']:.6f},{p['lat']:.6f}" for p in list(sources) + list(destinations)
    )
    n_src = len(sources)
    params = {
        "sources": ";".join(str(i) for i in range(n_src)),
        "destinations": ";".join(str(n_src + i) for i in range(len(destinations))),
        "annotations": "duration",
    }
    for attempt in range(3):
        try:
            r = requests.get(
                f"{OSRM_URL}/table/v1/driving/{coords}", params=params, timeout=120
            )
            r.raise_for_status()
            body = r.json()
            if body.get("code") != "Ok":
                raise requests.RequestException(body.get("code"))
            return body["durations"]
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            print(f"  retrying table call ({exc})...", file=sys.stderr)
            time.sleep(3)
    raise AssertionError("unreachable")


def main() -> None:
    check_server()
    stations = load_stations()
    centroids = load_centroids()
    county_names = load_county_names()
    n_strict = sum(1 for s in stations if s["source"] == SOURCE_CENSUS)
    print(
        f"{len(stations)} located ALS stations "
        f"({n_strict} census_street, {len(stations) - n_strict} hifld_matched); "
        f"{len(centroids)} populated block groups"
    )

    # Spatially coherent chunks: group by grid cell FIRST, then split each
    # cell into chunks. Never slice a globally-sorted list into consecutive
    # runs -- a run can straddle the jump from one latitude band's eastern
    # end to the next band's western end, giving the chunk a midpoint
    # hundreds of km from its extremes; the nearest-to-midpoint candidate
    # cap then starves the extremes of their local stations. (Found the
    # hard way: western Chautauqua was assigned Owego, Tioga County, as its
    # "nearest" station.)
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for c in centroids:
        cells[(round(c["lat"] / 0.25), round(c["lon"] / 0.25))].append(c)
    chunks = [
        cell[i : i + DEST_CHUNK]
        for _, cell in sorted(cells.items())
        for i in range(0, len(cell), DEST_CHUNK)
    ]

    unroutable: list[str] = []
    for n_chunk, chunk in enumerate(chunks, 1):
        spread = max(
            haversine_km(chunk[0]["lat"], chunk[0]["lon"], c["lat"], c["lon"])
            for c in chunk
        )
        # A chunk wider than its grid cell's diagonal means the grouping
        # above regressed to straddling -- fail loudly, don't compute junk.
        assert spread <= 45, f"chunk {n_chunk} spans {spread:.0f} km; chunking bug"
        cand_idx = candidates_for(chunk, stations)
        cand = [stations[i] for i in cand_idx]
        durations = osrm_table(cand, chunk)
        for d_i, centroid in enumerate(chunk):
            best = {SOURCE_CENSUS: (math.inf, None), "any": (math.inf, None)}
            for s_i, station in enumerate(cand):
                sec = durations[s_i][d_i]
                if sec is None:
                    continue
                if station["source"] == SOURCE_CENSUS and sec < best[SOURCE_CENSUS][0]:
                    best[SOURCE_CENSUS] = (sec, station)
                if sec < best["any"][0]:
                    best["any"] = (sec, station)
            centroid["strict_sec"], centroid["strict_station"] = best[SOURCE_CENSUS]
            centroid["full_sec"], centroid["full_station"] = best["any"]
            if math.isinf(centroid["full_sec"]):
                unroutable.append(centroid["geoid"])
        if n_chunk % 20 == 0 or n_chunk == len(chunks):
            print(f"  chunk {n_chunk}/{len(chunks)}")

    # Invariant: adding stations can only ever shorten the drive.
    violations = [
        c["geoid"]
        for c in centroids
        if c["full_sec"] > c["strict_sec"] + 1e-6
    ]
    if violations:
        raise AssertionError(
            f"{len(violations)} block groups have full > strict drive time "
            f"(first: {violations[:5]}) -- chunking/axis bug, not data."
        )

    PROCESSED.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "geoid", "county_fips", "county", "population",
                "latitude", "longitude",
                "drive_min_strict", "drive_min_full",
                "nearest_station_strict", "nearest_station_full",
                "desert_strict", "desert_full", "desert_class",
            ]
        )
        for c in centroids:
            strict_min = c["strict_sec"] / 60 if math.isfinite(c["strict_sec"]) else None
            full_min = c["full_sec"] / 60 if math.isfinite(c["full_sec"]) else None
            desert_strict = strict_min is None or strict_min > DESERT_THRESHOLD_MIN
            desert_full = full_min is None or full_min > DESERT_THRESHOLD_MIN
            desert_class = (
                "desert_both" if desert_full
                else "desert_strict_only" if desert_strict
                else "covered"
            )
            writer.writerow(
                [
                    c["geoid"], c["county_fips"],
                    county_names.get(c["county_fips"], ""), c["population"],
                    f"{c['lat']:.6f}", f"{c['lon']:.6f}",
                    f"{strict_min:.1f}" if strict_min is not None else "",
                    f"{full_min:.1f}" if full_min is not None else "",
                    c["strict_station"]["name"] if c["strict_station"] else "",
                    c["full_station"]["name"] if c["full_station"] else "",
                    desert_strict, desert_full, desert_class,
                ]
            )

    total_pop = sum(c["population"] for c in centroids)
    pop_strict = sum(
        c["population"] for c in centroids
        if math.isinf(c["strict_sec"]) or c["strict_sec"] / 60 > DESERT_THRESHOLD_MIN
    )
    pop_full = sum(
        c["population"] for c in centroids
        if math.isinf(c["full_sec"]) or c["full_sec"] / 60 > DESERT_THRESHOLD_MIN
    )
    print(f"\nWrote {len(centroids)} block groups to {OUTPUT_CSV}")
    print(f"  Desert population, strict (census-located stations only): "
          f"{pop_strict:,} ({100 * pop_strict / total_pop:.2f}% of NY)")
    print(f"  Desert population, full (+ HIFLD-matched stations):       "
          f"{pop_full:,} ({100 * pop_full / total_pop:.2f}% of NY)")
    print(f"  Gap attributable to HIFLD-matched stations:               "
          f"{pop_strict - pop_full:,}")
    print(f"  Unroutable block groups: {len(unroutable)}"
          + (f" -- {unroutable[:10]}" if unroutable else ""))
    print("\nBoth figures are UPPER BOUNDS: 353 in-state ALS agencies have no"
          "\ncoordinate (PO Boxes, skewing rural), and out-of-state stations near"
          "\nthe border are not in the registry at all.")


if __name__ == "__main__":
    main()
