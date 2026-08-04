"""
Join county-level EMS station density metrics to county boundary geometry,
for map display.

Inputs:
  - data/raw/tiger_county_boundaries_2025_NY/tiger_county_boundaries_2025_NY.shp
    (Census TIGER/Line 2025 county boundaries, filtered to NY)
  - data/processed/ny_ems_station_density_by_county.csv
    (output of build_ems_station_density.py)

Output:
  - data/processed/ny_ems_station_density_by_county.geojson

Join key: 5-digit county FIPS code (TIGER's GEOID <-> our county_fips column),
not county name -- names in the two sources don't always format identically
(e.g. "St. Lawrence" vs "Saint Lawrence"), so FIPS is the reliable key.

Before writing output, this script asserts all 62 NY counties matched with
no drops or duplicates on either side; it raises rather than silently
writing a partial or duplicated result.
"""

from pathlib import Path

import duckdb

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"

BOUNDARIES_SHP = (
    RAW / "tiger_county_boundaries_2025_NY" / "tiger_county_boundaries_2025_NY.shp"
)
DENSITY_CSV = PROCESSED / "ny_ems_station_density_by_county.csv"
OUTPUT_GEOJSON = PROCESSED / "ny_ems_station_density_by_county.geojson"

EXPECTED_COUNTY_COUNT = 62


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    con.execute(f"CREATE TABLE boundaries AS SELECT * FROM ST_Read('{BOUNDARIES_SHP}')")
    con.execute(f"CREATE TABLE density AS SELECT * FROM read_csv_auto('{DENSITY_CSV}')")

    n_boundaries = con.execute("SELECT COUNT(*) FROM boundaries").fetchone()[0]
    n_density = con.execute("SELECT COUNT(*) FROM density").fetchone()[0]
    dup_boundaries = con.execute(
        "SELECT GEOID FROM boundaries GROUP BY GEOID HAVING COUNT(*) > 1"
    ).fetchall()
    dup_density = con.execute(
        "SELECT county_fips FROM density GROUP BY county_fips HAVING COUNT(*) > 1"
    ).fetchall()

    if n_boundaries != EXPECTED_COUNTY_COUNT:
        raise ValueError(f"Expected {EXPECTED_COUNTY_COUNT} boundary rows, got {n_boundaries}")
    if n_density != EXPECTED_COUNTY_COUNT:
        raise ValueError(f"Expected {EXPECTED_COUNTY_COUNT} density rows, got {n_density}")
    if dup_boundaries:
        raise ValueError(f"Duplicate GEOID in boundaries: {dup_boundaries}")
    if dup_density:
        raise ValueError(f"Duplicate county_fips in density: {dup_density}")

    unmatched = con.execute(
        """
        SELECT COALESCE(b.GEOID, CAST(d.county_fips AS VARCHAR)) AS fips,
               b.GEOID IS NULL AS missing_in_boundaries,
               d.county_fips IS NULL AS missing_in_density
        FROM boundaries b
        FULL OUTER JOIN density d
          ON b.GEOID = LPAD(CAST(d.county_fips AS VARCHAR), 5, '0')
        WHERE b.GEOID IS NULL OR d.county_fips IS NULL
        """
    ).fetchall()
    if unmatched:
        raise ValueError(f"Unmatched counties after FIPS join: {unmatched}")

    matched_count = con.execute(
        """
        SELECT COUNT(*)
        FROM boundaries b
        JOIN density d
          ON b.GEOID = LPAD(CAST(d.county_fips AS VARCHAR), 5, '0')
        """
    ).fetchone()[0]
    if matched_count != EXPECTED_COUNTY_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_COUNTY_COUNT} matched rows, got {matched_count}"
        )

    con.execute(
        f"""
        COPY (
            SELECT
                d.* EXCLUDE (county_fips),
                b.GEOID AS county_fips,
                b.geom AS geometry
            FROM boundaries b
            JOIN density d
              ON b.GEOID = LPAD(CAST(d.county_fips AS VARCHAR), 5, '0')
        ) TO '{OUTPUT_GEOJSON}' WITH (FORMAT GDAL, DRIVER 'GeoJSON')
        """
    )

    print(f"Join key: county FIPS code (TIGER GEOID <-> density.county_fips)")
    print(f"Matched: {matched_count}/{EXPECTED_COUNTY_COUNT} counties, no drops, no duplicates")
    print(f"Wrote {OUTPUT_GEOJSON}")


if __name__ == "__main__":
    main()
