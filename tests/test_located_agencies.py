"""Provenance invariants for the located-agencies file the app renders.

The two coordinate sources are different kinds of fact (own geocoded address
vs a third-party station matched by name) and the whole app is built on never
pooling them — so the file has to keep them cleanly separable.
"""

SOURCE_CENSUS = "census_street"
SOURCE_HIFLD = "hifld_station_name_match"
VALID_SOURCES = {SOURCE_CENSUS, SOURCE_HIFLD, ""}


def test_every_row_has_a_valid_coordinate_source(located_frame):
    source = located_frame["coordinate_source"].fillna("")
    invalid = set(source) - VALID_SOURCES
    assert not invalid, f"unknown coordinate_source values: {invalid}"


def test_documented_provenance_counts(located_frame):
    """881 census-geocoded + 432 HIFLD-recovered = 1,313 of 1,770 located."""
    source = located_frame["coordinate_source"].fillna("")
    assert len(located_frame) == 1_770
    assert (source == SOURCE_CENSUS).sum() == 881
    assert (source == SOURCE_HIFLD).sum() == 432
    assert (source == "").sum() == 457


def test_documented_hifld_tier_counts(located_frame):
    tiers = located_frame["hifld_match_tier"].fillna("")
    assert (tiers == "A_same_organisation").sum() == 429
    assert (tiers == "B_corroborated").sum() == 3


def test_located_rows_have_coordinates_and_unlocated_rows_do_not(located_frame):
    source = located_frame["coordinate_source"].fillna("")
    located = located_frame[source != ""]
    assert located["latitude"].notna().all()
    assert located["longitude"].notna().all()
    # Plausible NY-and-surroundings bounding box — catches lat/lon swaps.
    assert located["latitude"].between(40.0, 46.0).all()
    assert located["longitude"].between(-80.5, -71.0).all()
    unlocated = located_frame[source == ""]
    assert unlocated["latitude"].isna().all()
    assert unlocated["longitude"].isna().all()


def test_census_source_iff_census_match(located_frame):
    """census_street is exactly the set of rows the Census geocoder matched."""
    source = located_frame["coordinate_source"].fillna("")
    assert ((source == SOURCE_CENSUS) == (located_frame["match_status"] == "Match")).all()


def test_hifld_columns_only_on_hifld_rows(located_frame):
    source = located_frame["coordinate_source"].fillna("")
    hifld = located_frame[source == SOURCE_HIFLD]
    assert hifld["hifld_station_name"].notna().all()
    assert hifld["hifld_match_tier"].notna().all()
    assert hifld["hifld_match_evidence"].notna().all()
    others = located_frame[source != SOURCE_HIFLD]
    assert others["hifld_station_name"].isna().all()
    assert others["hifld_match_tier"].isna().all()


def test_documented_ambiguity_and_sharing_flags(located_frame):
    """38 near-tied runner-ups; exactly one station shared by two agencies."""
    ambiguous = located_frame["hifld_ambiguous_runner_up"]
    assert ambiguous.sum() == 38
    source = located_frame["coordinate_source"].fillna("")
    assert (source[ambiguous] == SOURCE_HIFLD).all()

    shared = located_frame[located_frame["hifld_shared_station"]]
    assert len(shared) == 2
    assert shared["hifld_station_name"].nunique() == 1
    assert set(shared["agency_name"]) == {
        "St. Regis Falls Ambulance, Inc.",
        "St. Regis Falls Fire Department, Inc.",
    }


def test_located_file_is_a_row_aligned_superset_of_agencies_file(
    located_frame, agencies_frame
):
    """The app loads only the located file and trusts it to be the agencies
    file plus extra columns — same rows, same order (see the comment above
    AGENCIES_CSV_PATH in app/streamlit_app.py)."""
    base_columns = ["county", "county_fips", "agency_type", "agency_name", "street", "city"]
    assert list(located_frame.columns[: len(base_columns)]) == base_columns
    left = located_frame[base_columns].fillna("").reset_index(drop=True)
    right = agencies_frame[base_columns].fillna("").reset_index(drop=True)
    assert left.equals(right)
