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

# Specification values that look like fixture codes but aren't
_SPEC_CODES = {"IP67", "IP65", "IP20", "IP44", "GZ10", "GZ4", "GU10", "GU24",
               "T5", "T8", "E26", "E12", "G24", "G5", "G9"}


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
            # Text-extractable: LLM extraction + regex extraction
            logger.info("  Page %d: %d chars — text-extractable, using LLM + regex", idx, len(text))
            t1 = time.time()
            types = extract_fixture_types_llm(text)
            logger.info("  Page %d: LLM returned %d types in %.1fs", idx, len(types), time.time() - t1)
            all_types.extend(types)
            regex_types = _extract_types_from_schedule_text(text)
            logger.info("  Page %d: regex found %d additional types", idx, len(regex_types))
            all_types.extend(regex_types)
        else:
            # Rasterized: try Cloud Vision OCR first (produces text like pdfplumber)
            from app.config import GOOGLE_API_KEY
            t1 = time.time()
            ocr_text = _cloud_vision_ocr(
                render_page_to_image(pdf_path, idx, dpi=300), GOOGLE_API_KEY
            )
            if len(ocr_text) >= SCHEDULE_TEXT_THRESHOLD:
                # Cloud Vision succeeded — treat as text-extractable (high confidence)
                logger.info("  Page %d: rasterized → Cloud Vision OCR: %d chars (treating as text)", idx, len(ocr_text))
                types = extract_fixture_types_llm(ocr_text)
                logger.info("  Page %d: LLM returned %d types in %.1fs", idx, len(types), time.time() - t1)
                all_types.extend(types)
                regex_types = _extract_types_from_schedule_text(ocr_text)
                logger.info("  Page %d: regex found %d additional types", idx, len(regex_types))
                all_types.extend(regex_types)
            else:
                # Cloud Vision failed or empty page — fallback to vision LLM
                logger.info("  Page %d: Cloud Vision returned %d chars, falling back to vision LLM", idx, len(ocr_text))
                types = _extract_types_with_vision(pdf_path, idx, use_dual_model=use_dual_model)
                logger.info("  Page %d: vision returned %d types in %.1fs", idx, len(types), time.time() - t1)
                all_types.extend(types)

    # Clean up and deduplicate (with separator-normalized dedup)
    all_types = [_clean_type_code(t) for t in all_types]
    seen = set()
    fixture_types = []
    for t in all_types:
        t_upper = t.strip().upper()
        if not t_upper or t_upper in EXCLUDE_WORDS or t_upper in _SPEC_CODES:
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


def _extract_types_with_vision(pdf_path: str, page_index: int, use_dual_model: bool = False) -> list[str]:
    """Extract fixture types from rasterized schedule page.

    Strategy: Google Cloud Vision OCR (dedicated document OCR) extracts raw text,
    then LLM parses fixture type codes from the OCR text. This is far more accurate
    than vision LLM directly reading images — Cloud Vision reads text at pixel level.
    Falls back to Gemini Pro vision if Cloud Vision is unavailable.
    """
    from collections import Counter
    from app.config import GOOGLE_API_KEY

    image_bytes = render_page_to_image(pdf_path, page_index, dpi=300)
    logger.info("  Rendering page %d: %.1f KB at 300 DPI", page_index, len(image_bytes) / 1024)

    # --- Step 1: Google Cloud Vision OCR → raw text ---
    ocr_text = _cloud_vision_ocr(image_bytes, GOOGLE_API_KEY)

    if len(ocr_text) < 200:
        logger.warning("  Cloud Vision returned only %d chars, falling back to Gemini Pro", len(ocr_text))
        return _extract_types_with_gemini_pro(pdf_path, page_index)

    logger.info("  Cloud Vision OCR: %d chars extracted", len(ocr_text))

    # --- Step 2: LLM extracts fixture types from OCR text ---
    llm_types = extract_fixture_types_llm(ocr_text)
    logger.info("  LLM extracted %d types from OCR text", len(llm_types))

    # --- Step 3: Regex extraction from OCR text (deterministic supplement) ---
    regex_types = _extract_types_from_schedule_text(ocr_text)
    logger.info("  Regex extracted %d types from OCR text", len(regex_types))

    # --- Merge and dedup ---
    all_types = llm_types + regex_types
    all_types = [_clean_type_code(t) for t in all_types]

    seen = set()
    result = []
    for t in all_types:
        norm = _dedup_normalize(t.strip().upper())
        if norm and norm not in seen:
            seen.add(norm)
            result.append(t.strip())

    logger.info("  Schedule page %d: %d unique types (Cloud Vision OCR + LLM + regex)", page_index, len(result))
    return result


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


def _extract_types_with_gemini_pro(pdf_path: str, page_index: int) -> list[str]:
    """Fallback: Gemini Pro vision when Cloud Vision is unavailable."""
    from app.utils.llm_client import llm_vision_query_pro

    image_bytes = render_page_to_image(pdf_path, page_index, dpi=200)
    try:
        resp = llm_vision_query_pro(_VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, image_bytes)
        types = _parse_fixture_types_response(resp)
        return [_clean_type_code(t) for t in types if len(types) <= 60]
    except Exception as e:
        logger.warning("  Gemini Pro fallback failed: %s", str(e)[:100])
        return []




def _extract_types_from_schedule_text(text: str) -> list[str]:
    """Extract fixture type codes from schedule text using regex patterns.

    Looks for fixture codes at the start of lines or before catalog numbers (#).
    This is a deterministic supplement to LLM extraction.

    In engineering fixture schedules, type codes appear as:
      B1 #CLX-L48-4000LM-...  → B1
      GA1 #VCPG LED-V4-...     → GA1
      B1-EM #CLX-L48-...       → B1-EM
      LP1 EM  (description)    → LP1 EM
      LT-104.1  (description)  → LT-104.1
    """
    found = set()
    # Pattern 1: fixture code before catalog number (#xxx)
    # e.g., "B1 #CLX-L48-...", "GA #VCPG LED-..."
    catalog_re = re.compile(
        r'\b([A-Z]{1,2}[-.]?\d*[A-Z]?(?:\.\d{1,2})?(?:[-\s]?EM)?)\s+#',
    )
    for m in catalog_re.finditer(text):
        code = m.group(1).strip()
        if len(code) >= 2 and code.upper() not in EXCLUDE_WORDS and code.upper() not in _SPEC_CODES:
            found.add(code)

    # Pattern 2: fixture code before schedule keywords
    # e.g., "B2 STEP DIMMING", "U4 DIMMING DRIVER", "B3 FIXED OUTPUT"
    keyword_re = re.compile(
        r'\b([A-Z]{1,2}[-.]?\d+[A-Z]?(?:\.\d{1,2})?(?:[-\s]?EM)?)\s+'
        r'(?:DIMMING|FIXED|STEP|REMOTE|OUTPUT|DRIVER)',
    )
    for m in keyword_re.finditer(text):
        code = m.group(1).strip()
        if len(code) >= 2 and code.upper() not in EXCLUDE_WORDS:
            found.add(code)

    # Pattern 3: fixture code at start of line followed by text
    line_start_re = re.compile(
        r'(?:^|\n)\s*'
        r'([A-Z]{1,2}[-.]?\d+[A-Z]?(?:\.\d{1,2})?(?:[-\s]?EM)?)'
        r'(?:\s+[#(A-Z])',
        re.MULTILINE
    )
    for m in line_start_re.finditer(text):
        code = m.group(1).strip()
        if len(code) >= 2 and code.upper() not in EXCLUDE_WORDS:
            found.add(code)

    # Also look for compound types: AS1/AS2, SC1/SC3
    compound_re = re.compile(r'\b([A-Z]{1,2}\d+[A-Z]?/[A-Z]{1,2}\d+[A-Z]?)\b')
    for m in compound_re.finditer(text):
        found.add(m.group(1))

    # Also look for parenthesized types: BX(S), BX(D)
    paren_re = re.compile(r'\b([A-Z]{1,2}\([A-Z]+\))\b')
    for m in paren_re.finditer(text):
        found.add(m.group(1))

    # Also look for POLE variants: PH3-POLE
    pole_re = re.compile(r'\b([A-Z]{1,2}\d+[A-Z]?-POLE)\b')
    for m in pole_re.finditer(text):
        found.add(m.group(1))

    # Also look for size-embedded types: B1.8', B1.12'
    size_re = re.compile(r"\b([A-Z]{1,2}\d+\.\d+')['\s]")
    for m in size_re.finditer(text):
        found.add(m.group(1))

    return list(found)


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
