"""
Build county-level EMS station density metrics for New York State.

Inputs (data/raw/):
  - ny_doh_ems_agencies_ambulance_als_2026-07-06.pdf   (NY DOH Bureau of EMS)
  - ny_doh_ems_agencies_bls_nontransport_2026-07-06.pdf (NY DOH Bureau of EMS)
  - census_ny_county_population_2025.csv                (US Census Vintage 2025 population estimates)
  - census_ny_county_land_area_2025.txt                 (US Census 2025 Gazetteer, land area sq mi)

Output (data/processed/):
  - ny_ems_station_density_by_county.csv  (per-county counts + density metrics)
  - ny_ems_agencies.csv                   (individual agencies, name + city + type)

Note: this computes station *counts and individual agency records* from the
DOH agency registry. It does not yet include geocoded station coordinates for
map-marker display -- that requires a separate join against a geocoded source
(see data/raw/hifld_fire_ems_stations_2025-01_NY.geojson) and is deliberately
left as a follow-up step.
"""

import csv
import re
from collections import OrderedDict, defaultdict
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
AGENCIES_CSV = PROCESSED / "ny_ems_agencies.csv"

COUNTY_HEADER_RE = re.compile(r"\s*County of ([A-Za-z .'-]+?)\s*$")
OUT_OF_STATE_RE = re.compile(r"\s*Out Of State\s*$")
AGENCY_RECORD_RE = re.compile(r",\s*[A-Z]{2}\s+\d{5}")

# Each agency record's "City, ST ZIP" line is the LAST of its (typically
# three) wrapped lines. A mailing-address line ("PO Box 2, Brownville, NY
# 13615") can incidentally also match AGENCY_RECORD_RE, which would
# double-count that agency if taken at face value -- so a match is only
# counted when the immediately following line does NOT also match; two
# matches in a row means the earlier one was an address, not the closing
# city line.
FOOTER_MARKER = "NYS-EMS"
SERVICE_ID_X_TOLERANCE = 3


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
            lines = text.split("\n")
            for i, line in enumerate(lines):
                county_match = COUNTY_HEADER_RE.match(line)
                if county_match:
                    current_county = county_match.group(1).strip()
                    county_counts.setdefault(current_county, 0)
                    continue
                if OUT_OF_STATE_RE.match(line):
                    current_county = "Out Of State"
                    county_counts.setdefault(current_county, 0)
                    continue
                if not (current_county and AGENCY_RECORD_RE.search(line)):
                    continue
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                if AGENCY_RECORD_RE.search(next_line):
                    continue  # this match is an address line, not the closing city line
                county_counts[current_county] += 1

    return county_counts


def group_rows_global(page: "pdfplumber.page.Page", grid: float = 1.0) -> list[tuple[float, list]]:
    """Cluster a page's characters into visual rows by y-position ('top').

    A row's characters are not always contiguous in `page.chars`' stream
    order -- other rows' characters can be interspersed between a row's left
    and far-right columns -- so rows are found with a single global pass over
    every character on the page, bucketed by rounded `top`, rather than by
    "start a new row when `top` changes" over a stream-ordered walk (which
    silently drops content). Each bucket keeps its characters in their
    original stream order, which -- for a single row -- reconstructs the
    logical left-to-right field order (name, then service ID, then license
    type, then phone) even where two fields' x-ranges visually overlap.
    """
    buckets: dict[int, list] = defaultdict(list)
    for char in page.chars:
        buckets[round(char["top"] / grid)].append(char)
    rows = sorted(buckets.items(), key=lambda item: item[0])

    merged: list[tuple[float, list]] = []
    for _, chars in rows:
        top = chars[0]["top"]
        if merged and abs(merged[-1][0] - top) < grid:
            merged[-1] = (merged[-1][0], merged[-1][1] + chars)
        else:
            merged.append((top, chars))
    return merged


def find_service_id_column_start(pdf: "pdfplumber.PDF") -> float:
    """Find the x-position of the "Service ID" column header.

    Computed per-PDF rather than hardcoded -- the ambulance/ALS and BLS
    files' column positions differ by several points.
    """
    words = pdf.pages[0].extract_words()
    for i, word in enumerate(words):
        if word["text"] == "Service" and i + 1 < len(words) and words[i + 1]["text"] == "ID":
            return word["x0"]
    raise ValueError("Could not locate the 'Service ID' column header")


def split_name_id(chars: list, id_column_x: float) -> tuple[str | None, str | None]:
    """Split a record's name row into (agency_name, service_id).

    The 4-digit Service ID is drawn at a fixed column x-position regardless
    of name length. When a name is long enough to reach that x-position,
    naive text extraction (which sorts characters by x-position to
    reconstruct reading order) interleaves the ID's digits into the middle
    of the name character-by-character -- e.g. "Rocky Mtn Holdings LLC" with
    ID 0767 flattens to "Rocky Mtn 0H7o6l7dings LLC". No regex over that
    flattened text can undo the interleaving.

    The fix: `chars` is in original stream order (see `group_rows_global`),
    which keeps the full name intact ahead of the ID's digits regardless of
    x-overlap. So the split just needs to find where the ID starts: the
    first digit character whose x0 lands within tolerance of the known
    Service ID column. Anchoring on column position (not "the last digit run
    in the text") is what correctly leaves digits that are part of the name
    itself alone -- e.g. "Clarence Fire District #1" (id column tolerance
    ~257 +/- 3pt) vs. that agency's real ID "1444" starting exactly at 257.1.
    """
    for i, char in enumerate(chars):
        if char["text"].isdigit() and abs(char["x0"] - id_column_x) <= SERVICE_ID_X_TOLERANCE:
            j = i
            while j < len(chars) and chars[j]["text"].isdigit():
                j += 1
            name = "".join(c["text"] for c in chars[:i]).strip()
            agency_id = "".join(c["text"] for c in chars[i:j])
            if name:
                return name, agency_id
    return None, None


def extract_agency_records(pdf_path: Path) -> list[dict]:
    """Extract individual agency records (county, name, city) from a DOH PDF.

    Walks every row on every page in order, using the row's reconstructed
    text for county attribution (`COUNTY_HEADER_RE`) and record boundaries
    (`AGENCY_RECORD_RE`, unchanged from `count_agencies_by_county`), and the
    row's characters for name/ID splitting (`split_name_id`). A record's
    city is taken from the LAST `AGENCY_RECORD_RE`-matching row seen before
    the next name row starts -- the same "true city line is the last match"
    rule used to fix the Jefferson County BLS miscount in
    `count_agencies_by_county`, applied here as well.
    """
    records: list[dict] = []
    current_county = None
    pending: dict | None = None

    def finalize() -> None:
        nonlocal pending
        if pending is not None and pending["city"] is not None:
            records.append(
                {
                    "county": pending["county"],
                    "agency_name": pending["name"],
                    "city": pending["city"],
                }
            )
        pending = None

    with pdfplumber.open(pdf_path) as pdf:
        id_column_x = find_service_id_column_start(pdf)
        for page in pdf.pages:
            for _, chars in group_rows_global(page):
                text = "".join(c["text"] for c in chars)
                if text.startswith(FOOTER_MARKER):
                    continue

                county_match = COUNTY_HEADER_RE.match(text)
                if county_match:
                    finalize()
                    current_county = county_match.group(1).strip()
                    continue
                if OUT_OF_STATE_RE.match(text):
                    finalize()
                    current_county = "Out Of State"
                    continue

                name, _agency_id = split_name_id(chars, id_column_x)
                if name is not None:
                    finalize()
                    pending = {"county": current_county, "name": name, "city": None}
                    continue

                if pending is not None:
                    city_match = re.match(r"^(.*?,\s*[A-Z]{2}\s+\d{5})", text)
                    if city_match:
                        pending["city"] = city_match.group(1).strip()
        finalize()

    return records


def validate_agency_counts(
    records: list[dict], trusted_counts: "OrderedDict[str, int]", pdf_label: str
) -> None:
    """Assert per-county agency-record counts match the trusted count.

    `trusted_counts` comes from `count_agencies_by_county`, an independent
    parse of the same PDF using different logic (line-based counting vs.
    character-level name extraction here). Agreement between the two is the
    correctness check for both; raises with a per-county diff rather than
    silently writing a partial or corrupted result.
    """
    extracted_counts: dict[str, int] = defaultdict(int)
    for record in records:
        extracted_counts[record["county"]] += 1

    mismatches = [
        (county, trusted_counts.get(county, 0), extracted_counts.get(county, 0))
        for county in set(trusted_counts) | set(extracted_counts)
        if trusted_counts.get(county, 0) != extracted_counts.get(county, 0)
    ]
    if mismatches:
        detail = ", ".join(f"{c}: trusted={t} extracted={e}" for c, t, e in sorted(mismatches))
        raise ValueError(f"Agency-count mismatch in {pdf_label}: {detail}")


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


def load_fips() -> dict[str, str]:
    with open(LAND_AREA_TXT, encoding="latin1") as f:
        reader = csv.DictReader(f, delimiter="|")
        return {row["NAME"]: row["GEOID"] for row in reader}


def main() -> None:
    ambulance_als_counts = count_agencies_by_county(DOH_PDFS["ambulance_als"])
    bls_counts = count_agencies_by_county(DOH_PDFS["bls_nontransport"])
    population = load_population()
    land_area = load_land_area()
    fips = load_fips()

    all_counties = sorted(
        (set(ambulance_als_counts) | set(bls_counts)) - {"Out Of State"}
    )

    PROCESSED.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "county",
                "county_fips",
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
            county_fips = fips.get(census_name)
            ambulance_als = ambulance_als_counts.get(county, 0)
            bls = bls_counts.get(county, 0)
            total = ambulance_als + bls

            if pop is None or area is None or county_fips is None:
                raise ValueError(f"No Census match for DOH county name: {county!r}")

            per_capita = total / (pop / 10_000)
            per_area = total / (area / 100)

            writer.writerow(
                [
                    county,
                    county_fips,
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

    agency_records = []
    for agency_type, trusted_counts in [
        ("ambulance_als", ambulance_als_counts),
        ("bls_nontransport", bls_counts),
    ]:
        records = extract_agency_records(DOH_PDFS[agency_type])
        validate_agency_counts(records, trusted_counts, agency_type)
        for record in records:
            agency_records.append({**record, "agency_type": agency_type})

    with open(AGENCIES_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["county", "county_fips", "agency_type", "agency_name", "city"])
        for record in agency_records:
            if record["county"] == "Out Of State":
                continue
            county_fips = fips.get(f"{record['county']} County")
            if county_fips is None:
                raise ValueError(f"No Census match for DOH county name: {record['county']!r}")
            writer.writerow(
                [record["county"], county_fips, record["agency_type"], record["agency_name"], record["city"]]
            )

    print(f"Wrote {len(agency_records)} agency records to {AGENCIES_CSV}")


if __name__ == "__main__":
    main()
