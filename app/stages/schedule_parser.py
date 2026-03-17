import json
import logging
import re
import time
from app.config import SCHEDULE_TEXT_THRESHOLD, OPENAI_API_KEY
from app.utils.pdf_utils import extract_pages_text_batch, render_page_to_image
from app.utils.llm_client import llm_text_query, llm_vision_query

logger = logging.getLogger(__name__)

_EXTRACT_TYPES_SYSTEM = (
    "You are an expert at reading lighting fixture schedules from engineering drawings."
)

_EXTRACT_TYPES_PROMPT = """Below is text from a lighting fixture schedule in an engineering drawing PDF.
Extract ALL unique fixture TYPE CODES from this text.

WHAT ARE FIXTURE TYPE CODES:
- Short identifiers that name a lighting fixture type: D1A, L-22, DF01, SS9, LT-104.1, BX(S), PH3-POLE
- They appear at the START of each fixture entry in the schedule
- They have 1-2 letter prefix + optional separator + digits: B1, GA1, DF4, LP2, RD6A, LT-108
- Include EM (emergency) variants: D1A-EM, LP1 EM, L500-EM, L8EM, LR3 EM
- Include compound types with slash: AS1/AS2, SC1/SC3
- Include size-embedded codes: B1.8', B1.12'
- Include parenthesized codes: BX(S), BX(D)
- Include special variants: PH3-POLE
- Letter-only codes (2-3 letters, no digits) are valid if they name a fixture: GA, XA, XK

WHAT ARE NOT FIXTURE TYPE CODES (exclude these):
- Room/apartment names: A2, A3, C4, C5, Suite 100, Level 1
- Catalog/part numbers: CLX-L48-4000LM,?"4-12-WH-35, F3RS-1-F
- Manufacturer abbreviations: LUM, AME, GE, LIT, DIO
- Wattage/electrical values: 120V, 277V, 40W, 3000K
- Ratings: IP67, IP20, UL, ETL, CSA
- Drawing references: E0.04, A-301, M-501

Return ONLY valid JSON: {{"fixture_types": ["TYPE1", "TYPE2", ...]}}

Schedule text:
---
{schedule_text}
---"""

_VISION_OCR_SYSTEM = (
    "You are an expert at reading lighting fixture schedules from engineering drawings. "
    "Be precise and only report what you can clearly read."
)

_VISION_EXTRACT_PROMPT = """Look at this lighting fixture schedule from an engineering drawing.
Extract ALL unique fixture type codes from the TYPE column (usually the first or leftmost column).

CRITICAL RULES:
1. Read EVERY row in the table, including partially visible ones
2. Type codes are SHORT identifiers in the LEFTMOST column: L-2, L-7, D1A, DF1, SS9, LT-104.1
3. Include EM variants: D1A-EM, LP1 EM, L500-EM, L8EM
4. Include compound types: AS1/AS2, SC1/SC3
5. Include size variants: B1.8', B1.12', L1A (4')
6. Include parenthesized: BX(S), BX(D)
7. Include POLE variants: PH3-POLE

DO NOT:
- Include manufacturer names, catalog numbers, wattages, or descriptions
- Invent or guess types not clearly visible in the image
- Include types from memory or other projects — ONLY what you see HERE

Return ONLY valid JSON: {{"fixture_types": ["TYPE1", "TYPE2", ...]}}"""

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

# Prefixes that are panel/circuit references, not fixture codes.
# MP = Mechanical Panel, HP = HVAC Panel, EP = Electrical Panel, PP = Power Panel
_PANEL_PREFIXES = {"MP", "HP", "EP", "PP", "EV"}



def parse_fixture_schedule(pdf_path: str, page_indices: list[int], use_dual_model: bool = False) -> dict:
    """Extract fixture type codes from schedule pages using LLM.

    For text-extractable pages: pdfplumber text → LLM text extraction.
    For rasterized pages: render image → Claude vision (high quality OCR).
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
            # Text-extractable: chunked LLM extraction
            logger.info("  Page %d: %d chars — text-extractable", idx, len(text))
            t1 = time.time()
            types = _extract_types_from_long_text(text)
            logger.info("  Page %d: %d types in %.1fs", idx, len(types), time.time() - t1)
            all_types.extend(types)
        else:
            # Rasterized: try Cloud Vision OCR first (produces text like pdfplumber)
            from app.config import GOOGLE_API_KEY
            t1 = time.time()
            ocr_text = _cloud_vision_ocr(
                render_page_to_image(pdf_path, idx, dpi=200), GOOGLE_API_KEY
            )
            if len(ocr_text) >= SCHEDULE_TEXT_THRESHOLD:
                # Cloud Vision succeeded — extract types from OCR text
                logger.info("  Page %d: Cloud Vision OCR: %d chars", idx, len(ocr_text))
                # Split long OCR text into chunks for better LLM extraction
                # (LLM misses types in very long text — 36K+ chars)
                types = _extract_types_from_long_text(ocr_text)
                logger.info("  Page %d: extracted %d types in %.1fs", idx, len(types), time.time() - t1)
                all_types.extend(types)
            else:
                # Cloud Vision failed or empty page — fallback to Gemini vision
                logger.info("  Page %d: Cloud Vision returned %d chars, falling back to Gemini", idx, len(ocr_text))
                try:
                    img_bytes = render_page_to_image(pdf_path, idx, dpi=200)
                    response = llm_vision_query(
                        _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, img_bytes
                    )
                    types = _parse_fixture_types_response(response)
                    types = [_clean_type_code(t) for t in types]
                    logger.info("  Page %d: Gemini returned %d types in %.1fs", idx, len(types), time.time() - t1)
                    all_types.extend(types)
                except Exception as e:
                    logger.warning("  Page %d: Gemini fallback failed: %s", idx, str(e)[:100])

    # Clean up and deduplicate (with separator-normalized dedup)
    all_types = [_clean_type_code(t) for t in all_types]
    seen = set()
    fixture_types = []
    for t in all_types:
        t_upper = t.strip().upper()
        if not t_upper or t_upper in EXCLUDE_WORDS:
            continue
        # Normalize separators for dedup: "D1A EM" and "D1A-EM" → "D1AEM"
        norm_key = _dedup_normalize(t_upper)
        if norm_key not in seen:
            seen.add(norm_key)
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


def _openai_vision_query(system: str, prompt: str, image_bytes: bytes) -> str:
    """Send a vision query directly to OpenAI GPT-4.1 (bypasses configured provider).

    Used for high-quality OCR of rasterized schedules where accuracy is critical.
    GPT-4.1 has excellent vision capabilities for reading engineering drawings.
    """
    import base64
    from openai import OpenAI
    from app.config import OPENAI_API_KEY, OPENAI_MODEL

    client = OpenAI(api_key=OPENAI_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]},
        ],
        max_tokens=4096,
    )
    return resp.choices[0].message.content




def _extract_types_from_long_text(ocr_text: str) -> list[str]:
    """Extract fixture types from long OCR text by chunking + LLM.

    Long OCR text (36K+ chars) causes LLMs to miss types. Solution:
    split into overlapping chunks, extract from each chunk independently,
    union all results. Purely LLM-based — no regex overfitting.
    """
    all_types = []

    # Chunked LLM extraction (4000 char chunks with 500 char overlap)
    chunk_size = 4000
    overlap = 500
    chunks = []
    for i in range(0, len(ocr_text), chunk_size - overlap):
        chunk = ocr_text[i:i + chunk_size]
        if len(chunk) > 200:
            chunks.append(chunk)

    logger.info("  Splitting %d chars into %d chunks for LLM extraction", len(ocr_text), len(chunks))
    for i, chunk in enumerate(chunks):
        try:
            types = extract_fixture_types_llm(chunk)
            logger.info("  Chunk %d/%d: %d types", i + 1, len(chunks), len(types))
            all_types.extend(types)
        except Exception as e:
            logger.warning("  Chunk %d/%d failed: %s", i + 1, len(chunks), str(e)[:100])

    return all_types


def _cloud_vision_ocr(image_bytes: bytes, api_key: str) -> str:
    """Extract text from image using Google Cloud Vision DOCUMENT_TEXT_DETECTION."""
    import base64
    import requests

    if not api_key:
        return ""

    url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "requests": [{
            "image": {"content": b64},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}]
        }]
    }

    try:
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            if 'responses' in data and data['responses']:
                return data['responses'][0].get('fullTextAnnotation', {}).get('text', '')
        logger.warning("  Cloud Vision API error: %d %s", resp.status_code, resp.text[:100])
    except Exception as e:
        logger.warning("  Cloud Vision API failed: %s", str(e)[:100])

    return ""




def _dedup_normalize(code: str) -> str:
    """Normalize for deduplication: remove dashes, spaces, underscores, quotes.

    Preserves dots and slashes (they carry meaning).
    "D1A EM" → "D1AEM", "D1A-EM" → "D1AEM", "L-500" → "L500"
    """
    return ''.join(ch for ch in code if ch not in ('-', ' ', '_', '"', "'", '`')).upper()


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
        'L1A (4')' → 'L1A'   (strip size suffix)
        'L500 (2')' → 'L500' (strip size suffix)
    """
    raw = raw.strip()
    if not raw:
        return raw
    # Strip parenthesized size/variant suffixes FIRST (before EM check):
    # "L-500 (2') EM" → "L-500 EM", "L1A (4') EM" → "L1A EM"
    # But keep BX(S), BX(D) where parens are part of the code (no space before paren)
    raw = re.sub(r'\s+\([^)]+\)', '', raw).strip()
    # Keep EM variants intact: "LP1 EM", "D1A-EM", "L500-EM"
    if re.match(r'^[A-Z0-9.\'/-]+ ?-?EM$', raw, re.IGNORECASE):
        return raw
    # Strip trailing size like 4'8", 7'6" (space-separated)
    raw = re.sub(r"""\s+\d+'[\d"]*$""", '', raw)
    # Strip trailing description words (anything after first word boundary that's 3+ letters)
    # e.g., "D2 DOWNLIGHT" → "D2", "L2A STRAIGHT" → "L2A"
    m = re.match(r'^([A-Z0-9.\'/()-]+(?:\s?-?EM)?)\s+[A-Z]{3,}', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    # Strip trailing slash-duplicates: "L5/L5 PENDANT" → "L5"
    m = re.match(r'^([A-Z0-9.\'-]+)/\1\b', raw, re.IGNORECASE)
    if m:
        return m.group(1)
    return raw
