"""Shared fixtures for the StationScope data-pipeline test suite.

The suite runs entirely against the committed files in data/ plus the
importable parser functions in scripts/ — no Docker, no OSRM server, no
network. Invariants that genuinely require live routing are listed in
tests/test_desert_invariants.py's module docstring rather than mocked.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

# scripts/ is not a package; make its modules importable by module name.
sys.path.insert(0, str(ROOT / "scripts"))

DENSITY_CSV = PROCESSED / "ny_ems_station_density_by_county.csv"
DENSITY_GEOJSON = PROCESSED / "ny_ems_station_density_by_county.geojson"
AGENCIES_CSV = PROCESSED / "ny_ems_agencies.csv"
LOCATED_CSV = PROCESSED / "ny_ems_agencies_located.csv"
DESERTS_CSV = PROCESSED / "ambulance_deserts_by_block_group.csv"
ALS_PDF = RAW / "ny_doh_ems_agencies_ambulance_als_2026-07-06.pdf"
BLS_PDF = RAW / "ny_doh_ems_agencies_bls_nontransport_2026-07-06.pdf"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pdf: slow tests that re-parse the DOH PDFs page by page "
        "(minutes, not seconds); deselect with -m 'not pdf'",
    )


@pytest.fixture(scope="session")
def density_frame() -> pd.DataFrame:
    return pd.read_csv(DENSITY_CSV, dtype={"county_fips": str})


@pytest.fixture(scope="session")
def agencies_frame() -> pd.DataFrame:
    return pd.read_csv(AGENCIES_CSV, dtype={"county_fips": str})


@pytest.fixture(scope="session")
def located_frame() -> pd.DataFrame:
    frame = pd.read_csv(LOCATED_CSV, dtype={"county_fips": str})
    # The flag columns hold "TRUE" or empty; pandas reads them as True/NaN.
    # Normalize to plain booleans.
    for col in ("hifld_ambiguous_runner_up", "hifld_shared_station"):
        frame[col] = frame[col].notna()
    return frame


@pytest.fixture(scope="session")
def deserts_frame() -> pd.DataFrame:
    return pd.read_csv(DESERTS_CSV, dtype={"geoid": str, "county_fips": str})


@pytest.fixture(scope="session")
def county_geojson() -> dict:
    import json

    with open(DENSITY_GEOJSON) as f:
        return json.load(f)
