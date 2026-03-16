# Approach A: Vision-First on Classified Pages — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mixed pdfplumber+vision fixture type discovery with uniform GPT-4.1 vision on all classified pages, achieving 95%+ recall and precision.

**Architecture:** Classify pages using existing sheet index parser (fast, deterministic). Render each classified page to an image. Send each to GPT-4.1 vision with a fixture-type-extraction prompt. Aggregate types across pages — types on 2+ pages are high confidence, types on 1 schedule page are kept. Simple pattern filter for noise.

**Tech Stack:** Python, FastAPI, fitz (PyMuPDF) for rendering, OpenAI GPT-4.1 (vision), ThreadPoolExecutor for parallelism

**Spec:** `docs/superpowers/specs/2026-03-16-vision-first-classified-pages-design.md`

**Current .env config:**
```
LLM_PROVIDER=openai
VISION_PROVIDER=google
OPENAI_API_KEY=sk-svcacct-...
OPENAI_MODEL=gpt-4.1
GOOGLE_API_KEY=AIzaSy...
GOOGLE_MODEL=gemini-2.5-flash
RENDER_DPI=300
```

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/stages/vision_scanner.py` | **Create** | Renders pages to images, calls GPT-4.1 vision, parses JSON responses |
| `app/pipeline.py` | **Modify** | New `_discover_types_v2()` that uses vision_scanner instead of pdfplumber+schedule_parser |
| `app/main.py` | No change | Calls `run_fixture_discovery()` which calls `_discover_types()` internally |
| `app/stages/classifier.py` | No change | PDF extractability check |
| `app/stages/page_classifier.py` | No change | Page detection / sheet index parsing |
| `app/utils/pdf_utils.py` | No change | `render_page_to_image()`, `parse_sheet_index()` |
| `app/utils/llm_client.py` | No change | `_openai_vision()` already exists |
| `app/config.py` | No change | `OPENAI_API_KEY`, `OPENAI_MODEL` already configured |
| `verify_fixtures.py` | No change | Verification script |

---

## Chunk 1: Create Vision Scanner Module

### Task 1: Create `app/stages/vision_scanner.py`

**Files:**
- Create: `app/stages/vision_scanner.py`

- [ ] **Step 1: Create the vision scanner module**

```python
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
List ALL lighting fixture type codes visible on this page.

Fixture type codes are short identifiers like: D1A, L-2, DF1, SS9, LT-104.1, BX(S), PH3-POLE
Include EM (emergency) variants: D1A-EM, LP1 EM, L500-EM
Include compound types: AS1/AS2, SC1/SC3
Include size variants that are part of the code: B1.8', B1.12'

Rules:
- Return ONLY fixture type codes — not descriptions, catalog numbers, manufacturers, or wattages
- Do NOT invent or guess types not clearly visible in THIS image
- If no fixture types are visible, return an empty list

Return valid JSON: {"fixture_types": ["TYPE1", "TYPE2", ...]}"""

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
        result.append(t)
    return result


def _normalize(code: str) -> str:
    """Normalize for dedup: remove dashes, spaces, underscores, quotes. Keep dots and slashes."""
    return ''.join(ch for ch in code.strip() if ch not in ('-', ' ', '_', '"', "'", '`')).upper()
```

- [ ] **Step 2: Verify the module imports correctly**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python -c "from app.stages.vision_scanner import scan_pages_for_types, aggregate_types; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/stages/vision_scanner.py
git commit -m "feat: add vision scanner module for GPT-4.1 page scanning"
```

---

## Chunk 2: Wire Vision Scanner into Pipeline

### Task 2: Add `_discover_types_v2()` to pipeline.py

**Files:**
- Modify: `app/pipeline.py`

- [ ] **Step 1: Add the new discovery function**

Add this function to `app/pipeline.py` (after the existing `_discover_types` function, before `run_pipeline`):

```python
def _discover_types_v2(
    pdf_path: str,
    lighting_pages: list[int],
    schedule_pages: list[int],
    unit_pages: list[int] | None = None,
) -> tuple[list[str], dict | None]:
    """Discover fixture types using GPT-4.1 vision on all classified pages.

    Strategy: render each classified page to an image, send to GPT-4.1,
    aggregate types across pages with frequency-based filtering.
    """
    from app.stages.vision_scanner import scan_pages_for_types, aggregate_types

    logger.info("Discovering fixture types (vision-first approach)...")
    t0 = time.time()
    unit_pages = unit_pages or []

    # Combine all classified pages
    all_pages = sorted(set(schedule_pages + lighting_pages + unit_pages))

    # Add high-density electrical plan pages
    additional = _find_all_fixture_pages(pdf_path, all_pages, min_codes=15)
    if additional:
        logger.info("  Found %d additional electrical pages", len(additional))
        all_pages = sorted(set(all_pages + additional))

    logger.info("  Scanning %d pages with vision: %s", len(all_pages), all_pages)

    # Vision scan all pages in parallel
    page_types = scan_pages_for_types(pdf_path, all_pages, dpi=200, max_workers=4)

    # Aggregate with frequency-based filtering
    all_types = aggregate_types(page_types, schedule_pages)

    if not all_types:
        logger.warning("  No fixture types found")
        return [], {
            "status": "error",
            "fixture_types": [],
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": ["No fixture types found via vision scanning."],
        }

    logger.info("Vision discovery: %d types in %.1fs", len(all_types), time.time() - t0)
    return all_types, None
```

- [ ] **Step 2: Switch `run_fixture_discovery` to use `_discover_types_v2`**

In `run_fixture_discovery()`, change the `_discover_types` call to `_discover_types_v2`:

```python
# BEFORE:
fixture_types, error = _discover_types(
    pdf_path, lighting_pages, schedule_pages, unit_pages
)

# AFTER:
fixture_types, error = _discover_types_v2(
    pdf_path, lighting_pages, schedule_pages, unit_pages
)
```

Note: Keep the old `_discover_types` function — it's still used by `run_pipeline` for counting.

- [ ] **Step 3: Verify server starts**

```bash
kill $(lsof -ti :8000) 2>/dev/null; sleep 2
uvicorn app.main:app --port 8000 &>/tmp/uvicorn.log &
sleep 5 && curl -s http://localhost:8000/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add app/pipeline.py
git commit -m "feat: wire vision-first discovery into /fixtures endpoint"
```

---

## Chunk 3: Verification

### Task 3: Run verification on both datasets

- [ ] **Step 1: Test Chase Bank**

```bash
PYTHON="/opt/homebrew/Cellar/python@3.11/3.11.11/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python"
$PYTHON -c "
import json, urllib.request, time, re

def normalize(code):
    code = code.strip()
    code = re.sub(r'\s*\([^)]*\)\s*$', '', code)
    code = re.sub(r\"\"\"\s+\d+'[\d\\\"]*$\"\"\", '', code)
    return ''.join(ch for ch in code if ch not in ('-', ' ', '_', '\"', \"'\", '\`')).upper()

CHASE = ['D1A','D1A-EM','D1B','D2','DF1','DF3','DF4','DF5','DF6','DF7',
         'L-2','L-2-EM','L-7','L-7-EM','L-22','L-411','L-412',
         'L1A','L1A-EM','L2A','L2B','L3','L4','L5','L6',
         'L500','L500-EM','L8','L8EM','X1']

url = 'http://localhost:8000/fixtures'
data = json.dumps({'file_path': '20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf'}).encode()
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
t0 = time.time()
with urllib.request.urlopen(req, timeout=600) as resp:
    result = json.loads(resp.read())
elapsed = time.time()-t0
returned = sorted(result.get('fixture_types',[]))
print(f'Chase Bank: {elapsed:.0f}s, {len(returned)} types')
expected_norm = {normalize(t): t for t in CHASE}
returned_norm = {normalize(t): t for t in returned}
matched = set(expected_norm.keys()) & set(returned_norm.keys())
missing = set(expected_norm.keys()) - matched
fps = set(returned_norm.keys()) - matched
print(f'Recall: {len(matched)/len(CHASE)*100:.1f}%  Precision: {len(matched)/len(returned_norm)*100:.1f}%')
print(f'Missing: {sorted(expected_norm[n] for n in missing)}')
print(f'FP: {sorted(returned_norm[n] for n in fps)}')
"
```

- [ ] **Step 2: Test AMLI BREA**

Same script with AMLI data (use timeout=1800 for the larger PDF).

- [ ] **Step 3: If recall < 95%, iterate**

Options:
- Increase DPI to 300 for schedule pages
- Add a second GPT-4.1 pass on schedule pages with different prompt
- Lower the frequency threshold (allow 1-page non-schedule types if they match fixture patterns)

- [ ] **Step 4: If precision < 95%, iterate**

Options:
- Add more entries to `_EXCLUDE` and `_PANEL_PREFIXES`
- Increase frequency threshold to 3+ pages
- Add apartment number pattern filter (single-letter + 3-digit)

- [ ] **Step 5: Update baseline in `docs/fixture-type-verification.md`**

- [ ] **Step 6: Commit final results**

```bash
git add -A
git commit -m "feat: vision-first fixture discovery — Approach A"
```
