"""County join invariants: exactly 62 NY counties, no drops, no duplicates.

Locks in the guarantee scripts/join_county_density_boundaries.py asserts at
build time — here re-verified on the committed outputs, so a hand-edited or
partially rewritten processed file fails even without rerunning the build.
"""

import math

EXPECTED_COUNTY_COUNT = 62
NY_STATE_FIPS = "36"


def test_density_csv_has_exactly_62_counties(density_frame):
    assert len(density_frame) == EXPECTED_COUNTY_COUNT


def test_density_csv_county_fips_unique_and_in_ny(density_frame):
    fips = density_frame["county_fips"]
    assert fips.is_unique
    assert (fips.str.len() == 5).all()
    assert fips.str.startswith(NY_STATE_FIPS).all()


def test_density_csv_county_names_unique(density_frame):
    assert density_frame["county"].is_unique


def test_geojson_features_match_density_csv_exactly(county_geojson, density_frame):
    """The map file and the metrics file describe the same 62 counties."""
    feature_fips = [
        feature["properties"]["county_fips"] for feature in county_geojson["features"]
    ]
    assert len(feature_fips) == EXPECTED_COUNTY_COUNT
    assert len(set(feature_fips)) == EXPECTED_COUNTY_COUNT, "duplicate county geometry"
    assert set(feature_fips) == set(density_frame["county_fips"]), (
        "geojson and density CSV cover different county sets"
    )


def test_geojson_properties_carry_the_density_metrics(county_geojson):
    required = {
        "county",
        "county_fips",
        "total_station_count",
        "population_2025",
        "land_area_sq_mi",
        "stations_per_10k_residents",
        "stations_per_100_sq_mi",
    }
    for feature in county_geojson["features"]:
        missing = required - set(feature["properties"])
        assert not missing, f"feature missing properties: {missing}"


def test_station_counts_are_internally_consistent(density_frame):
    assert (
        density_frame["total_station_count"]
        == density_frame["ambulance_als_station_count"]
        + density_frame["bls_nontransport_station_count"]
    ).all()


def test_density_metrics_recompute_from_their_inputs(density_frame):
    """The two headline metrics are pure arithmetic on count/pop/area."""
    for _, row in density_frame.iterrows():
        per_capita = row["total_station_count"] / (row["population_2025"] / 10_000)
        per_area = row["total_station_count"] / (row["land_area_sq_mi"] / 100)
        assert math.isclose(row["stations_per_10k_residents"], per_capita, abs_tol=5e-3), row["county"]
        assert math.isclose(row["stations_per_100_sq_mi"], per_area, abs_tol=5e-3), row["county"]


def test_every_agency_county_exists_in_the_density_table(agencies_frame, density_frame):
    """No agency is attributed to a county the join doesn't know about."""
    assert set(agencies_frame["county_fips"]) <= set(density_frame["county_fips"])


def test_per_county_agency_rows_match_density_counts(agencies_frame, density_frame):
    """The agency-level file and the county-level counts tell one story."""
    per_county = (
        agencies_frame.groupby(["county_fips", "agency_type"]).size().unstack(fill_value=0)
    )
    merged = density_frame.set_index("county_fips").join(per_county)
    assert (
        merged["ambulance_als_station_count"] == merged["ambulance_als"]
    ).all(), "ALS agency rows disagree with county counts"
    assert (
        merged["bls_nontransport_station_count"] == merged["bls_nontransport"].fillna(0)
    ).all(), "BLS agency rows disagree with county counts"
