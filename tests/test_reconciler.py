import pytest
from app.stages.reconciler import reconcile_counts


def test_matching_counts_are_high_confidence():
    pdfplumber_counts = {"D1A": 37, "L1A": 32, "X1": 7}
    llm_counts = {"D1A": 37, "L1A": 32, "X1": 7}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    for item in result:
        assert item["confidence"] == "high"


def test_mismatched_counts_are_review():
    pdfplumber_counts = {"D1A": 45, "L1A": 32}
    llm_counts = {"D1A": 37, "L1A": 30}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    d1a = next(r for r in result if r["type"] == "D1A")
    assert d1a["confidence"] == "review"
    assert "pdfplumber=45" in d1a["note"]
    assert "llm=37" in d1a["note"]


def test_within_threshold_is_high():
    pdfplumber_counts = {"D1A": 38}
    llm_counts = {"D1A": 37}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    assert result[0]["confidence"] == "high"
    assert result[0]["quantity"] == 38  # pdfplumber takes priority


def test_type_in_one_but_not_other():
    pdfplumber_counts = {"D1A": 37, "EM": 5}
    llm_counts = {"D1A": 37}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    em = next(r for r in result if r["type"] == "EM")
    assert em["confidence"] == "review"
