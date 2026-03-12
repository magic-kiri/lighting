import re
from app.utils.pdf_utils import extract_page_words, extract_page_full_text


def parse_fixture_schedule(pdf_path: str, page_indices: list[int]) -> dict:
    """Extract fixture type codes from schedule pages.
    Returns: {"success": bool, "fixture_types": [{"type_code": str, "description": str}], "error": str|None}
    """
    all_types = []

    for page_idx in page_indices:
        text = extract_page_full_text(pdf_path, page_idx)
        words = extract_page_words(pdf_path, page_idx)

        if len(words) < 20:
            continue

        found_types = _extract_types_from_text(text, words)
        all_types.extend(found_types)

    if not all_types:
        return {
            "success": False,
            "fixture_types": [],
            "error": (
                f"No fixture types found on schedule pages {[i+1 for i in page_indices]}. "
                "The schedule may be rasterized as an image. Manual schedule input required."
            ),
        }

    seen = set()
    unique_types = []
    for ft in all_types:
        if ft["type_code"] not in seen:
            seen.add(ft["type_code"])
            unique_types.append(ft)

    return {"success": True, "fixture_types": unique_types, "error": None}


def _extract_types_from_text(text: str, words: list[dict]) -> list[dict]:
    """Extract fixture type codes from schedule text."""
    fixture_pattern = re.compile(r'^[A-Z]{1,4}[-]?[A-Z0-9]{0,4}[-]?[A-Z0-9]{0,4}$')

    candidates = []
    for w in words:
        word_text = w["text"].strip()
        if 1 <= len(word_text) <= 10 and fixture_pattern.match(word_text):
            if word_text not in _EXCLUDE_WORDS:
                candidates.append({"type_code": word_text, "description": ""})

    return candidates


_EXCLUDE_WORDS = {
    "A", "B", "C", "D", "E", "F", "N", "S", "W",
    "OR", "ON", "IN", "AT", "TO", "OF", "BY", "NO",
    "LED", "DIM", "AC", "DC", "VA", "HP",
    "NEC", "UL", "ETL", "CSA",
    "YES", "SEE", "PER", "TYP", "MAX", "MIN",
    "THE", "AND", "FOR", "NOT", "ALL", "NEW",
    "WALL", "TYPE",
}
