import pytest
from app.stages.counter import count_fixtures_on_page

CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_count_fixtures_chase_page_113():
    """Page 113 (index 112) is E-212 Electrical Lighting Plan - Level 02."""
    fixture_types = ["D1A", "D1B", "D2", "L1A", "L2A", "L2B", "L5", "L6", "L-8", "L-22", "X1", "EM"]
    counts = count_fixtures_on_page(CHASE_PDF, page_index=112, fixture_types=fixture_types)
    assert isinstance(counts, dict)
    assert sum(counts.values()) > 0
    if "D1A" in counts:
        assert counts["D1A"] > 0


def test_count_returns_only_known_types():
    fixture_types = ["D1A"]
    counts = count_fixtures_on_page(CHASE_PDF, page_index=112, fixture_types=["D1A"])
    assert all(k in ["D1A"] for k in counts.keys())
