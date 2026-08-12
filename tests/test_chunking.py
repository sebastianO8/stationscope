"""The chunk-spread guard that caught the lat-band straddling bug.

Background (CLAUDE.md, 2026-08-09): slicing a globally-sorted centroid list
into consecutive runs produced a chunk straddling one latitude band's eastern
end and the next band's western end. Its midpoint sat hundreds of km from its
extremes, so the nearest-to-midpoint candidate cap starved edge centroids of
their local stations (western Chautauqua was assigned a "nearest" station
250+ km away in Tioga County). The fix chunks strictly within 0.25-degree
grid cells and asserts at runtime that no chunk spans more than 45 km.

This test re-runs that geometry check statically: it rebuilds the chunks from
the same raw centroid file, with the same grid construction and the module's
own DEST_CHUNK and haversine_km, and asserts the <=45 km bound holds for every
chunk — no OSRM server involved, because the bound is a property of the
chunking alone, not of routing.

The three-line grid construction is duplicated from build_ambulance_deserts
.main() because the chunking is inline there rather than a named function,
and this suite must not modify scripts/. If the grid cell size (0.25 deg) or
chunk construction in main() changes, update the copy here to match.
"""

from collections import defaultdict

import build_ambulance_deserts as bad

GRID_DEG = 0.25  # keep in sync with the cell rounding in main()
MAX_CHUNK_SPAN_KM = 45  # keep in sync with the runtime assert in main()


def build_chunks(centroids: list[dict]) -> list[list[dict]]:
    """Verbatim reconstruction of main()'s grid-cell chunking."""
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for c in centroids:
        cells[(round(c["lat"] / GRID_DEG), round(c["lon"] / GRID_DEG))].append(c)
    return [
        cell[i : i + bad.DEST_CHUNK]
        for _, cell in sorted(cells.items())
        for i in range(0, len(cell), bad.DEST_CHUNK)
    ]


def test_no_chunk_spans_more_than_45_km():
    centroids = bad.load_centroids()
    assert centroids, "no populated centroids loaded"
    chunks = build_chunks(centroids)

    # Same spread measure as the runtime assert: max distance from the
    # chunk's first centroid to any other member.
    worst = 0.0
    for chunk in chunks:
        spread = max(
            bad.haversine_km(chunk[0]["lat"], chunk[0]["lon"], c["lat"], c["lon"])
            for c in chunk
        )
        worst = max(worst, spread)
        assert spread <= MAX_CHUNK_SPAN_KM, (
            f"chunk starting at geoid {chunk[0]['geoid']} spans {spread:.0f} km; "
            "grid chunking has regressed to straddling"
        )
    # The bound should not merely hold — a 0.25-degree cell's diagonal is
    # ~34 km at NY latitudes, so anything approaching 45 km means the cell
    # construction itself changed.
    assert worst <= 40, f"worst chunk spread {worst:.1f} km is suspiciously wide"


def test_chunks_partition_the_centroids_exactly():
    """Every populated centroid lands in exactly one chunk, none duplicated."""
    centroids = bad.load_centroids()
    chunks = build_chunks(centroids)
    assert all(len(chunk) <= bad.DEST_CHUNK for chunk in chunks)
    chunked_geoids = [c["geoid"] for chunk in chunks for c in chunk]
    assert len(chunked_geoids) == len(centroids)
    assert len(set(chunked_geoids)) == len(chunked_geoids)


def test_centroid_universe_matches_the_desert_output(deserts_frame):
    """The raw centroid file and the committed desert CSV cover the same
    block groups — a drifted raw file would silently invalidate the output."""
    centroids = bad.load_centroids()
    assert {c["geoid"] for c in centroids} == set(deserts_frame["geoid"])
