"""
Geocode individual EMS agency addresses using the US Census Bureau's free
batch geocoding API.

Input (data/processed/):
  - ny_ems_agencies.csv  (output of build_ems_station_density.py)

Output (data/processed/):
  - ny_ems_agencies_geocoded.csv

The Census batch geocoder (geocoding.geo.census.gov) matches a street
address to a point via TIGER/Line reference data. It cannot resolve PO Box
addresses to a point -- there is no street-network entry for a box number --
so a large, unavoidable share of "No_Match" results in this dataset are PO
Box addresses, not geocoder failures. These are flagged separately from
genuine unmatched street addresses in the manual-review report.

Run with:
    python scripts/geocode_agencies.py
"""

import csv
import io
import re
import sys
import time
from pathlib import Path

import requests

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"
INPUT_CSV = PROCESSED / "ny_ems_agencies.csv"
OUTPUT_CSV = PROCESSED / "ny_ems_agencies_geocoded.csv"

BATCH_ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
CHUNK_SIZE = 500
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 300  # seconds; a 500-address batch can take a couple of minutes

CITY_STATE_ZIP_RE = re.compile(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})$")
PO_BOX_RE = re.compile(r"^\s*P\.?\s*O\.?\s*Box\b", re.IGNORECASE)

GEOCODE_FIELDS = [
    "match_status",
    "match_type",
    "matched_address",
    "longitude",
    "latitude",
    "tiger_line_id",
    "side",
    "needs_manual_review",
    "review_reason",
]


def load_agencies() -> list[dict]:
    with open(INPUT_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows, start=1):
        match = CITY_STATE_ZIP_RE.match(row["city"])
        if not match:
            raise ValueError(f"Unparsable city field on row {i}: {row['city']!r}")
        row["_id"] = str(i)
        row["_city_name"], row["_state"], row["_zip"] = match.groups()
    return rows


def build_batch_csv(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    for row in rows:
        writer.writerow([row["_id"], row["street"], row["_city_name"], row["_state"], row["_zip"]])
    return buffer.getvalue().encode("utf-8")


def geocode_chunk(rows: list[dict], session: requests.Session) -> dict[str, dict]:
    batch_csv = build_batch_csv(rows)
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.post(
                BATCH_ENDPOINT,
                files={"addressFile": ("batch.csv", batch_csv, "text/csv")},
                data={"benchmark": BENCHMARK},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return parse_batch_response(response.text)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            wait = 5 * attempt
            print(
                f"  attempt {attempt}/{MAX_ATTEMPTS} failed ({exc}); retrying in {wait}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise RuntimeError(f"Batch geocode failed after {MAX_ATTEMPTS} attempts: {last_error}")


def parse_batch_response(text: str) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        record_id, _input_address, status = row[0], row[1], row[2]
        if status == "Match" and len(row) >= 8:
            longitude, latitude = row[5].split(",")
            results[record_id] = {
                "match_status": status,
                "match_type": row[3],
                "matched_address": row[4],
                "longitude": longitude,
                "latitude": latitude,
                "tiger_line_id": row[6],
                "side": row[7],
            }
        else:
            results[record_id] = {
                "match_status": status,
                "match_type": "",
                "matched_address": "",
                "longitude": "",
                "latitude": "",
                "tiger_line_id": "",
                "side": "",
            }
    return results


def review_reason(row: dict, geocode: dict) -> str:
    if geocode["match_status"] == "Match":
        return ""
    if PO_BOX_RE.match(row["street"]):
        return "PO Box address -- Census geocoder cannot resolve to a street point"
    if geocode["match_status"] == "Tie":
        return "Multiple equally-likely address matches -- needs manual disambiguation"
    return "No match found -- verify address manually"


def main() -> None:
    rows = load_agencies()
    total = len(rows)
    chunks = [rows[i : i + CHUNK_SIZE] for i in range(0, total, CHUNK_SIZE)]
    print(f"Geocoding {total} addresses in {len(chunks)} batch(es) of up to {CHUNK_SIZE}...")

    all_results: dict[str, dict] = {}
    with requests.Session() as session:
        for i, chunk in enumerate(chunks, start=1):
            print(f"  batch {i}/{len(chunks)} ({len(chunk)} addresses)...")
            all_results.update(geocode_chunk(chunk, session))
            if i < len(chunks):
                time.sleep(1)

    missing = [row["_id"] for row in rows if row["_id"] not in all_results]
    if missing:
        raise RuntimeError(f"{len(missing)} addresses got no response row at all: {missing[:10]}...")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    output_fields = ["county", "county_fips", "agency_type", "agency_name", "street", "city"] + GEOCODE_FIELDS
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        for row in rows:
            geocode = all_results[row["_id"]]
            needs_review = geocode["match_status"] != "Match"
            writer.writerow(
                {
                    "county": row["county"],
                    "county_fips": row["county_fips"],
                    "agency_type": row["agency_type"],
                    "agency_name": row["agency_name"],
                    "street": row["street"],
                    "city": row["city"],
                    **geocode,
                    "needs_manual_review": needs_review,
                    "review_reason": review_reason(row, geocode),
                }
            )

    matched = sum(1 for r in all_results.values() if r["match_status"] == "Match")
    exact = sum(1 for r in all_results.values() if r["match_type"] == "Exact")
    non_exact = sum(1 for r in all_results.values() if r["match_type"] == "Non_Exact")
    no_match = sum(1 for r in all_results.values() if r["match_status"] == "No_Match")
    tie = sum(1 for r in all_results.values() if r["match_status"] == "Tie")
    po_box_no_match = sum(
        1
        for row in rows
        if all_results[row["_id"]]["match_status"] != "Match" and PO_BOX_RE.match(row["street"])
    )
    street_no_match = no_match + tie - po_box_no_match

    print(f"\nWrote {total} rows to {OUTPUT_CSV}")
    print(f"Matched:      {matched}/{total} ({100 * matched / total:.1f}%)")
    print(f"  exact:      {exact}")
    print(f"  non-exact:  {non_exact}")
    print(f"No match:     {no_match}")
    print(f"Tie:          {tie}")
    print(
        f"\nOf {no_match + tie} unmatched/tied addresses, {po_box_no_match} are PO Box "
        f"addresses (expected -- Census geocoder needs a street address) and "
        f"{street_no_match} are street addresses that still failed to match "
        f"(flagged for manual review in the 'review_reason' column)."
    )


if __name__ == "__main__":
    main()
