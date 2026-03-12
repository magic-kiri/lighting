import pytest
from app.stages.llm_counter import count_fixtures_with_llm, _parse_count_response

CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_llm_count_chase_page_113():
    fixture_types = ["D1A", "D1B", "D2", "L1A", "L2A", "L5", "X1", "EM"]
    counts = count_fixtures_with_llm(CHASE_PDF, page_index=112, fixture_types=fixture_types)
    assert isinstance(counts, dict)
    assert sum(counts.values()) > 0


def test_parse_count_response_valid_json():
    """Test parsing of well-formed LLM response."""
    response = '{"counts": {"D1A": 37, "L1A": 32}}'
    valid_types = ["D1A", "L1A", "X1"]
    result = _parse_count_response(response, valid_types)
    assert result == {"D1A": 37, "L1A": 32}


def test_parse_count_response_with_code_fence():
    """Test parsing with markdown code fence."""
    response = '```json\n{"counts": {"D1A": 10}}\n```'
    valid_types = ["D1A"]
    result = _parse_count_response(response, valid_types)
    assert result == {"D1A": 10}


def test_parse_count_response_filters_unknown_types():
    """Only return counts for valid fixture types."""
    response = '{"counts": {"D1A": 5, "UNKNOWN": 3}}'
    valid_types = ["D1A", "L1A"]
    result = _parse_count_response(response, valid_types)
    assert result == {"D1A": 5}
    assert "UNKNOWN" not in result
