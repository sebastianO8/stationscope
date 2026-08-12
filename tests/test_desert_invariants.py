"""Ambulance-desert invariants, verified on the committed block-group file.

GOLDEN VALUES: the headline figures asserted here (546,536 / 310,062 desert
population, 50 counties, Hamilton 100%/84.5%, the 495+195 station split, the
4 Shelter Island block groups) are pinned to the current analysis run — the
2026-08-09 build documented in CLAUDE.md. A failure means one of two things:
a regression that silently changed the output, or a legitimate re-analysis
(new registry vintage, relocated stations, different OSRM extract) that
genuinely moved the numbers. Investigate which before updating the values —
never re-pin to whatever the new output says just to make the suite green.

NOT TESTABLE WITHOUT LIVE ROUTING (reported, not mocked):
  * The drive times themselves — every drive_min_* value came from a local
    OSRM server over the Geofabrik NY extract. Without that server we can
    check the *relationships* between the numbers (F ⊆ S, threshold/flag
    agreement, class consistency) but not the numbers.
  * The radius-ladder candidate search and MAX_SOURCES cap in
    candidates_for() — their effect only materialises in OSRM table calls.
  * The runtime chunk-spread assert *firing during a build* — the chunk
    geometry it guards is re-checked statically in test_chunking.py, but the
    assert's placement in the live loop can only be exercised by a build.
  * The documented OSRM-vs-Google conservative time bias (+4–37%%) — an
    external-service comparison by nature. (The "+4-37% slower" figure is
    documented in CLAUDE.md, 2026-08-09.)
"""

DESERT_THRESHOLD_MIN = 25.0
# drive_min_* is written rounded to 0.1 min, but the desert flags were
# computed from unrounded seconds — a 25.04-minute drive is stored as "25.0"
# yet correctly flagged as desert. Flag/threshold agreement is therefore
# asserted with a half-rounding-step tolerance.
ROUNDING_SLACK = 0.05


def test_full_desert_set_is_subset_of_strict(deserts_frame):
    """F ⊆ S: adding HIFLD-matched stations can only ever shrink deserts."""
    violation = deserts_frame["desert_full"] & ~deserts_frame["desert_strict"]
    assert not violation.any(), (
        f"{violation.sum()} block groups are desert under full but not strict: "
        f"{deserts_frame.loc[violation, 'geoid'].head().tolist()}"
    )


def test_full_drive_time_never_exceeds_strict(deserts_frame):
    """Full's station set is a superset of strict's, so its drive can't be longer.

    No tolerance needed: both columns are rounded by the same monotonic
    formatting, so full_sec <= strict_sec survives rounding.
    """
    both = deserts_frame.dropna(subset=["drive_min_strict", "drive_min_full"])
    bad = both[both["drive_min_full"] > both["drive_min_strict"]]
    assert bad.empty, (
        f"{len(bad)} block groups have full > strict drive time: "
        f"{bad['geoid'].head().tolist()}"
    )


def test_full_unroutable_implies_strict_unroutable(deserts_frame):
    """A block group unroutable under full must also be unroutable under strict."""
    bad = deserts_frame[
        deserts_frame["drive_min_full"].isna() & deserts_frame["drive_min_strict"].notna()
    ]
    assert bad.empty


def test_desert_flags_agree_with_threshold(deserts_frame):
    for scenario in ("strict", "full"):
        flag = deserts_frame[f"desert_{scenario}"]
        # Flagged desert: no route at all, or over the threshold (within rounding).
        flagged = deserts_frame[flag]
        bad = flagged[
            flagged[f"drive_min_{scenario}"].notna()
            & (flagged[f"drive_min_{scenario}"] < DESERT_THRESHOLD_MIN - ROUNDING_SLACK)
        ]
        assert bad.empty, f"{scenario}: flagged desert but well under 25 min"
        # Not flagged: must have a route at or under the threshold.
        unflagged = deserts_frame[~flag]
        assert unflagged[f"drive_min_{scenario}"].notna().all(), (
            f"{scenario}: unroutable block group not flagged as desert"
        )
        bad = unflagged[
            unflagged[f"drive_min_{scenario}"] > DESERT_THRESHOLD_MIN + ROUNDING_SLACK
        ]
        assert bad.empty, f"{scenario}: over 25 min but not flagged"


def test_desert_class_is_derived_from_the_two_flags(deserts_frame):
    expected = deserts_frame.apply(
        lambda r: "desert_both"
        if r["desert_full"]
        else ("desert_strict_only" if r["desert_strict"] else "covered"),
        axis=1,
    )
    assert (deserts_frame["desert_class"] == expected).all()


def test_block_group_universe(deserts_frame):
    """15,739 populated block groups, unique 12-digit GEOIDs, all in NY."""
    assert len(deserts_frame) == 15_739
    assert deserts_frame["geoid"].is_unique
    assert (deserts_frame["geoid"].str.len() == 12).all()
    assert (deserts_frame["geoid"].str[:2] == "36").all()
    assert (deserts_frame["county_fips"] == deserts_frame["geoid"].str[:5]).all()
    assert (deserts_frame["population"] > 0).all()


def test_headline_desert_figures_match_the_documented_run(deserts_frame):
    """The numbers CLAUDE.md and the README are built on."""
    strict_pop = int(deserts_frame.loc[deserts_frame["desert_strict"], "population"].sum())
    full_pop = int(deserts_frame.loc[deserts_frame["desert_full"], "population"].sum())
    assert strict_pop == 546_536
    assert full_pop == 310_062
    assert strict_pop - full_pop == 236_474  # the strict-vs-full provenance gap
    n_strict_counties = deserts_frame.loc[
        deserts_frame["desert_strict"], "county"
    ].nunique()
    assert n_strict_counties == 50


def test_unroutable_block_groups_are_exactly_shelter_island(deserts_frame):
    """4 ferry-only block groups (pop 3,253), desert by construction, in Suffolk."""
    unroutable = deserts_frame[deserts_frame["drive_min_full"].isna()]
    assert len(unroutable) == 4
    assert int(unroutable["population"].sum()) == 3_253
    assert (unroutable["county"] == "Suffolk").all()
    assert unroutable["desert_strict"].all() and unroutable["desert_full"].all()


def test_known_county_extremes(deserts_frame):
    """Hamilton is 100% desert strict / 84.5% full; Westchester has none."""
    hamilton = deserts_frame[deserts_frame["county"] == "Hamilton"]
    ham_pop = hamilton["population"].sum()
    assert hamilton["desert_strict"].all()
    full_share = hamilton.loc[hamilton["desert_full"], "population"].sum() / ham_pop
    assert abs(full_share - 0.845) < 0.001
    westchester = deserts_frame[deserts_frame["county"] == "Westchester"]
    assert not westchester["desert_strict"].any()
    assert not westchester["desert_full"].any()


def test_desert_station_universe_matches_located_file(located_frame):
    """The documented 495 strict + 195 HIFLD ALS stations feed the analysis."""
    als = located_frame[located_frame["agency_type"] == "ambulance_als"]
    strict = (als["coordinate_source"] == "census_street").sum()
    hifld = (als["coordinate_source"] == "hifld_station_name_match").sum()
    assert strict == 495
    assert hifld == 195
    # 353 in-state ALS agencies have no coordinate — the documented reason
    # every desert figure is an upper bound.
    in_state = als[als["county"] != "Out Of State"]
    unlocated = (
        ~in_state["coordinate_source"].isin(
            ["census_street", "hifld_station_name_match"]
        )
    ).sum()
    assert unlocated == 353
