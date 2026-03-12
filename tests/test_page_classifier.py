import pytest
from app.stages.page_classifier import classify_pages, extract_sheet_titles

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_extract_sheet_titles_amli():
    titles = extract_sheet_titles(AMLI_PDF)
    assert isinstance(titles, dict)
    assert len(titles) > 0
    assert all(isinstance(k, int) for k in titles.keys())
    assert all(isinstance(v, str) for v in titles.values())


def test_classify_pages_amli():
    result = classify_pages(AMLI_PDF)
    assert len(result["lighting_plans"]) > 0
    assert len(result["fixture_schedules"]) > 0
    assert len(result["unit_plans"]) > 0


def test_classify_pages_chase():
    result = classify_pages(CHASE_PDF)
    assert len(result["lighting_plans"]) > 0
    assert len(result["fixture_schedules"]) > 0
