import json
import pytest
from unittest.mock import patch
from app.stages.schedule_parser import parse_fixture_schedule, extract_fixture_types_llm

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


class TestExtractFixtureTypesLLM:
    """Tests for the LLM-based fixture type extraction."""

    def test_extracts_types_from_schedule_text(self):
        """Given schedule text, LLM should return fixture type codes."""
        mock_response = json.dumps({
            "fixture_types": ["D1A", "D1B", "D2", "DF1", "L-22", "X1"]
        })
        schedule_text = "TYPE  DESCRIPTION\nD1A   6\" Downlight\nD1B   4\" Downlight"

        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            types = extract_fixture_types_llm(schedule_text)
            assert types == ["D1A", "D1B", "D2", "DF1", "L-22", "X1"]

    def test_handles_markdown_wrapped_json(self):
        """LLM sometimes wraps JSON in markdown code blocks."""
        mock_response = '```json\n{"fixture_types": ["AL1", "BH1", "SS9"]}\n```'
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            types = extract_fixture_types_llm("schedule text")
            assert types == ["AL1", "BH1", "SS9"]

    def test_handles_empty_response(self):
        """Empty or malformed LLM response should return empty list."""
        with patch("app.stages.schedule_parser.llm_text_query", return_value="sorry"):
            types = extract_fixture_types_llm("schedule text")
            assert types == []

    def test_handles_compound_and_em_types(self):
        """Should preserve compound types (AS1/AS2) and EM variants."""
        mock_response = json.dumps({
            "fixture_types": ["AS1", "AS1/AS2", "LP1 EM", "D1A-EM", "B1.8'"]
        })
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            types = extract_fixture_types_llm("schedule text")
            assert "AS1/AS2" in types
            assert "LP1 EM" in types
            assert "D1A-EM" in types
            assert "B1.8'" in types


class TestParseFixtureSchedule:
    """Integration tests for the full schedule parsing flow."""

    def test_text_extractable_schedule(self):
        """AMLI BREA schedule page 5 has extractable text — should use pdfplumber + LLM."""
        mock_response = json.dumps({
            "fixture_types": ["AL1", "AS1", "B1", "BH1", "U1", "SS9"]
        })
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            result = parse_fixture_schedule(AMLI_PDF, [5])
            assert result["success"] is True
            assert len(result["fixture_types"]) > 0
            type_codes = [ft["type_code"] for ft in result["fixture_types"]]
            assert "AL1" in type_codes

    def test_rasterized_schedule_uses_vision(self):
        """Chase Bank schedule page 103 is rasterized — should use direct vision extraction."""
        vision_response = json.dumps({"fixture_types": ["D1A", "L-22"]})

        with patch("app.stages.schedule_parser.llm_vision_query", return_value=vision_response):
            result = parse_fixture_schedule(CHASE_PDF, [103])
            assert result["success"] is True
            type_codes = [ft["type_code"] for ft in result["fixture_types"]]
            assert "D1A" in type_codes

    def test_returns_structured_output(self):
        """Output should have correct structure."""
        mock_response = json.dumps({"fixture_types": ["X1"]})
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            result = parse_fixture_schedule(AMLI_PDF, [5])
            assert "success" in result
            assert "fixture_types" in result
            assert "error" in result
            for ft in result["fixture_types"]:
                assert "type_code" in ft
                assert isinstance(ft["type_code"], str)
