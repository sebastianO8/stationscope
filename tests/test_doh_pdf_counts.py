"""DOH registry parsing: agency counts vs the documents' own subtotals.

The ambulance/ALS PDF prints a per-county "Level of Care Totals" block (level
labels, then per-level counts); the county's agency total is their sum. That
gives an exhaustive, document-internal ground truth for all 63 sections
(62 counties + Out Of State) — the strongest check available, since it comes
from the publisher, not from our own parsing.

The BLS non-transport PDF has NO built-in subtotal (CLAUDE.md, 2026-08-03),
so it is checked against the five hand-verified county counts plus Jefferson
(whose off-by-one was found and fixed on 2026-08-04), and for consistency
with the committed county CSV.

These tests re-parse the PDFs page by page — marked `pdf`, minutes not
seconds. Deselect with `-m "not pdf"` for a quick run.
"""

import re

import pdfplumber
import pytest

import build_ems_station_density as besd
from conftest import ALS_PDF, BLS_PDF

pytestmark = pytest.mark.pdf

SUBTOTAL_MARKER = "Level of Care Totals"
NUMBERS_LINE_RE = re.compile(r"^\s*\d[\d\s]*$")


def parse_document_subtotals(pdf_path) -> dict[str, int]:
    """Per-county totals as printed by the document itself.

    Each county section ends with a "Level of Care Totals:" block: a labels
    line (AEMT / EMT / EMT-P / ...) followed by a line of per-level counts.
    The county's agency total is the sum of those counts.
    """
    subtotals: dict[str, int] = {}
    current_county = None
    pending_subtotal = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            for line in text.split("\n"):
                county_match = besd.COUNTY_HEADER_RE.match(line)
                if county_match:
                    current_county = county_match.group(1).strip()
                    continue
                if besd.OUT_OF_STATE_RE.match(line):
                    current_county = "Out Of State"
                    continue
                if SUBTOTAL_MARKER in line:
                    pending_subtotal = True
                    continue
                if pending_subtotal and NUMBERS_LINE_RE.match(line):
                    assert current_county is not None
                    assert current_county not in subtotals, (
                        f"second subtotal block for {current_county}"
                    )
                    subtotals[current_county] = sum(int(n) for n in line.split())
                    pending_subtotal = False
    return subtotals


@pytest.fixture(scope="module")
def als_parsed_counts():
    return besd.count_agencies_by_county(ALS_PDF)


@pytest.fixture(scope="module")
def bls_parsed_counts():
    return besd.count_agencies_by_county(BLS_PDF)


def test_als_counts_match_the_documents_own_subtotals(als_parsed_counts):
    """All 63 sections: parsed count == the PDF's printed subtotal."""
    subtotals = parse_document_subtotals(ALS_PDF)
    assert set(subtotals) == set(als_parsed_counts), (
        f"section sets differ: only-in-subtotals="
        f"{set(subtotals) - set(als_parsed_counts)}, "
        f"only-in-parsed={set(als_parsed_counts) - set(subtotals)}"
    )
    assert len(subtotals) == 63  # 62 counties + Out Of State
    mismatches = {
        county: (als_parsed_counts[county], subtotals[county])
        for county in subtotals
        if als_parsed_counts[county] != subtotals[county]
    }
    assert not mismatches, f"(parsed, document) mismatches: {mismatches}"


def test_als_counts_match_the_committed_csv(als_parsed_counts, density_frame):
    committed = dict(
        zip(density_frame["county"], density_frame["ambulance_als_station_count"])
    )
    parsed = {c: n for c, n in als_parsed_counts.items() if c != "Out Of State"}
    assert parsed == committed


def test_bls_counts_match_the_committed_csv(bls_parsed_counts, density_frame):
    committed = dict(
        zip(density_frame["county"], density_frame["bls_nontransport_station_count"])
    )
    parsed = {c: n for c, n in bls_parsed_counts.items() if c != "Out Of State"}
    # Counties absent from the BLS PDF have zero BLS agencies.
    for county in committed:
        assert committed[county] == parsed.get(county, 0), county


def test_bls_hand_verified_counties(bls_parsed_counts):
    """The five counties counted line-by-line by hand (CLAUDE.md, 2026-08-03),
    plus Jefferson, whose PO-Box double-count fix pinned it at 19."""
    expected = {
        "Onondaga": 45,
        "Rensselaer": 28,
        "Cortland": 10,
        "Schoharie": 4,
        "Kings": 1,
        "Jefferson": 19,
    }
    actual = {county: bls_parsed_counts.get(county, 0) for county in expected}
    assert actual == expected
