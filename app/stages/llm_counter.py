import json
import re
from app.utils.pdf_utils import render_page_to_image
from app.utils.llm_client import llm_vision_query
from app.config import RENDER_DPI

SYSTEM_PROMPT = """You are an expert electrical engineer who counts lighting fixtures on engineering floor plans.

You will be given:
1. An image of an electrical lighting plan (a floor plan from engineering drawings)
2. A list of fixture type codes to look for

Your task: Count every instance of each fixture type that is PLACED on the floor plan.

Rules:
- Only count fixtures that are actual placements on the floor plan (symbols with labels next to them)
- Do NOT count labels that appear in legends, keynotes, schedules, title blocks, or annotation tables
- Do NOT count labels that appear in switch/circuit annotations unless they are actual fixture placements
- If a fixture label has a suffix like "w1" or "w2" (switch groups), it still counts as one fixture
- If a fixture has "-EM" suffix (emergency), count it under the -EM type if it's in the type list, otherwise under the base type

Return ONLY valid JSON in this exact format:
{"counts": {"TYPE1": count, "TYPE2": count, ...}}

Only include types that have count > 0.
"""


def count_fixtures_with_llm(pdf_path: str, page_index: int, fixture_types: list[str]) -> dict[str, int]:
    """Count fixtures on a page using LLM vision."""
    image_bytes = render_page_to_image(pdf_path, page_index, dpi=RENDER_DPI)

    type_list = ", ".join(fixture_types)
    prompt = (
        f"Count every instance of these fixture types on this lighting plan: {type_list}\n\n"
        "Return JSON with the counts. Only include types with count > 0."
    )

    response = llm_vision_query(SYSTEM_PROMPT, prompt, image_bytes)

    return _parse_count_response(response, fixture_types)


def count_fixtures_with_llm_multi_page(
    pdf_path: str, page_indices: list[int], fixture_types: list[str]
) -> dict[str, int]:
    """Count fixtures across multiple pages using LLM, summing results."""
    from collections import Counter
    total = Counter()
    for page_idx in page_indices:
        page_counts = count_fixtures_with_llm(pdf_path, page_idx, fixture_types)
        total.update(page_counts)
    return dict(total)


def _parse_count_response(response: str, valid_types: list[str]) -> dict[str, int]:
    """Parse LLM JSON response into fixture counts."""
    text = response.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "counts" in data:
            raw_counts = data["counts"]
        elif isinstance(data, dict):
            raw_counts = data
        else:
            return {}
    except json.JSONDecodeError:
        match = re.search(r'\{[^{}]*\}', text)
        if match:
            raw_counts = json.loads(match.group())
        else:
            return {}

    # Normalize and validate
    valid_upper = {t.upper(): t for t in valid_types}
    counts = {}
    for key, value in raw_counts.items():
        normalized = key.upper().strip()
        if normalized in valid_upper:
            counts[valid_upper[normalized]] = int(value)

    return counts
