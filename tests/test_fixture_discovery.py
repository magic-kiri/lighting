import pytest
from app.pipeline import _cross_validate_types


def test_cross_validate_finds_floor_plan_only_types():
    """Types on floor plan with 2+ letter prefix match should be flagged."""
    schedule_types = ["DF1", "LP1", "SS9"]
    floor_plan_words = ["DF1", "LP1", "LP3", "SS9", "SS7", "WALL", "DOOR", "A103"]

    result = _cross_validate_types(schedule_types, floor_plan_words)
    assert "DF1" in result
    assert "LP1" in result
    assert "SS9" in result
    # LP3 shares 'LP' prefix with LP1 — should be added
    assert "LP3" in result
    # SS7 shares 'SS' prefix with SS9 — should be added
    assert "SS7" in result
    # WALL, DOOR, A103 should NOT be in results
    assert "WALL" not in result
    assert "DOOR" not in result
    assert "A103" not in result


def test_cross_validate_empty_floor_plan():
    """If no floor plan words, should return schedule types unchanged."""
    schedule_types = ["AL1", "BH1", "SS9"]
    result = _cross_validate_types(schedule_types, [])
    assert result == ["AL1", "BH1", "SS9"]


def test_cross_validate_filters_room_numbers():
    """Room/drawing numbers like A103, E-211 should not be added."""
    schedule_types = ["AL1", "DF1"]
    floor_plan_words = ["AL1", "DF1", "A103", "A201", "E-211", "DF3"]

    result = _cross_validate_types(schedule_types, floor_plan_words)
    assert "DF3" in result  # shares 'DF' prefix
    assert "A103" not in result  # single letter + 3 digits = room number
    assert "A201" not in result
    assert "E-211" not in result
