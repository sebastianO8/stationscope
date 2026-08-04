"""
Build county-level EMS station density metrics for New York State.

Inputs (data/raw/):
  - ny_doh_ems_agencies_ambulance_als_2026-07-06.pdf   (NY DOH Bureau of EMS)
  - ny_doh_ems_agencies_bls_nontransport_2026-07-06.pdf (NY DOH Bureau of EMS)
  - census_ny_county_population_2025.csv                (US Census Vintage 2025 population estimates)
  - census_ny_county_land_area_2025.txt                 (US Census 2025 Gazetteer, land area sq mi)

Output (data/processed/):
  - ny_ems_station_density_by_county.csv

Note: this computes station *counts* per county from the DOH agency registry.
It does not yet include station coordinates for map display -- that requires
a separate join against a geocoded source (see data/raw/hifld_fire_ems_stations_2025-01_NY.geojson)
and is deliberately left as a follow-up step.
"""

import csv
import re
from collections import OrderedDict
from pathlib import Path

import pdfplumber

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"

DOH_PDFS = {
    "ambulance_als": RAW / "ny_doh_ems_agencies_ambulance_als_2026-07-06.pdf",
    "bls_nontransport": RAW / "ny_doh_ems_agencies_bls_nontransport_2026-07-06.pdf",
}
POPULATION_CSV = RAW / "census_ny_county_population_2025.csv"
LAND_AREA_TXT = RAW / "census_ny_county_land_area_2025.txt"
OUTPUT_CSV = PROCESSED / "ny_ems_station_density_by_county.csv"

COUNTY_HEADER_RE = re.compile(r"\s*County of ([A-Za-z .'-]+?)\s*$")
OUT_OF_STATE_RE = re.compile(r"\s*Out Of State\s*$")
AGENCY_RECORD_RE = re.compile(r",\s*[A-Z]{2}\s+\d{5}")


def count_agencies_by_county(pdf_path: Path) -> "OrderedDict[str, int]":
    """Count DOH-listed EMS agencies per county.

    The DOH PDFs group agencies under repeating "County of X" headers, with
    each agency spanning several lines of a mailing-address-style layout.
    Rather than parsing every field (fragile given the overlapping-column
    text layout), we count one agency per "City, ST ZIP" line -- this line
    appears exactly once per agency record and survives page breaks cleanly,
    since a county's header is not repeated until a new county begins.
    """
    county_counts: "OrderedDict[str, int]" = OrderedDict()
    current_county = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            for line in text.split("\n"):
                county_match = COUNTY_HEADER_RE.match(line)
                if county_match:
                    current_county = county_match.group(1).strip()
                    county_counts.setdefault(current_county, 0)
                    continue
                if OUT_OF_STATE_RE.match(line):
                    current_county = "Out Of State"
                    county_counts.setdefault(current_county, 0)
                    continue
                if current_county and AGENCY_RECORD_RE.search(line):
                    county_counts[current_county] += 1

    return county_counts


def load_population() -> dict[str, int]:
    with open(POPULATION_CSV, encoding="latin1") as f:
        reader = csv.DictReader(f)
        return {
            row["CTYNAME"]: int(row["POPESTIMATE2025"])
            for row in reader
            if row["SUMLEV"] == "050"
        }


def load_land_area() -> dict[str, float]:
    with open(LAND_AREA_TXT, encoding="latin1") as f:
        reader = csv.DictReader(f, delimiter="|")
        return {row["NAME"]: float(row["ALAND_SQMI"]) for row in reader}


def main() -> None:
    ambulance_als_counts = count_agencies_by_county(DOH_PDFS["ambulance_als"])
    bls_counts = count_agencies_by_county(DOH_PDFS["bls_nontransport"])
    population = load_population()
    land_area = load_land_area()

    all_counties = sorted(
        (set(ambulance_als_counts) | set(bls_counts)) - {"Out Of State"}
    )

    PROCESSED.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "county",
                "ambulance_als_station_count",
                "bls_nontransport_station_count",
                "total_station_count",
                "population_2025",
                "land_area_sq_mi",
                "stations_per_10k_residents",
                "stations_per_100_sq_mi",
            ]
        )
        for county in all_counties:
            census_name = f"{county} County"
            pop = population.get(census_name)
            area = land_area.get(census_name)
            ambulance_als = ambulance_als_counts.get(county, 0)
            bls = bls_counts.get(county, 0)
            total = ambulance_als + bls

            if pop is None or area is None:
                raise ValueError(f"No Census match for DOH county name: {county!r}")

            per_capita = total / (pop / 10_000)
            per_area = total / (area / 100)

            writer.writerow(
                [
                    county,
                    ambulance_als,
                    bls,
                    total,
                    pop,
                    round(area, 3),
                    round(per_capita, 3),
                    round(per_area, 3),
                ]
            )

    print(f"Wrote {len(all_counties)} counties to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
