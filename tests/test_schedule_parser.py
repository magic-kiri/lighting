import pytest
from app.stages.schedule_parser import parse_fixture_schedule

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_parse_amli_schedule():
    """AMLI BREA fixture schedule is on page 6 (index 5)."""
    result = parse_fixture_schedule(AMLI_PDF, page_indices=[5])
    assert result["success"] is True
    assert len(result["fixture_types"]) > 10
    type_codes = [ft["type_code"] for ft in result["fixture_types"]]
    assert "U1" in type_codes
    assert "B1" in type_codes


def test_parse_chase_schedule_rasterized():
    """Chase Bank schedule (page 103, index 102) is rasterized."""
    result = parse_fixture_schedule(CHASE_PDF, page_indices=[102])
    if not result["success"]:
        assert "rasterized" in result["error"].lower() or "no fixture types" in result["error"].lower()


def test_parse_returns_type_codes():
    result = parse_fixture_schedule(AMLI_PDF, page_indices=[5])
    for ft in result["fixture_types"]:
        assert "type_code" in ft
        assert isinstance(ft["type_code"], str)
        assert len(ft["type_code"]) > 0
