import pytest
from app.pipeline import (
    _looks_like_fixture_code,
    _normalize_type_code,
    _find_fixture_codes_in_words,
    _merge_type_sources,
    _filter_vision_hallucinations,
)


def test_looks_like_fixture_code_accepts_valid():
    """Valid fixture codes should be recognized."""
    valid = ["D1A", "DF01", "L-22", "LT-104.1", "SS9", "U1A", "L500", "RD6A"]
    for code in valid:
        assert _looks_like_fixture_code(code), f"Should accept {code}"


def test_looks_like_fixture_code_rejects_noise():
    """Non-fixture words, long-prefix codes, and sheet refs should be rejected."""
    noise = ["WALL", "DOOR", "LED", "TYPE", "EM", "AB", "THE", "",
             "CAT6E", "WAC60", "BLGA-13", "E0.04", "A.3", "M.5"]
    for word in noise:
        assert not _looks_like_fixture_code(word), f"Should reject {word}"


def test_looks_like_fixture_code_em_variants():
    """EM variant fixture codes should be recognized."""
    assert _looks_like_fixture_code("D1A-EM")
    assert _looks_like_fixture_code("L500-EM")
    assert _looks_like_fixture_code("L8EM")


def test_normalize_type_code_strips_leading_zeros():
    """Leading zeros in single-digit numbers should be stripped."""
    assert _normalize_type_code("DF01") == "DF1"
    assert _normalize_type_code("DF03") == "DF3"
    assert _normalize_type_code("F05") == "F5"


def test_normalize_type_code_preserves_multi_digit():
    """Multi-digit numbers should not be changed."""
    assert _normalize_type_code("LT-101") == "LT-101"
    assert _normalize_type_code("L500") == "L500"
    assert _normalize_type_code("L-22") == "L-22"


def test_find_fixture_codes_filters_by_freq_and_prefix():
    """Unknown-prefix types need freq >= 3; known-prefix types accepted at any freq."""
    words_by_page = {
        0: [
            {"text": "D1A", "x0": 10, "y0": 10, "x1": 30, "y1": 15},
            {"text": "D1A", "x0": 50, "y0": 50, "x1": 70, "y1": 55},
            {"text": "D1A", "x0": 90, "y0": 90, "x1": 110, "y1": 95},
            {"text": "A103", "x0": 100, "y0": 10, "x1": 130, "y1": 15},
            {"text": "DF3", "x0": 200, "y0": 10, "x1": 220, "y1": 15},
        ],
    }
    schedule_set = {"DF1"}  # DF prefix is known from schedule
    result = _find_fixture_codes_in_words(words_by_page, schedule_set)
    assert "D1A" in result  # freq=3, passes threshold for unknown prefix
    assert "DF3" in result  # prefix DF known from schedule, freq=1 OK
    assert "A103" not in result  # freq=1, unknown prefix


def test_merge_type_sources_deduplicates():
    """Merge should combine without duplicates, schedule types first."""
    schedule = ["DF1", "LP1", "SS9"]
    floor = ["DF1", "LP3", "SS7", "RD2"]
    result = _merge_type_sources(schedule, floor)
    assert result[:3] == ["DF1", "LP1", "SS9"]
    assert "LP3" in result
    assert "SS7" in result
    assert "RD2" in result
    # No duplicates
    assert len(result) == len(set(t.upper() for t in result))


def test_merge_type_sources_normalized_dedup():
    """DF01 from floor plans should not duplicate DF1 from schedule."""
    schedule = ["DF1"]
    floor = ["DF01"]
    result = _merge_type_sources(schedule, floor)
    assert len(result) == 1
    assert result[0] == "DF1"


def test_filter_vision_hallucinations_alpha_suffix():
    """Alphabetic suffix sequences (5+ variants) should be trimmed to A/B only."""
    vision = ["L1A", "L1B", "L1C", "L1D", "L1E", "L1F", "L1G"]
    filtered = _filter_vision_hallucinations(vision, [], [])
    codes = [t.upper() for t in filtered]
    assert "L1A" in codes
    assert "L1B" in codes
    assert "L1C" not in codes
    assert "L1G" not in codes


def test_filter_vision_hallucinations_numeric_sequence():
    """Dense numeric sequences (10+ types in a range) should be filtered."""
    # L-401 through L-420 = 20 hallucinated types, L-411 is on floor plans
    vision = [f"L-{n}" for n in range(401, 421)] + ["DF3"]
    filtered = _filter_vision_hallucinations(
        vision, [], ["L-411"]  # L-411 corroborated by floor plans
    )
    codes = [t.upper() for t in filtered]
    assert "L-411" in codes  # kept: on floor plans
    assert "L-401" not in codes  # dropped: numeric hallucination
    assert "L-420" not in codes  # dropped: numeric hallucination
    assert "DF3" in codes  # unrelated, kept


def test_filter_vision_hallucinations_deduplicates():
    """Vision filter should deduplicate within vision types."""
    vision = ["DF1", "DF1", "DF3"]
    filtered = _filter_vision_hallucinations(vision, [], [])
    codes = [t.upper() for t in filtered]
    assert codes.count("DF1") == 1
    assert "DF3" in codes
