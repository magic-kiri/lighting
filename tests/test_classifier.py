import pytest
from app.stages.classifier import classify_pdf

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"
POPEYES_PDF = "Newberg Popeyes Permit Set Revised_ E-Sheets.pdf"


def test_amli_is_extractable():
    result = classify_pdf(AMLI_PDF)
    assert result["extractable"] is True
    assert result["error"] is None


def test_chase_is_extractable():
    result = classify_pdf(CHASE_PDF)
    assert result["extractable"] is True


def test_popeyes_is_not_extractable():
    result = classify_pdf(POPEYES_PDF)
    assert result["extractable"] is False
    assert result["error"] is not None
