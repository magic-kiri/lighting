import json
import logging
import re
import time
import fitz
from app.utils.pdf_utils import extract_page_full_text, get_page_count, extract_all_page_titles
from app.utils.llm_client import llm_text_query

logger = logging.getLogger(__name__)

# Known lighting fixture code prefixes for deterministic page detection
_FIXTURE_CODE_DETECT_RE = re.compile(
    r'\b('
    r'D\d+[A-Z]?'      # D1A, D1B, D2 (downlights)
    r'|L\d+[A-Z]?'     # L1A, L2A, L5, L6 (linear)
    r'|L-\d+'          # L-8, L-22 (linear with dash)
    r'|DF\d+'          # DF01, DF3 (decorative fixtures)
    r'|X\d+'           # X1 (exit signs)
    r'|B\d+[A-Z]?'    # B1, B2, B5
    r'|U\d+[A-Z]?'    # U1, U2
    r')\b'
)


def detect_lighting_pages(pdf_path: str, min_codes: int = 6, expand_range: int = 2) -> list[int]:
    """Detect lighting plan pages by scanning for fixture code patterns.

    Strategy: find the page with the MOST fixture codes (anchor), then include
    nearby pages within ±expand_range that also have fixture codes. This avoids
    picking up architectural pages (RCPs) that duplicate fixture labels in a
    different section of the document.

    Uses fitz (PyMuPDF) for speed — no LLM API call needed.
    Returns 0-indexed page numbers sorted by fixture code density (most first).
    """
    doc = fitz.open(pdf_path)
    page_scores = {}
    for i in range(doc.page_count):
        text = doc[i].get_text()
        matches = _FIXTURE_CODE_DETECT_RE.findall(text)
        if len(matches) >= min_codes:
            page_scores[i] = len(matches)
    doc.close()

    if not page_scores:
        logger.info("Deterministic detection: no pages with >= %d fixture codes", min_codes)
        return []

    # Find anchor — the page with the most fixture codes
    anchor = max(page_scores, key=page_scores.get)
    logger.info(
        "Deterministic detection: anchor page %d (%d codes), %d total candidates",
        anchor, page_scores[anchor], len(page_scores),
    )

    # Include pages within ±expand_range of anchor that have enough codes
    result = []
    for page_idx, count in page_scores.items():
        if abs(page_idx - anchor) <= expand_range:
            result.append((page_idx, count))

    result.sort(key=lambda x: x[1], reverse=True)
    for page_idx, count in result:
        logger.info("  Page %d: %d fixture codes", page_idx, count)
    return [page_idx for page_idx, _ in result]

SYSTEM_PROMPT = """You are an expert at reading engineering drawing sheet indexes.
You classify pages from electrical engineering PDF drawings.

Given a list of page numbers and their extracted title text, classify each page into exactly one category:

- LIGHTING_PLAN: Floor plan pages showing lighting fixture placements (symbols on a floor plan). These are the pages where you'd count fixture symbols.
- FIXTURE_SCHEDULE: Pages containing a fixture schedule table (a table defining fixture type codes, descriptions, manufacturers, wattages).
- UNIT_PLAN: Individual apartment/unit type electrical plans showing fixtures for a single repeating unit type (common in residential projects).
- OTHER: Everything else (cover sheets, general notes, power plans, panel schedules, details, specs, site plans, roof plans, fire alarm, etc.)

Return ONLY valid JSON in this exact format:
{"pages": [{"page": 1, "category": "OTHER", "reason": "Cover sheet"}, ...]}

Important:
- LIGHTING_PLAN means a floor plan with fixture symbols to count — not a lighting control plan, not a lighting detail, not a photometric plan.
- FIXTURE_SCHEDULE is specifically the table that defines fixture types — not a panel schedule.
- UNIT_PLAN is only for residential projects with repeating unit types (apartment buildings, hotels).
"""


def extract_sheet_titles(pdf_path: str) -> dict[int, str]:
    """Extract a short title/description from each page.
    Returns {page_index: title_text} for all pages.
    Uses single PDF open for speed.
    """
    return extract_all_page_titles(pdf_path)


def classify_pages(pdf_path: str) -> dict:
    """Classify all pages using LLM.
    Returns:
        {
            "lighting_plans": [page_indices],
            "fixture_schedules": [page_indices],
            "unit_plans": [page_indices],
            "other": [page_indices],
            "raw_classifications": [{page, category, reason}, ...]
        }
    """
    t0 = time.time()
    titles = extract_sheet_titles(pdf_path)
    logger.info("Title extraction complete (%.1fs)", time.time() - t0)

    lines = []
    for idx, title in sorted(titles.items()):
        short_title = title[:200].replace("\n", " ").strip()
        lines.append(f"Page {idx + 1}: {short_title}")

    prompt = "Classify each page:\n\n" + "\n".join(lines)
    logger.info("Sending %d page titles to LLM for classification...", len(lines))
    t0 = time.time()
    response = llm_text_query(SYSTEM_PROMPT, prompt)
    logger.info("LLM classification response received (%.1fs)", time.time() - t0)

    classifications = _parse_llm_response(response)
    logger.info("Parsed %d page classifications", len(classifications))

    result = {
        "lighting_plans": [],
        "fixture_schedules": [],
        "unit_plans": [],
        "other": [],
        "raw_classifications": classifications,
    }

    for item in classifications:
        page_idx = item["page"] - 1  # Convert 1-based to 0-based
        cat = item.get("category", "OTHER").upper()
        if cat == "LIGHTING_PLAN":
            result["lighting_plans"].append(page_idx)
        elif cat == "FIXTURE_SCHEDULE":
            result["fixture_schedules"].append(page_idx)
        elif cat == "UNIT_PLAN":
            result["unit_plans"].append(page_idx)
        else:
            result["other"].append(page_idx)

    return result


def _parse_llm_response(response: str) -> list[dict]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = response.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "pages" in data:
            return data["pages"]
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        match = re.search(r'\{.*"pages".*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return data.get("pages", [])

    return []
