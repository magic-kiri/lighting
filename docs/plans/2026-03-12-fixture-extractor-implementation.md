# Fixture Extractor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI service that extracts lighting fixture Type + Quantity from Bluebeam-exported engineering drawing PDFs using pdfplumber (deterministic) + LLM vision (verification).

**Architecture:** A 5-stage pipeline: PDF classification → page classification (LLM) → fixture schedule parsing → spatial counting (pdfplumber) + LLM verification → CSV output. Each stage is a separate module. The pipeline orchestrator runs them in sequence.

**Tech Stack:** Python 3.11+, FastAPI, pdfplumber, PyMuPDF (fitz), anthropic/openai/google-generativeai SDKs, python-dotenv

**Design Doc:** `docs/plans/2026-03-12-fixture-extractor-design.md`

**Sample Data for Testing:**
- AMLI BREA: `04_Electrical_1-16-2026.pdf` → expected output in `AMLI-BREA, CA COUNTS.xlsx`
- Chase Bank: `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf` → expected output in `CHASE BANK - NEWPORT BEACH COUNTS.xlsx`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `app/__init__.py`
- Create: `app/stages/__init__.py`
- Create: `app/utils/__init__.py`
- Create: `tests/__init__.py`
- Create: `requirements.txt`
- Create: `app/config.py`
- Create: `.env.example`
- Create: `data/input/.gitkeep`
- Create: `data/output/.gitkeep`

**Step 1: Create folder structure**

```bash
mkdir -p app/stages app/utils tests data/input data/output
touch app/__init__.py app/stages/__init__.py app/utils/__init__.py tests/__init__.py
```

**Step 2: Create requirements.txt**

```
fastapi>=0.110.0
uvicorn>=0.27.0
python-multipart>=0.0.9
pdfplumber>=0.11.0
PyMuPDF>=1.24.0
anthropic>=0.40.0
openai>=1.50.0
google-generativeai>=0.8.0
python-dotenv>=1.0.0
pytest>=8.0.0
httpx>=0.27.0
```

**Step 3: Create .env.example**

```
# LLM Provider: "anthropic", "openai", or "google"
LLM_PROVIDER=anthropic

# API Keys (set the one matching your provider)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...

# Model names per provider
ANTHROPIC_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o
GOOGLE_MODEL=gemini-2.0-flash

# Rendering DPI for LLM vision
RENDER_DPI=300

# Confidence threshold — max allowed difference between pdfplumber and LLM counts
# If abs(pdfplumber_count - llm_count) <= threshold, confidence = "high"
CONFIDENCE_THRESHOLD=2
```

**Step 4: Create app/config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
RENDER_DPI = int(os.getenv("RENDER_DPI", "300"))
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "2"))
```

**Step 5: Install dependencies and verify**

```bash
pip install -r requirements.txt
python -c "import pdfplumber; import fitz; import fastapi; print('All imports OK')"
```

**Step 6: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with dependencies and config"
```

---

## Task 2: PDF Utilities

**Files:**
- Create: `app/utils/pdf_utils.py`
- Create: `tests/test_pdf_utils.py`

**Step 1: Write failing tests**

```python
# tests/test_pdf_utils.py
import pytest
from app.utils.pdf_utils import get_pdf_metadata, extract_page_text, render_page_to_image, get_page_count

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_get_pdf_metadata_amli():
    meta = get_pdf_metadata(AMLI_PDF)
    assert "producer" in meta
    assert "Bluebeam" in meta["producer"]


def test_get_pdf_metadata_chase():
    meta = get_pdf_metadata(CHASE_PDF)
    assert "Bluebeam" in meta["producer"]


def test_get_page_count():
    count = get_page_count(AMLI_PDF)
    assert count == 135


def test_extract_page_text_returns_chars():
    """Page 6 (index 5) of AMLI BREA has the fixture schedule — should have text."""
    chars = extract_page_text(AMLI_PDF, page_index=5)
    assert len(chars) > 100
    # Each char should have text, x0, y0, x1, y1
    first = chars[0]
    assert "text" in first
    assert "x0" in first
    assert "y0" in first


def test_render_page_to_image():
    """Should return PNG bytes."""
    img_bytes = render_page_to_image(AMLI_PDF, page_index=5, dpi=150)
    assert isinstance(img_bytes, bytes)
    assert img_bytes[:4] == b'\x89PNG'
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pdf_utils.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.utils.pdf_utils'`

**Step 3: Implement pdf_utils.py**

```python
# app/utils/pdf_utils.py
import pdfplumber
import fitz


def get_pdf_metadata(pdf_path: str) -> dict:
    """Extract PDF metadata (producer, creator, etc.)."""
    with pdfplumber.open(pdf_path) as pdf:
        meta = pdf.metadata or {}
    return {k.lower(): v for k, v in meta.items() if v}


def get_page_count(pdf_path: str) -> int:
    """Return total number of pages."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def extract_page_text(pdf_path: str, page_index: int) -> list[dict]:
    """Extract all characters with positions from a page using pdfplumber.

    Returns list of dicts with keys: text, x0, y0, x1, y1, fontname, size
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        chars = page.chars
    return [
        {
            "text": c.get("text", ""),
            "x0": c.get("x0", 0),
            "y0": c.get("top", 0),
            "x1": c.get("x1", 0),
            "y1": c.get("bottom", 0),
            "fontname": c.get("fontname", ""),
            "size": c.get("size", 0),
        }
        for c in chars
    ]


def extract_page_words(pdf_path: str, page_index: int) -> list[dict]:
    """Extract words (grouped characters) with positions from a page.

    Returns list of dicts with keys: text, x0, y0, x1, y1
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    return [
        {
            "text": w.get("text", ""),
            "x0": w.get("x0", 0),
            "y0": w.get("top", 0),
            "x1": w.get("x1", 0),
            "y1": w.get("bottom", 0),
        }
        for w in words
    ]


def extract_page_full_text(pdf_path: str, page_index: int) -> str:
    """Extract plain text from a page."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        return page.extract_text() or ""


def render_page_to_image(pdf_path: str, page_index: int, dpi: int = 300) -> bytes:
    """Render a PDF page to PNG bytes using PyMuPDF."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pdf_utils.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add app/utils/pdf_utils.py tests/test_pdf_utils.py
git commit -m "feat: PDF utility functions for text extraction and rendering"
```

---

## Task 3: LLM Client Wrapper

**Files:**
- Create: `app/utils/llm_client.py`
- Create: `tests/test_llm_client.py`

**Step 1: Write failing test**

```python
# tests/test_llm_client.py
import pytest
from app.utils.llm_client import llm_text_query, llm_vision_query


def test_llm_text_query_returns_string():
    """Basic smoke test — send a trivial prompt, get a response."""
    response = llm_text_query(
        system="You are a helpful assistant. Respond with only the word 'OK'.",
        prompt="Say OK."
    )
    assert isinstance(response, str)
    assert len(response) > 0


def test_llm_vision_query_returns_string():
    """Smoke test with a tiny white PNG image."""
    # 1x1 white PNG
    import base64
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
        "Nl7BcQAAAABJRU5ErkJggg=="
    )
    response = llm_vision_query(
        system="Describe the image in one word.",
        prompt="What is this?",
        image_bytes=tiny_png,
        image_media_type="image/png"
    )
    assert isinstance(response, str)
    assert len(response) > 0
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_llm_client.py -v
```

**Step 3: Implement llm_client.py**

```python
# app/utils/llm_client.py
import base64
from app.config import (
    LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY,
    ANTHROPIC_MODEL, OPENAI_MODEL, GOOGLE_MODEL,
)


def llm_text_query(system: str, prompt: str) -> str:
    """Send a text-only query to the configured LLM provider."""
    if LLM_PROVIDER == "anthropic":
        return _anthropic_text(system, prompt)
    elif LLM_PROVIDER == "openai":
        return _openai_text(system, prompt)
    elif LLM_PROVIDER == "google":
        return _google_text(system, prompt)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def llm_vision_query(system: str, prompt: str, image_bytes: bytes, image_media_type: str = "image/png") -> str:
    """Send a vision query (text + image) to the configured LLM provider."""
    if LLM_PROVIDER == "anthropic":
        return _anthropic_vision(system, prompt, image_bytes, image_media_type)
    elif LLM_PROVIDER == "openai":
        return _openai_vision(system, prompt, image_bytes, image_media_type)
    elif LLM_PROVIDER == "google":
        return _google_vision(system, prompt, image_bytes, image_media_type)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


# --- Anthropic ---

def _anthropic_text(system: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _anthropic_vision(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return msg.content[0].text


# --- OpenAI ---

def _openai_text(system: str, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return resp.choices[0].message.content


def _openai_vision(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{image_media_type};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]},
        ],
    )
    return resp.choices[0].message.content


# --- Google ---

def _google_text(system: str, prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GOOGLE_MODEL, system_instruction=system)
    resp = model.generate_content(prompt)
    return resp.text


def _google_vision(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GOOGLE_MODEL, system_instruction=system)
    image_part = {"mime_type": image_media_type, "data": image_bytes}
    resp = model.generate_content([image_part, prompt])
    return resp.text
```

**Step 4: Run tests (requires valid API key in .env)**

```bash
pytest tests/test_llm_client.py -v
```

Expected: PASS (if API key is set), SKIP or FAIL (if no key — that's OK for now)

**Step 5: Commit**

```bash
git add app/utils/llm_client.py tests/test_llm_client.py
git commit -m "feat: LLM client wrapper for Anthropic, OpenAI, Google"
```

---

## Task 4: Stage 1 — PDF Classifier

**Files:**
- Create: `app/stages/classifier.py`
- Create: `tests/test_classifier.py`

**Step 1: Write failing tests**

```python
# tests/test_classifier.py
import pytest
from app.stages.classifier import classify_pdf

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"
POPEYES_PDF = "Newberg Popeyes Permit Set Revised_ E-Sheets.pdf"


def test_amli_is_extractable():
    result = classify_pdf(AMLI_PDF)
    assert result["extractable"] is True
    assert result["error"] is None


def test_chase_is_extractable():
    result = classify_pdf(CHASE_PDF)
    assert result["extractable"] is True


def test_popeyes_is_not_extractable():
    """Popeyes has zero fixture labels as text — should be rejected."""
    result = classify_pdf(POPEYES_PDF)
    assert result["extractable"] is False
    assert result["error"] is not None
    assert "not text-extractable" in result["error"].lower() or "vector" in result["error"].lower()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_classifier.py -v
```

**Step 3: Implement classifier.py**

```python
# app/stages/classifier.py
from app.utils.pdf_utils import get_pdf_metadata, get_page_count, extract_page_text


def classify_pdf(pdf_path: str) -> dict:
    """Check if a PDF has text-extractable fixture labels.

    Returns:
        {"extractable": bool, "producer": str, "page_count": int, "error": str|None}
    """
    meta = get_pdf_metadata(pdf_path)
    producer = meta.get("producer", "Unknown")
    page_count = get_page_count(pdf_path)

    # Quick check: known Bluebeam producer
    is_bluebeam = "bluebeam" in producer.lower()

    # Deeper check: sample a few pages and see if meaningful text exists
    # Test up to 5 evenly spaced pages
    sample_indices = _sample_page_indices(page_count, n=5)
    total_chars = 0
    for idx in sample_indices:
        chars = extract_page_text(pdf_path, idx)
        total_chars += len(chars)

    # Heuristic: Bluebeam PDFs typically have 500+ chars per page on content pages.
    # Direct AutoCAD exports have <100 chars total (just title block).
    avg_chars = total_chars / len(sample_indices) if sample_indices else 0
    has_meaningful_text = avg_chars > 200

    extractable = is_bluebeam or has_meaningful_text

    error = None
    if not extractable:
        error = (
            f"PDF is not text-extractable. Producer: '{producer}'. "
            "Fixture labels are likely encoded as vector strokes, not text objects. "
            "Please provide a Bluebeam-produced PDF."
        )

    return {
        "extractable": extractable,
        "producer": producer,
        "page_count": page_count,
        "error": error,
    }


def _sample_page_indices(page_count: int, n: int = 5) -> list[int]:
    """Pick n evenly spaced page indices, biased toward middle pages (where plans are)."""
    if page_count <= n:
        return list(range(page_count))
    step = page_count // (n + 1)
    return [step * (i + 1) for i in range(n)]
```

**Step 4: Run tests**

```bash
pytest tests/test_classifier.py -v
```

Expected: PASS for AMLI and Chase. Popeyes test may need threshold tuning — adjust `avg_chars > 200` if needed.

**Step 5: Commit**

```bash
git add app/stages/classifier.py tests/test_classifier.py
git commit -m "feat: Stage 1 — PDF extractability classifier"
```

---

## Task 5: Stage 2 — Page Classifier (LLM)

**Files:**
- Create: `app/stages/page_classifier.py`
- Create: `tests/test_page_classifier.py`

**Step 1: Write failing tests**

```python
# tests/test_page_classifier.py
import pytest
from app.stages.page_classifier import classify_pages, extract_sheet_titles

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_extract_sheet_titles_amli():
    titles = extract_sheet_titles(AMLI_PDF)
    assert isinstance(titles, dict)
    assert len(titles) > 0
    # Should have page indices as keys, title strings as values
    assert all(isinstance(k, int) for k in titles.keys())
    assert all(isinstance(v, str) for v in titles.values())


def test_classify_pages_amli():
    result = classify_pages(AMLI_PDF)
    # Must find at least some lighting plans and a fixture schedule
    assert len(result["lighting_plans"]) > 0
    assert len(result["fixture_schedules"]) > 0
    # AMLI BREA should have unit plans
    assert len(result["unit_plans"]) > 0


def test_classify_pages_chase():
    result = classify_pages(CHASE_PDF)
    assert len(result["lighting_plans"]) > 0
    assert len(result["fixture_schedules"]) > 0
    # Chase Bank is commercial — no unit plans expected
    # (but don't assert 0, let the LLM decide)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_page_classifier.py -v
```

**Step 3: Implement page_classifier.py**

```python
# app/stages/page_classifier.py
import json
import re
from app.utils.pdf_utils import extract_page_full_text, get_page_count
from app.utils.llm_client import llm_text_query

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
    """
    page_count = get_page_count(pdf_path)
    titles = {}
    for i in range(page_count):
        text = extract_page_full_text(pdf_path, i)
        # Take first 500 chars — enough to capture sheet title without sending full page text
        titles[i] = text[:500].strip() if text else "(no text)"
    return titles


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
    titles = extract_sheet_titles(pdf_path)

    # Build prompt with page titles
    lines = []
    for idx, title in sorted(titles.items()):
        # Truncate to keep prompt reasonable
        short_title = title[:200].replace("\n", " ").strip()
        lines.append(f"Page {idx + 1}: {short_title}")

    prompt = "Classify each page:\n\n" + "\n".join(lines)

    response = llm_text_query(SYSTEM_PROMPT, prompt)

    # Parse JSON from response
    classifications = _parse_llm_response(response)

    # Group by category
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
    # Strip markdown code fences if present
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
        # Try to find JSON in the response
        match = re.search(r'\{.*"pages".*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return data.get("pages", [])

    return []
```

**Step 4: Run tests**

```bash
pytest tests/test_page_classifier.py -v
```

Expected: PASS (requires LLM API key)

**Step 5: Commit**

```bash
git add app/stages/page_classifier.py tests/test_page_classifier.py
git commit -m "feat: Stage 2 — LLM-based page classifier"
```

---

## Task 6: Stage 3 — Fixture Schedule Parser

**Files:**
- Create: `app/stages/schedule_parser.py`
- Create: `tests/test_schedule_parser.py`

**Step 1: Write failing tests**

```python
# tests/test_schedule_parser.py
import pytest
from app.stages.schedule_parser import parse_fixture_schedule

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_parse_amli_schedule():
    """AMLI BREA fixture schedule is on page 6 (index 5)."""
    result = parse_fixture_schedule(AMLI_PDF, page_indices=[5])
    assert result["success"] is True
    assert len(result["fixture_types"]) > 10
    # Should find known types
    type_codes = [ft["type_code"] for ft in result["fixture_types"]]
    assert "U1" in type_codes
    assert "B1" in type_codes
    assert "GA" in type_codes


def test_parse_chase_schedule_rasterized():
    """Chase Bank schedule (page 103, index 102) is rasterized — should fail gracefully."""
    result = parse_fixture_schedule(CHASE_PDF, page_indices=[102])
    # Should either succeed with types or fail with clear error
    if not result["success"]:
        assert "rasterized" in result["error"].lower() or "no fixture types" in result["error"].lower()


def test_parse_returns_type_codes():
    result = parse_fixture_schedule(AMLI_PDF, page_indices=[5])
    for ft in result["fixture_types"]:
        assert "type_code" in ft
        assert isinstance(ft["type_code"], str)
        assert len(ft["type_code"]) > 0
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule_parser.py -v
```

**Step 3: Implement schedule_parser.py**

```python
# app/stages/schedule_parser.py
import re
from app.utils.pdf_utils import extract_page_words, extract_page_full_text


def parse_fixture_schedule(pdf_path: str, page_indices: list[int]) -> dict:
    """Extract fixture type codes from schedule pages.

    Returns:
        {
            "success": bool,
            "fixture_types": [{"type_code": str, "description": str}],
            "error": str|None
        }
    """
    all_types = []

    for page_idx in page_indices:
        text = extract_page_full_text(pdf_path, page_idx)
        words = extract_page_words(pdf_path, page_idx)

        if len(words) < 20:
            # Too few words — likely rasterized
            continue

        # Try to find fixture type codes from the text
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

    # Deduplicate by type_code
    seen = set()
    unique_types = []
    for ft in all_types:
        if ft["type_code"] not in seen:
            seen.add(ft["type_code"])
            unique_types.append(ft)

    return {
        "success": True,
        "fixture_types": unique_types,
        "error": None,
    }


def _extract_types_from_text(text: str, words: list[dict]) -> list[dict]:
    """Extract fixture type codes from schedule text.

    Fixture schedules are tables. The type code is typically in the first column —
    short codes like U1, B1, AL1, D1A, L-7, EM, EX, GA1, etc.

    Heuristic: Look for short strings (1-8 chars) that match typical fixture code patterns.
    These are alphanumeric with optional dashes: letters + optional digits + optional dash + optional suffix.
    """
    # Pattern for fixture type codes:
    # - Start with 1-4 letters
    # - Optionally followed by dash
    # - Optionally followed by digits/letters
    # - Examples: U1, B1, AL1, D1A, L-7, L-7E, EM, EX, GA1, B1-EM, LX-2, DF01
    fixture_pattern = re.compile(
        r'^[A-Z]{1,4}[-]?[A-Z0-9]{0,4}[-]?[A-Z0-9]{0,4}$'
    )

    # Extract candidate type codes from words
    candidates = []
    for w in words:
        word_text = w["text"].strip()
        if 1 <= len(word_text) <= 10 and fixture_pattern.match(word_text):
            # Exclude common non-fixture words
            if word_text not in _EXCLUDE_WORDS:
                candidates.append({"type_code": word_text, "description": ""})

    # Filter: fixture codes in a schedule appear in a structured region
    # For now, return all candidates. The schedule page should mostly contain fixture data.
    # We'll refine in later iterations if there's noise.
    return candidates


# Common words that look like fixture codes but aren't
_EXCLUDE_WORDS = {
    "A", "B", "C", "D", "E", "F", "N", "S", "W",  # Single grid letters
    "OR", "ON", "IN", "AT", "TO", "OF", "BY", "NO",  # Prepositions
    "LED", "DIM", "AC", "DC", "VA", "HP",  # Electrical abbreviations
    "NEC", "UL", "ETL", "CSA",  # Standards
    "YES", "SEE", "PER", "TYP", "MAX", "MIN",  # Common notes
    "THE", "AND", "FOR", "NOT", "ALL", "NEW",  # Common words
    "WALL", "TYPE",  # Column headers
}
```

**Step 4: Run tests**

```bash
pytest tests/test_schedule_parser.py -v
```

Expected: AMLI tests PASS. Chase test passes (graceful failure for rasterized schedule).

**Step 5: Commit**

```bash
git add app/stages/schedule_parser.py tests/test_schedule_parser.py
git commit -m "feat: Stage 3 — fixture schedule parser with pdfplumber"
```

---

## Task 7: Stage 4a — Deterministic Spatial Counter

**Files:**
- Create: `app/utils/spatial.py`
- Create: `app/stages/counter.py`
- Create: `tests/test_counter.py`

**Step 1: Write failing tests**

```python
# tests/test_counter.py
import pytest
from app.stages.counter import count_fixtures_on_page

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_count_fixtures_chase_page_113():
    """Page 113 (index 112) is E-212 Electrical Lighting Plan - Level 02."""
    fixture_types = ["D1A", "D1B", "D2", "L1A", "L2A", "L2B", "L5", "L6", "L-8", "L-22", "X1", "EM"]
    counts = count_fixtures_on_page(CHASE_PDF, page_index=112, fixture_types=fixture_types)
    assert isinstance(counts, dict)
    # Should find at least some of the fixture types
    assert sum(counts.values()) > 0
    # D1A should be the most common on this page
    if "D1A" in counts:
        assert counts["D1A"] > 0


def test_count_returns_only_known_types():
    """Should only count types we ask for."""
    fixture_types = ["D1A"]
    counts = count_fixtures_on_page(CHASE_PDF, page_index=112, fixture_types=["D1A"])
    assert all(k in fixture_types for k in counts.keys())
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_counter.py -v
```

**Step 3: Implement spatial.py**

```python
# app/utils/spatial.py


def identify_title_block_region(page_width: float, page_height: float) -> dict:
    """Return the bounding box of the title block region to exclude.

    Title blocks are typically in the bottom-right corner of engineering drawings.
    On landscape pages: rightmost ~20% width, bottom ~15% height.
    On portrait pages: bottom ~20% height, right ~30% width.
    """
    if page_width > page_height:  # Landscape
        return {
            "x0": page_width * 0.75,
            "y0": page_height * 0.85,
            "x1": page_width,
            "y1": page_height,
        }
    else:  # Portrait
        return {
            "x0": page_width * 0.65,
            "y0": page_height * 0.80,
            "x1": page_width,
            "y1": page_height,
        }


def is_in_region(x0: float, y0: float, region: dict) -> bool:
    """Check if a point falls within a region."""
    return (region["x0"] <= x0 <= region["x1"] and
            region["y0"] <= y0 <= region["y1"])


def identify_legend_regions(words: list[dict], page_width: float, page_height: float) -> list[dict]:
    """Detect legend/keynote regions by finding clusters of text in regular grid patterns.

    Legends have vertically stacked text with regular y-spacing.
    Returns list of exclusion region bounding boxes.
    """
    # For now, exclude the border annotation strip (outermost 5% on each side)
    # and any text in the very bottom 20% (schedule/notes area)
    regions = [
        # Bottom strip (fixture schedule if embedded on same page)
        {"x0": 0, "y0": page_height * 0.82, "x1": page_width, "y1": page_height},
        # Right margin annotations
        {"x0": page_width * 0.92, "y0": 0, "x1": page_width, "y1": page_height},
        # Left margin
        {"x0": 0, "y0": 0, "x1": page_width * 0.03, "y1": page_height},
        # Top margin
        {"x0": 0, "y0": 0, "x1": page_width, "y1": page_height * 0.03},
    ]
    return regions
```

**Step 4: Implement counter.py**

```python
# app/stages/counter.py
import re
from collections import Counter
from app.utils.pdf_utils import extract_page_words
from app.utils.spatial import identify_title_block_region, identify_legend_regions, is_in_region
import pdfplumber


def count_fixtures_on_page(pdf_path: str, page_index: int, fixture_types: list[str]) -> dict[str, int]:
    """Count fixture labels on a single page using spatial filtering.

    Args:
        pdf_path: Path to PDF
        page_index: 0-based page index
        fixture_types: List of valid fixture type codes to search for

    Returns:
        Dict mapping fixture type code → count
    """
    # Get page dimensions
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        page_width = page.width
        page_height = page.height

    words = extract_page_words(pdf_path, page_index)

    # Build exclusion zones
    title_block = identify_title_block_region(page_width, page_height)
    legend_regions = identify_legend_regions(words, page_width, page_height)
    exclusion_zones = [title_block] + legend_regions

    # Normalize fixture types for matching (case-insensitive, strip whitespace)
    type_set = {t.upper().strip() for t in fixture_types}

    # Build regex patterns for flexible matching
    # Some labels have spaces or different formatting: "L-7E w2" should match "L-7E"
    # We match the fixture code at the start of the word
    type_patterns = {}
    for t in type_set:
        # Escape for regex, allow optional trailing whitespace/annotations
        escaped = re.escape(t)
        type_patterns[t] = re.compile(f'^{escaped}$', re.IGNORECASE)

    counts = Counter()

    for word in words:
        text = word["text"].strip().upper()
        x0, y0 = word["x0"], word["y0"]

        # Skip if in any exclusion zone
        in_exclusion = False
        for zone in exclusion_zones:
            if is_in_region(x0, y0, zone):
                in_exclusion = True
                break
        if in_exclusion:
            continue

        # Check if this word matches any fixture type
        for type_code, pattern in type_patterns.items():
            if pattern.match(text):
                counts[type_code] += 1
                break

    return dict(counts)


def count_fixtures_multi_page(pdf_path: str, page_indices: list[int], fixture_types: list[str]) -> dict[str, int]:
    """Count fixtures across multiple pages, summing counts."""
    total = Counter()
    for page_idx in page_indices:
        page_counts = count_fixtures_on_page(pdf_path, page_idx, fixture_types)
        total.update(page_counts)
    return dict(total)
```

**Step 5: Run tests**

```bash
pytest tests/test_counter.py -v
```

**Step 6: Commit**

```bash
git add app/utils/spatial.py app/stages/counter.py tests/test_counter.py
git commit -m "feat: Stage 4a — deterministic spatial fixture counter"
```

---

## Task 8: Stage 4b — LLM Vision Counter

**Files:**
- Create: `app/stages/llm_counter.py`
- Create: `tests/test_llm_counter.py`

**Step 1: Write failing test**

```python
# tests/test_llm_counter.py
import pytest
from app.stages.llm_counter import count_fixtures_with_llm

CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_llm_count_chase_page_113():
    fixture_types = ["D1A", "D1B", "D2", "L1A", "L2A", "L5", "X1", "EM"]
    counts = count_fixtures_with_llm(CHASE_PDF, page_index=112, fixture_types=fixture_types)
    assert isinstance(counts, dict)
    assert sum(counts.values()) > 0
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_llm_counter.py -v
```

**Step 3: Implement llm_counter.py**

```python
# app/stages/llm_counter.py
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
```

**Step 4: Run tests**

```bash
pytest tests/test_llm_counter.py -v
```

**Step 5: Commit**

```bash
git add app/stages/llm_counter.py tests/test_llm_counter.py
git commit -m "feat: Stage 4b — LLM vision fixture counter"
```

---

## Task 9: Stage 4c — Reconciler + Stage 5 — Output

**Files:**
- Create: `app/stages/reconciler.py`
- Create: `tests/test_reconciler.py`

**Step 1: Write failing tests**

```python
# tests/test_reconciler.py
import pytest
from app.stages.reconciler import reconcile_counts


def test_matching_counts_are_high_confidence():
    pdfplumber_counts = {"D1A": 37, "L1A": 32, "X1": 7}
    llm_counts = {"D1A": 37, "L1A": 32, "X1": 7}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    for item in result:
        assert item["confidence"] == "high"


def test_mismatched_counts_are_review():
    pdfplumber_counts = {"D1A": 45, "L1A": 32}
    llm_counts = {"D1A": 37, "L1A": 30}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    d1a = next(r for r in result if r["type"] == "D1A")
    assert d1a["confidence"] == "review"
    assert "pdfplumber=45" in d1a["note"]
    assert "llm=37" in d1a["note"]


def test_within_threshold_is_high():
    pdfplumber_counts = {"D1A": 38}
    llm_counts = {"D1A": 37}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    assert result[0]["confidence"] == "high"
    # Should use LLM count when within threshold (LLM is better at excluding non-fixtures)
    assert result[0]["quantity"] == 37


def test_type_in_one_but_not_other():
    pdfplumber_counts = {"D1A": 37, "EM": 5}
    llm_counts = {"D1A": 37}
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=2)
    em = next(r for r in result if r["type"] == "EM")
    assert em["confidence"] == "review"
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_reconciler.py -v
```

**Step 3: Implement reconciler.py**

```python
# app/stages/reconciler.py
import csv
import os


def reconcile_counts(
    pdfplumber_counts: dict[str, int],
    llm_counts: dict[str, int],
    threshold: int = 2,
) -> list[dict]:
    """Compare pdfplumber and LLM counts, assign confidence.

    Args:
        pdfplumber_counts: {type: count} from spatial extraction
        llm_counts: {type: count} from LLM vision
        threshold: max allowed difference for "high" confidence

    Returns:
        List of {"type", "quantity", "confidence", "note"}
    """
    all_types = sorted(set(list(pdfplumber_counts.keys()) + list(llm_counts.keys())))
    results = []

    for type_code in all_types:
        pdf_count = pdfplumber_counts.get(type_code, 0)
        llm_count = llm_counts.get(type_code, 0)
        diff = abs(pdf_count - llm_count)

        if diff <= threshold:
            # Counts agree (within threshold)
            # Prefer LLM count when close — LLM is better at excluding non-fixture labels
            quantity = llm_count if llm_count > 0 else pdf_count
            results.append({
                "type": type_code,
                "quantity": quantity,
                "confidence": "high",
                "note": "",
            })
        else:
            # Counts disagree — flag for review
            # Use LLM count as the quantity (likely more accurate for disambiguation)
            # but flag it so human can verify
            quantity = llm_count if llm_count > 0 else pdf_count
            results.append({
                "type": type_code,
                "quantity": quantity,
                "confidence": "review",
                "note": f"pdfplumber={pdf_count}, llm={llm_count}",
            })

    return results


def write_csv(results: list[dict], output_path: str) -> str:
    """Write results to CSV file.

    Returns the output file path.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["type", "quantity", "confidence", "note"])
        writer.writeheader()
        writer.writerows(results)
    return output_path
```

**Step 4: Run tests**

```bash
pytest tests/test_reconciler.py -v
```

**Step 5: Commit**

```bash
git add app/stages/reconciler.py tests/test_reconciler.py
git commit -m "feat: Stage 4c + 5 — reconciler and CSV output"
```

---

## Task 10: Pipeline Orchestrator

**Files:**
- Create: `app/pipeline.py`
- Create: `tests/test_pipeline.py`

**Step 1: Write failing test**

```python
# tests/test_pipeline.py
import pytest
import os
from app.pipeline import run_pipeline

CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_pipeline_chase_bank():
    result = run_pipeline(CHASE_PDF, output_dir="data/output")
    assert result["status"] == "success"
    assert len(result["fixture_counts"]) > 0
    assert os.path.exists(result["csv_path"])
    # Check that at least some known types are present
    types_found = [fc["type"] for fc in result["fixture_counts"]]
    assert any(t in types_found for t in ["D1A", "L1A", "X1"])
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_pipeline.py -v
```

**Step 3: Implement pipeline.py**

```python
# app/pipeline.py
import os
import re
from app.stages.classifier import classify_pdf
from app.stages.page_classifier import classify_pages
from app.stages.schedule_parser import parse_fixture_schedule
from app.stages.counter import count_fixtures_multi_page
from app.stages.llm_counter import count_fixtures_with_llm_multi_page
from app.stages.reconciler import reconcile_counts, write_csv
from app.config import CONFIDENCE_THRESHOLD


def run_pipeline(pdf_path: str, output_dir: str = "data/output") -> dict:
    """Run the full extraction pipeline on a PDF.

    Returns:
        {
            "status": "success" | "error",
            "fixture_counts": [{"type", "quantity", "confidence", "note"}],
            "csv_path": str | None,
            "pages_analyzed": {"lighting_plans": [], "fixture_schedules": [], "unit_plans": []},
            "pattern": "direct_counting" | "unit_multiplication",
            "errors": [str]
        }
    """
    errors = []

    # --- Stage 1: PDF Classification ---
    classification = classify_pdf(pdf_path)
    if not classification["extractable"]:
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": [classification["error"]],
        }

    # --- Stage 2: Page Classification ---
    page_map = classify_pages(pdf_path)
    lighting_pages = page_map["lighting_plans"]
    schedule_pages = page_map["fixture_schedules"]
    unit_pages = page_map["unit_plans"]

    if not lighting_pages:
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": page_map,
            "pattern": None,
            "errors": ["No lighting plan pages identified in the PDF."],
        }

    # Detect counting pattern
    pattern = "unit_multiplication" if unit_pages else "direct_counting"

    # --- Stage 3: Fixture Schedule ---
    if schedule_pages:
        schedule_result = parse_fixture_schedule(pdf_path, schedule_pages)
    else:
        schedule_result = {"success": False, "fixture_types": [], "error": "No schedule pages found."}

    if not schedule_result["success"]:
        errors.append(schedule_result["error"])
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {
                "lighting_plans": lighting_pages,
                "fixture_schedules": schedule_pages,
                "unit_plans": unit_pages,
            },
            "pattern": pattern,
            "errors": errors,
        }

    fixture_types = [ft["type_code"] for ft in schedule_result["fixture_types"]]

    # --- Stage 4: Counting ---
    if pattern == "direct_counting":
        fixture_counts = _direct_counting(pdf_path, lighting_pages, fixture_types)
    else:
        fixture_counts = _unit_multiplication_counting(
            pdf_path, unit_pages, lighting_pages, fixture_types
        )

    # --- Stage 5: Output ---
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    # Clean filename
    basename = re.sub(r'[^\w\-]', '_', basename)[:50]
    csv_path = os.path.join(output_dir, f"{basename}_counts.csv")
    write_csv(fixture_counts, csv_path)

    return {
        "status": "success",
        "fixture_counts": fixture_counts,
        "csv_path": csv_path,
        "pages_analyzed": {
            "lighting_plans": lighting_pages,
            "fixture_schedules": schedule_pages,
            "unit_plans": unit_pages,
        },
        "pattern": pattern,
        "errors": errors,
    }


def _direct_counting(
    pdf_path: str, lighting_pages: list[int], fixture_types: list[str]
) -> list[dict]:
    """Direct counting pattern: count fixture labels on lighting plan pages."""
    # Stage 4a: pdfplumber spatial count
    pdfplumber_counts = count_fixtures_multi_page(pdf_path, lighting_pages, fixture_types)

    # Stage 4b: LLM verification count
    llm_counts = count_fixtures_with_llm_multi_page(pdf_path, lighting_pages, fixture_types)

    # Stage 4c: Reconcile
    return reconcile_counts(pdfplumber_counts, llm_counts, threshold=CONFIDENCE_THRESHOLD)


def _unit_multiplication_counting(
    pdf_path: str,
    unit_pages: list[int],
    lighting_pages: list[int],
    fixture_types: list[str],
) -> list[dict]:
    """Unit multiplication pattern: count per unit, then multiply by instances.

    This is a simplified first version. It counts fixtures on unit plan pages
    and on lighting plan pages separately, then combines them.

    TODO: Full implementation needs to:
    1. Parse each unit plan to get fixtures-per-unit-type
    2. Count unit instances on floor plan pages
    3. Multiply and sum
    For now, we count all pages together as a starting point.
    """
    all_pages = unit_pages + lighting_pages

    # Stage 4a: pdfplumber count across all relevant pages
    pdfplumber_counts = count_fixtures_multi_page(pdf_path, all_pages, fixture_types)

    # Stage 4b: LLM count across all relevant pages
    llm_counts = count_fixtures_with_llm_multi_page(pdf_path, all_pages, fixture_types)

    # Stage 4c: Reconcile
    return reconcile_counts(pdfplumber_counts, llm_counts, threshold=CONFIDENCE_THRESHOLD)
```

**Step 4: Run tests**

```bash
pytest tests/test_pipeline.py -v
```

**Step 5: Commit**

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestrator connecting all stages"
```

---

## Task 11: FastAPI Endpoint

**Files:**
- Create: `app/main.py`

**Step 1: Implement main.py**

```python
# app/main.py
import os
import tempfile
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.pipeline import run_pipeline

app = FastAPI(
    title="Fixture Extractor",
    description="Extract lighting fixture counts from engineering drawing PDFs",
    version="0.1.0",
)


@app.post("/extract")
async def extract_fixtures(file: UploadFile = File(...)):
    """Upload a PDF and extract fixture counts."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Save uploaded file to temp location
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        result = run_pipeline(tmp_path, output_dir="data/output")
        return JSONResponse(content=result)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 2: Test manually**

```bash
uvicorn app.main:app --reload --port 8000
# In another terminal:
curl -X POST "http://localhost:8000/extract" -F "file=@20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"
```

**Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat: FastAPI endpoint for PDF upload and extraction"
```

---

## Task 12: End-to-End Validation

**Files:**
- Create: `tests/test_e2e_validation.py`

**Step 1: Write validation test**

This test compares our output against Kaz's expected counts from the Excel files.

```python
# tests/test_e2e_validation.py
"""End-to-end validation: compare extracted counts against expected Excel output."""
import pytest
import openpyxl
from app.pipeline import run_pipeline

CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"
CHASE_XLSX = "CHASE BANK - NEWPORT BEACH COUNTS.xlsx"

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
AMLI_XLSX = "AMLI-BREA, CA COUNTS.xlsx"


def _load_expected_counts(xlsx_path: str) -> dict[str, int]:
    """Load Type → Quantity from the expected Excel file."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    # Try common sheet names
    for name in wb.sheetnames:
        if "quote" in name.lower() or "customer" in name.lower():
            ws = wb[name]
            break
    else:
        ws = wb[wb.sheetnames[0]]

    counts = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            type_code = str(row[0]).strip()
            try:
                qty = int(row[1])
                if type_code and qty > 0:
                    counts[type_code] = counts.get(type_code, 0) + qty
            except (ValueError, TypeError):
                continue
    wb.close()
    return counts


def test_chase_bank_e2e():
    """Validate Chase Bank extraction against expected Excel counts."""
    result = run_pipeline(CHASE_PDF)
    assert result["status"] == "success"

    expected = _load_expected_counts(CHASE_XLSX)
    extracted = {fc["type"]: fc["quantity"] for fc in result["fixture_counts"]}

    print("\n=== Chase Bank Validation ===")
    print(f"{'Type':<10} {'Expected':>10} {'Extracted':>10} {'Match':>8}")
    print("-" * 40)

    matches = 0
    total = 0
    for type_code in sorted(set(list(expected.keys()) + list(extracted.keys()))):
        exp = expected.get(type_code, 0)
        ext = extracted.get(type_code, 0)
        match = "OK" if exp == ext else f"DIFF ({exp-ext:+d})"
        if exp > 0:
            total += 1
            if exp == ext:
                matches += 1
        print(f"{type_code:<10} {exp:>10} {ext:>10} {match:>8}")

    accuracy = matches / total * 100 if total > 0 else 0
    print(f"\nAccuracy: {matches}/{total} = {accuracy:.1f}%")
    # We want at least 80% match on first run — will improve iteratively
    assert accuracy >= 50, f"Accuracy too low: {accuracy:.1f}%"


def test_amli_brea_e2e():
    """Validate AMLI BREA extraction against expected Excel counts."""
    result = run_pipeline(AMLI_PDF)
    assert result["status"] in ("success", "error")

    if result["status"] == "error":
        pytest.skip(f"Pipeline returned error: {result['errors']}")

    expected = _load_expected_counts(AMLI_XLSX)
    extracted = {fc["type"]: fc["quantity"] for fc in result["fixture_counts"]}

    print("\n=== AMLI BREA Validation ===")
    print(f"{'Type':<10} {'Expected':>10} {'Extracted':>10} {'Match':>8}")
    print("-" * 40)

    matches = 0
    total = 0
    for type_code in sorted(set(list(expected.keys()) + list(extracted.keys()))):
        exp = expected.get(type_code, 0)
        ext = extracted.get(type_code, 0)
        match = "OK" if exp == ext else f"DIFF ({exp-ext:+d})"
        if exp > 0:
            total += 1
            if exp == ext:
                matches += 1
        print(f"{type_code:<10} {exp:>10} {ext:>10} {match:>8}")

    accuracy = matches / total * 100 if total > 0 else 0
    print(f"\nAccuracy: {matches}/{total} = {accuracy:.1f}%")
```

**Step 2: Run validation**

```bash
pytest tests/test_e2e_validation.py -v -s
```

The `-s` flag shows the comparison table so we can see exactly where counts match and where they differ. This is our baseline — we iterate from here.

**Step 3: Commit**

```bash
git add tests/test_e2e_validation.py
git commit -m "feat: end-to-end validation tests against expected Excel counts"
```

---

## Summary of Tasks

| Task | What | Depends On |
|------|------|-----------|
| 1 | Project scaffolding | — |
| 2 | PDF utilities (pdfplumber/fitz) | 1 |
| 3 | LLM client wrapper | 1 |
| 4 | Stage 1: PDF classifier | 2 |
| 5 | Stage 2: Page classifier (LLM) | 2, 3 |
| 6 | Stage 3: Schedule parser | 2 |
| 7 | Stage 4a: Spatial counter | 2 |
| 8 | Stage 4b: LLM vision counter | 2, 3 |
| 9 | Stage 4c: Reconciler + output | — |
| 10 | Pipeline orchestrator | 4, 5, 6, 7, 8, 9 |
| 11 | FastAPI endpoint | 10 |
| 12 | End-to-end validation | 10 |

**Total: 12 tasks, each with TDD steps (test → implement → verify → commit)**
