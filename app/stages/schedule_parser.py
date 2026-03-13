import json
import logging
import re
import time
from app.config import SCHEDULE_TEXT_THRESHOLD
from app.utils.pdf_utils import extract_pages_text_batch, render_page_to_image
from app.utils.llm_client import llm_text_query, llm_vision_query

logger = logging.getLogger(__name__)

_EXTRACT_TYPES_SYSTEM = (
    "You are an expert at reading lighting fixture schedules from engineering drawings."
)

_EXTRACT_TYPES_PROMPT = """Below is text extracted from a lighting fixture schedule in an engineering drawing PDF.
Extract ALL unique fixture type codes from this schedule.

Rules:
- Type codes are short identifiers like D1A, L-22, DF01, SS9, BX(S), LT-104.1
- Include EM (emergency) variants as separate types (e.g., D1A-EM, LP1 EM)
- Include compound types (e.g., AS1/AS2, SC1/SC3)
- Include size variants that are part of the code (e.g., B1.8', B1.12')
- Do NOT include descriptions, manufacturers, wattages, or catalog numbers
- Do NOT invent types that are not in the text

Return ONLY valid JSON: {{"fixture_types": ["TYPE1", "TYPE2", ...]}}

Schedule text:
---
{schedule_text}
---"""

_VISION_OCR_SYSTEM = (
    "You are an expert at reading lighting fixture schedules from engineering drawings. "
    "Be precise and only report what you can clearly read."
)

_VISION_OCR_PROMPT = (
    "Read this lighting fixture schedule table. "
    "Return all text you can see, preserving the table structure. "
    "Focus especially on the TYPE column which contains fixture type codes."
)

# Words to exclude — shared with pipeline.py for cross-validation filtering
EXCLUDE_WORDS = {
    "A", "B", "C", "D", "E", "F", "N", "S", "W",
    "OR", "ON", "IN", "AT", "TO", "OF", "BY", "NO",
    "LED", "DIM", "AC", "DC", "VA", "HP",
    "NEC", "UL", "ETL", "CSA",
    "YES", "SEE", "PER", "TYP", "MAX", "MIN",
    "THE", "AND", "FOR", "NOT", "ALL", "NEW",
    "WALL", "TYPE", "NONE", "NOTE", "NOTES",
    "SPEC", "REF", "QTY",
}


def parse_fixture_schedule(pdf_path: str, page_indices: list[int]) -> dict:
    """Extract fixture type codes from schedule pages using LLM.

    For text-extractable pages: pdfplumber text → LLM text extraction.
    For rasterized pages: render image → LLM vision direct type extraction.
    Results are merged and deduplicated.

    Returns:
        {
            "success": bool,
            "fixture_types": [{"type_code": str}],
            "error": str | None,
        }
    """
    logger.info("Schedule parser: processing %d page(s): %s", len(page_indices), page_indices)
    t0 = time.time()

    page_texts = extract_pages_text_batch(pdf_path, page_indices)
    all_types = []

    # Process each page with the best strategy
    for idx in page_indices:
        text = page_texts.get(idx, "")
        if len(text) >= SCHEDULE_TEXT_THRESHOLD:
            # Text-extractable: pdfplumber text → LLM text extraction
            logger.info("  Page %d: %d chars — text-extractable, using LLM text extraction", idx, len(text))
            t1 = time.time()
            types = extract_fixture_types_llm(text)
            logger.info("  Page %d: LLM returned %d types in %.1fs", idx, len(types), time.time() - t1)
            all_types.extend(types)
        else:
            # Rasterized: direct vision type extraction (1-step, no intermediate OCR)
            logger.info("  Page %d: %d chars — rasterized, using direct vision extraction", idx, len(text))
            t1 = time.time()
            types = _extract_types_with_vision(pdf_path, idx)
            logger.info("  Page %d: vision returned %d types in %.1fs", idx, len(types), time.time() - t1)
            all_types.extend(types)

    # Clean up and deduplicate
    all_types = [_clean_type_code(t) for t in all_types]
    seen = set()
    fixture_types = []
    for t in all_types:
        t_upper = t.strip().upper()
        if t_upper and t_upper not in seen and t_upper not in EXCLUDE_WORDS:
            seen.add(t_upper)
            fixture_types.append(t)

    if not fixture_types:
        return {
            "success": False,
            "fixture_types": [],
            "error": "No fixture types extracted from schedule pages.",
        }

    total_time = time.time() - t0
    logger.info("Schedule parser: SUCCESS — %d unique types in %.1fs", len(fixture_types), total_time)

    return {
        "success": True,
        "fixture_types": [{"type_code": t} for t in fixture_types],
        "error": None,
    }


_VISION_EXTRACT_PROMPT = """Look at this lighting fixture schedule page from an engineering drawing.
Extract ALL unique fixture type codes from the TYPE column.

Rules:
- Type codes are short identifiers like D1A, L-22, DF01, SS9, BX(S), LT-104.1
- Include EM (emergency) variants as separate types (e.g., D1A-EM, LP1 EM)
- Include compound types (e.g., AS1/AS2, SC1/SC3)
- Include size variants that are part of the code (e.g., B1.8', B1.12')
- Do NOT include descriptions, manufacturers, wattages, or catalog numbers
- Only report codes you can CLEARLY read — do not guess or invent codes

Return ONLY valid JSON: {{"fixture_types": ["TYPE1", "TYPE2", ...]}}"""


def _extract_types_with_vision(pdf_path: str, page_index: int) -> list[str]:
    """Render a page and directly extract fixture type codes via LLM vision."""
    try:
        image_bytes = render_page_to_image(pdf_path, page_index, dpi=200)
        logger.info("  Sending %.1f KB image to vision LLM...", len(image_bytes) / 1024)
        response = llm_vision_query(
            _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, image_bytes
        )
        return _parse_fixture_types_response(response)
    except Exception as e:
        logger.warning("  Vision extraction failed for page %d: %s", page_index, e)
        return []


def extract_fixture_types_llm(schedule_text: str) -> list[str]:
    """Send schedule text to LLM and extract fixture type codes.

    Returns list of unique type code strings.
    """
    prompt = _EXTRACT_TYPES_PROMPT.format(schedule_text=schedule_text)
    response = llm_text_query(_EXTRACT_TYPES_SYSTEM, prompt)
    return _parse_fixture_types_response(response)


def _parse_fixture_types_response(response: str) -> list[str]:
    """Parse the LLM response to extract fixture type codes."""
    text = response.strip()
    # Strip markdown code blocks
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "fixture_types" in data:
            return [str(t) for t in data["fixture_types"] if t]
        if isinstance(data, list):
            return [str(t) for t in data if t]
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r'\{.*"fixture_types".*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return [str(t) for t in data.get("fixture_types", []) if t]
            except json.JSONDecodeError:
                pass

    logger.warning("Could not parse fixture types from LLM response: %.200s", text)
    return []


def _clean_type_code(raw: str) -> str:
    """Clean a raw type code from LLM output.

    Strips trailing descriptions, normalizes whitespace.
    Examples:
        'D2 DOWNLIGHT' → 'D2'
        'L2A STRAIGHT' → 'L2A'
        'L1A ACT GRID' → 'L1A'
        'DF01 (AL)' → 'DF01'
        'L5/L5 PENDANT' → 'L5'
        'LP1 EM' → 'LP1 EM'  (keep EM variants)
    """
    raw = raw.strip()
    if not raw:
        return raw
    # Keep EM variants intact: "LP1 EM", "D1A-EM"
    if re.match(r'^[A-Z0-9.\'/-]+ ?EM$', raw, re.IGNORECASE):
        return raw
    # Strip parenthesized suffixes that are NOT part of the code
    # Keep BX(S), BX(D) but strip DF01 (AL)
    raw = re.sub(r'\s+\([^)]+\)\s*$', '', raw)
    # Strip trailing description words (anything after first word boundary that's 3+ letters)
    # e.g., "D2 DOWNLIGHT" → "D2", "L2A STRAIGHT" → "L2A"
    m = re.match(r'^([A-Z0-9.\'/()-]+(?:\s?EM)?)\s+[A-Z]{3,}', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    # Strip trailing slash-duplicates: "L5/L5 PENDANT" → "L5"
    m = re.match(r'^([A-Z0-9.\'-]+)/\1\b', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    return raw
