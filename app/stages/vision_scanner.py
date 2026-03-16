"""Vision-based fixture type scanner.

Renders PDF pages to images and sends each to GPT-4.1 vision
to extract fixture type codes. One API call per page.
"""
import io
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.utils.pdf_utils import render_page_to_image

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an expert at reading engineering lighting drawings. "
    "You identify fixture type codes precisely and never invent codes not visible in the image."
)

_PROMPT = """You are reading a page from an engineering lighting drawing PDF.
List ALL lighting fixture TYPE CODES visible on this page.

WHAT ARE FIXTURE TYPE CODES:
- Short identifiers from a lighting fixture schedule: D1A, L-2, L-7, DF1, SS9, LT-104.1, BX(S), PH3-POLE
- They label lighting fixtures on floor plans (usually with a leader line to a symbol)
- They appear in the TYPE column of fixture schedule tables
- Include EM variants: D1A-EM, LP1 EM, L500-EM
- Include compound types: AS1/AS2, SC1/SC3
- Include size variants: B1.8', B1.12'

WHAT ARE NOT FIXTURE TYPE CODES (do NOT include these):
- Room/office numbers: L1, L10, L200, A101, C320 (these label rooms, not fixtures)
- Sheet references: E-001, E-211, A-301
- Panel/circuit labels: PP3, LP-21, MP-11, HP-2
- Catalog/part numbers: CLX-L48-4000LM, VCPG-LED-V4
- Manufacturer names, wattages, descriptions

Return valid JSON: {"fixture_types": ["TYPE1", "TYPE2", ...]}
If no fixture types are visible, return: {"fixture_types": []}"""

# Words that are never fixture types
_EXCLUDE = {
    "A", "B", "C", "D", "E", "F", "N", "S", "W",
    "OR", "ON", "IN", "AT", "TO", "OF", "BY", "NO",
    "LED", "DIM", "AC", "DC", "VA", "HP",
    "NEC", "UL", "ETL", "CSA",
    "YES", "SEE", "PER", "TYP", "MAX", "MIN",
    "THE", "AND", "FOR", "NOT", "ALL", "NEW",
    "WALL", "TYPE", "NONE", "NOTE", "NOTES",
    "SPEC", "REF", "QTY",
    "ED", "SF", "IC", "ID", "AM", "PM",
    "IP67", "IP65", "IP20", "GZ10", "GU10", "GU24",
}

# Panel/circuit reference prefixes
_PANEL_PREFIXES = {"MP", "HP", "EP", "PP", "EV"}


def scan_pages_for_types(
    pdf_path: str,
    page_indices: list[int],
    dpi: int = 200,
    max_workers: int = 4,
) -> dict[int, list[str]]:
    """Scan multiple pages with GPT-4.1 vision in parallel.

    Args:
        pdf_path: Path to the PDF file.
        page_indices: 0-indexed page numbers to scan.
        dpi: Rendering resolution.
        max_workers: Max parallel API calls.

    Returns:
        {page_index: [type_codes]} for each page.
    """
    t0 = time.time()
    logger.info("Vision scanner: scanning %d pages with GPT-4.1...", len(page_indices))

    results: dict[int, list[str]] = {}

    if not OPENAI_API_KEY:
        logger.warning("Vision scanner: OPENAI_API_KEY not set, skipping")
        return results

    def _scan_one(page_idx: int) -> tuple[int, list[str]]:
        try:
            image_bytes = render_page_to_image(pdf_path, page_idx, dpi=dpi)
            response = _call_gpt4_vision(image_bytes)
            types = _parse_response(response)
            types = _clean_types(types)
            logger.info("  Page %d: %d types", page_idx, len(types))
            return page_idx, types
        except Exception as e:
            logger.warning("  Page %d: vision failed — %s", page_idx, str(e)[:100])
            return page_idx, []

    workers = min(max_workers, len(page_indices))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_scan_one, idx) for idx in page_indices]
        for f in as_completed(futures):
            page_idx, types = f.result()
            results[page_idx] = types

    total = time.time() - t0
    total_types = sum(len(t) for t in results.values())
    logger.info("Vision scanner: done — %d types from %d pages in %.1fs",
                total_types, len(results), total)
    return results


def aggregate_types(
    page_types: dict[int, list[str]],
    schedule_pages: list[int],
) -> list[str]:
    """Aggregate types across pages with frequency-based filtering.

    - Types on 2+ pages: high confidence — keep
    - Types on 1 page that IS a schedule page: keep (schedules list types once)
    - Types on 1 page that is NOT a schedule page: drop (likely noise)

    Returns deduplicated list of fixture type codes.
    """
    # Count pages per type (using normalized key for dedup)
    type_pages: dict[str, set[int]] = {}  # norm_key -> set of page indices
    norm_to_raw: dict[str, str] = {}  # norm_key -> first raw form

    schedule_set = set(schedule_pages)

    for page_idx, types in page_types.items():
        for t in types:
            key = _normalize(t)
            if not key:
                continue
            type_pages.setdefault(key, set()).add(page_idx)
            if key not in norm_to_raw:
                norm_to_raw[key] = t

    # Filter
    result = []
    for key in sorted(type_pages.keys()):
        pages = type_pages[key]
        raw = norm_to_raw[key]
        if len(pages) >= 2:
            # High confidence: appears on multiple pages
            result.append(raw)
        elif len(pages) == 1:
            page = next(iter(pages))
            if page in schedule_set:
                # Schedule page: types listed once, still valid
                result.append(raw)
            else:
                logger.debug("  Dropping %s (only on non-schedule page %d)", raw, page)

    logger.info("Aggregation: %d types kept (%d on 2+ pages, %d schedule-only)",
                len(result),
                sum(1 for k in type_pages if len(type_pages[k]) >= 2),
                sum(1 for k in type_pages if len(type_pages[k]) == 1
                    and next(iter(type_pages[k])) in schedule_set))
    return result


def _call_gpt4_vision(image_bytes: bytes) -> str:
    """Call OpenAI GPT-4.1 vision API."""
    import base64
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": _PROMPT},
            ]},
        ],
        max_tokens=4096,
    )
    return resp.choices[0].message.content


def _parse_response(response: str) -> list[str]:
    """Parse fixture types from GPT JSON response."""
    text = response.strip()
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
        match = re.search(r'\{.*"fixture_types".*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return [str(t) for t in data.get("fixture_types", []) if t]
            except json.JSONDecodeError:
                pass

    logger.warning("Could not parse vision response: %.200s", text)
    return []


def _clean_types(types: list[str]) -> list[str]:
    """Clean and filter raw type codes from vision output."""
    result = []
    for raw in types:
        t = raw.strip()
        if not t:
            continue
        # Strip parenthesized size suffixes: L1A (4') -> L1A
        t = re.sub(r'\s+\([^)]+\)', '', t).strip()
        # Strip trailing size: WS1 4'8" -> WS1
        t = re.sub(r"""\s+\d+'[\d"]*$""", '', t)
        upper = t.upper()
        # Filter excluded words
        if upper in _EXCLUDE:
            continue
        # Filter panel references
        m = re.match(r'^([A-Z]+)', upper)
        if m and m.group(1) in _PANEL_PREFIXES:
            continue
        # Must have at least 1 letter
        if not any(c.isalpha() for c in t):
            continue
        # Reasonable length
        if len(t) < 2 or len(t) > 15:
            continue
        # Filter likely room/office numbers: single letter + 2-3 pure digits (L10, A101, C320)
        # Real fixture codes with single-letter prefix have 1-digit numbers (B1, U3)
        # or dashes (L-2, L-7) or letter suffixes (D1A, L1A)
        if re.match(r'^[A-Z]\d{2,}$', upper):
            continue
        result.append(t)
    return result


def _normalize(code: str) -> str:
    """Normalize for dedup: remove dashes, spaces, underscores, quotes. Keep dots and slashes."""
    return ''.join(ch for ch in code.strip() if ch not in ('-', ' ', '_', '"', "'", '`')).upper()
