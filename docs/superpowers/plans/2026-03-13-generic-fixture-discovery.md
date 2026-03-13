# Generic Fixture Type Discovery — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded-regex fixture type discovery with a generic 4-step pipeline (Sheet Index → Schedule Extraction → LLM Type Extraction → Cross-Validation) that works on any engineering drawing PDF.

**Architecture:** Parse sheet index deterministically with fitz to find schedule/lighting pages → extract schedule text with pdfplumber (or LLM vision for rasterized pages) → send schedule text to LLM for type code extraction → cross-validate against floor plan words. Falls back to existing LLM page classification when no sheet index is found.

**Tech Stack:** Python 3.11+, FastAPI, pdfplumber, PyMuPDF (fitz), LLM via `app/utils/llm_client.py` (anthropic/openai/google)

**Spec:** `docs/superpowers/specs/2026-03-13-generic-fixture-discovery-design.md`
**Verification:** `docs/fixture-type-verification.md`

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `app/config.py` | Config constants | Add `SCHEDULE_TEXT_THRESHOLD`, `PDFPLUMBER_PAGE_TIMEOUT` |
| `app/utils/pdf_utils.py` | PDF I/O helpers | Add `parse_sheet_index()`, `extract_pages_text_batch()`, `extract_pages_words_batch()` |
| `app/stages/schedule_parser.py` | Schedule → fixture types | Rewrite: LLM-based type extraction replacing regex |
| `app/pipeline.py` | Pipeline orchestrator | Replace `_detect_pages()` + `_discover_types()` with 4-step discovery |
| `tests/test_pdf_utils.py` | PDF util tests | Add tests for `parse_sheet_index()` and batch functions |
| `tests/test_schedule_parser.py` | Schedule parser tests | Rewrite for LLM-based extraction with mocks |
| `tests/test_fixture_discovery.py` | Discovery integration tests | New: end-to-end mocked tests for the 4-step flow |
| `tests/test_pipeline.py` | Pipeline integration test | Update imports/assertions for new discovery flow |
| `tests/test_e2e_validation.py` | E2E validation | Update to validate fixture discovery against ground-truth CSVs |

---

## Chunk 1: Foundation — Config and PDF Utils

### Task 1: Add config constants

**Files:**
- Modify: `app/config.py:1-14`

- [ ] **Step 1: Write the failing test**

```python
# No test needed — config constants are trivially correct.
# Verify by import.
```

- [ ] **Step 2: Add the constants**

Add to `app/config.py` after `CONFIDENCE_THRESHOLD`:

```python
SCHEDULE_TEXT_THRESHOLD = int(os.getenv("SCHEDULE_TEXT_THRESHOLD", "1500"))
PDFPLUMBER_PAGE_TIMEOUT = int(os.getenv("PDFPLUMBER_PAGE_TIMEOUT", "60"))
```

- [ ] **Step 3: Verify import works**

Run: `python3.11 -c "from app.config import SCHEDULE_TEXT_THRESHOLD, PDFPLUMBER_PAGE_TIMEOUT; print(SCHEDULE_TEXT_THRESHOLD, PDFPLUMBER_PAGE_TIMEOUT)"`
Expected: `1500 60`

- [ ] **Step 4: Commit**

```bash
git add app/config.py
git commit -m "feat: add SCHEDULE_TEXT_THRESHOLD and PDFPLUMBER_PAGE_TIMEOUT config"
```

---

### Task 2: Add `parse_sheet_index()` to pdf_utils

**Files:**
- Modify: `app/utils/pdf_utils.py`
- Test: `tests/test_pdf_utils.py`

This function scans the PDF for a sheet index page, parses sheet entries, classifies them by description, and maps sheet numbers to 0-indexed page indices.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pdf_utils.py`:

```python
from app.utils.pdf_utils import parse_sheet_index


def test_parse_sheet_index_chase():
    """Chase Bank has a sheet index. Should find schedule and lighting pages."""
    result = parse_sheet_index(CHASE_PDF)
    assert "schedule_pages" in result
    assert "lighting_pages" in result
    assert "sheet_map" in result
    # Chase Bank has lighting schedule pages
    assert len(result["schedule_pages"]) > 0
    assert len(result["lighting_pages"]) > 0
    # All page indices should be non-negative integers
    for p in result["schedule_pages"] + result["lighting_pages"]:
        assert isinstance(p, int)
        assert p >= 0


def test_parse_sheet_index_amli():
    """AMLI BREA has a sheet index. Should find schedule and lighting pages."""
    result = parse_sheet_index(AMLI_PDF)
    assert len(result["schedule_pages"]) > 0
    assert len(result["lighting_pages"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_pdf_utils.py::test_parse_sheet_index_chase tests/test_pdf_utils.py::test_parse_sheet_index_amli -v`
Expected: FAIL with `ImportError: cannot import name 'parse_sheet_index'`

- [ ] **Step 3: Implement `parse_sheet_index()`**

Add to `app/utils/pdf_utils.py`:

```python
def parse_sheet_index(pdf_path: str) -> dict:
    """Parse the sheet index from an engineering drawing PDF.

    Finds the sheet index page (table of contents), extracts sheet entries,
    classifies them by description, and maps sheet numbers to 0-indexed page indices.

    Returns:
        {
            "schedule_pages": [int],   # 0-indexed pages containing fixture schedules
            "lighting_pages": [int],   # 0-indexed pages containing lighting plans
            "unit_pages": [int],       # 0-indexed pages containing unit plans
            "sheet_map": {str: int},   # sheet_number -> 0-indexed page index
        }
    """
    doc = fitz.open(pdf_path)
    page_count = doc.page_count

    # Step 1: Find the index page
    index_page_idx = _find_index_page(doc, page_count)
    if index_page_idx is None:
        doc.close()
        logger.info("Sheet index: no index page found")
        return {"schedule_pages": [], "lighting_pages": [], "unit_pages": [], "sheet_map": {}}

    logger.info("Sheet index: found index page at page %d", index_page_idx)

    # Step 2: Parse sheet entries from the index page
    index_text = doc[index_page_idx].get_text()
    entries = _parse_sheet_entries(index_text)
    logger.info("Sheet index: parsed %d entries", len(entries))

    # Step 3: Classify entries by description
    schedule_sheets = []
    lighting_sheets = []
    unit_sheets = []
    for sheet_num, description in entries:
        desc_upper = description.upper()
        has_lighting = any(w in desc_upper for w in ("LIGHTING", "LUMINAIRE", "FIXTURE"))
        has_schedule = "SCHEDULE" in desc_upper
        has_plan = "PLAN" in desc_upper
        has_unit = "UNIT" in desc_upper
        has_electrical = "ELECTRICAL" in desc_upper

        if has_lighting and has_schedule:
            schedule_sheets.append(sheet_num)
        elif has_lighting and has_plan:
            lighting_sheets.append(sheet_num)
        elif has_unit and (has_plan or has_electrical):
            unit_sheets.append(sheet_num)

    logger.info(
        "Sheet index: classified — schedule=%s, lighting=%s, unit=%s",
        schedule_sheets, lighting_sheets, unit_sheets,
    )

    # Step 4: Map sheet numbers to page indices
    # Build a lookup of all page text for sheet number matching
    all_sheets = set(schedule_sheets + lighting_sheets + unit_sheets)
    sheet_map = _map_sheets_to_pages(doc, all_sheets, page_count)
    doc.close()

    logger.info("Sheet index: mapped %d/%d sheets to pages", len(sheet_map), len(all_sheets))

    return {
        "schedule_pages": sorted(sheet_map[s] for s in schedule_sheets if s in sheet_map),
        "lighting_pages": sorted(sheet_map[s] for s in lighting_sheets if s in sheet_map),
        "unit_pages": sorted(sheet_map[s] for s in unit_sheets if s in sheet_map),
        "sheet_map": sheet_map,
    }


def _find_index_page(doc, page_count: int) -> int | None:
    """Find the sheet index page by scanning for keywords."""
    keywords = ("SHEET INDEX", "DRAWING INDEX", "SHEET LIST", "TABLE OF CONTENTS")

    # Check first 10 pages and any text-heavy pages
    candidates = list(range(min(10, page_count)))
    for i in range(page_count):
        if i not in candidates:
            text = doc[i].get_text()
            if len(text) > 10000:
                candidates.append(i)

    for i in candidates:
        text = doc[i].get_text().upper()
        if any(kw in text for kw in keywords):
            return i
    return None


_SHEET_NUM_RE = re.compile(r'^([A-Z]{1,2}[-.]?\d[\d.]*(?:\.\d+)*)', re.MULTILINE)
_SHEET_RANGE_RE = re.compile(r'^([A-Z]{1,2}[-.]?\d[\d.]*)-(\d+)\s', re.MULTILINE)


def _parse_sheet_entries(text: str) -> list[tuple[str, str]]:
    """Parse (sheet_number, description) pairs from index page text."""
    entries = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        # Try to match a sheet number at the start of the line
        m = _SHEET_NUM_RE.match(line)
        if m:
            sheet_num = m.group(1)
            # Description is the rest of the line after the sheet number
            rest = line[m.end():].strip()
            # Sometimes description is on the same line separated by spaces/tabs
            # Sometimes it's just the sheet number and description follows
            if rest:
                entries.append((sheet_num, rest))
            elif i + 1 < len(lines):
                # Description might be on the next line
                next_line = lines[i + 1].strip()
                if next_line and not _SHEET_NUM_RE.match(next_line):
                    entries.append((sheet_num, next_line))

        # Check for ranges like E0.04.1-3
        rm = _SHEET_RANGE_RE.match(line)
        if rm:
            base = rm.group(1)
            end_num = int(rm.group(2))
            # Extract the last number from base to determine start
            parts = base.rsplit('.', 1)
            if len(parts) == 2:
                prefix = parts[0]
                start_num = int(parts[1])
                rest = line[rm.end():].strip()
                desc = rest if rest else ""
                for n in range(start_num, end_num + 1):
                    expanded = f"{prefix}.{n}"
                    if expanded != sheet_num:  # avoid duplicate with the base
                        entries.append((expanded, desc))

    return entries


def _map_sheets_to_pages(doc, sheet_numbers: set, page_count: int) -> dict:
    """Map sheet numbers to 0-indexed page indices.

    Looks for sheet numbers in the title block area (last portion of page text).
    Prefers pages where the sheet number appears most prominently.
    """
    sheet_map = {}
    if not sheet_numbers:
        return sheet_map

    for i in range(page_count):
        text = doc[i].get_text()
        if not text:
            continue
        # Check the title block area — typically the last 300 chars
        title_block = text[-300:] if len(text) > 300 else text
        for sn in sheet_numbers:
            if sn in sheet_map:
                continue
            if sn in title_block:
                sheet_map[sn] = i
                logger.debug("Sheet %s → page %d (title block match)", sn, i)

    # Second pass: for any unmapped sheets, check full page text
    unmapped = sheet_numbers - set(sheet_map.keys())
    if unmapped:
        for i in range(page_count):
            text = doc[i].get_text()
            for sn in list(unmapped):
                if sn in text:
                    sheet_map[sn] = i
                    unmapped.discard(sn)
                    logger.debug("Sheet %s → page %d (full text match)", sn, i)
            if not unmapped:
                break

    return sheet_map
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_pdf_utils.py::test_parse_sheet_index_chase tests/test_pdf_utils.py::test_parse_sheet_index_amli -v`
Expected: PASS

**Important:** If tests fail, inspect the actual PDF structure:
1. Print the index page text to understand the format
2. Adjust `_parse_sheet_entries()` regex to match
3. Check which pages the sheet numbers map to

- [ ] **Step 5: Commit**

```bash
git add app/utils/pdf_utils.py tests/test_pdf_utils.py
git commit -m "feat: add parse_sheet_index() for deterministic schedule page discovery"
```

---

### Task 3: Add batch PDF extraction helpers

**Files:**
- Modify: `app/utils/pdf_utils.py`
- Test: `tests/test_pdf_utils.py`

These functions open the PDF once and extract text/words from multiple pages — avoiding the per-page PDF open overhead.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pdf_utils.py`:

```python
from app.utils.pdf_utils import extract_pages_text_batch, extract_pages_words_batch


def test_extract_pages_text_batch():
    """Batch extraction should return text for each requested page."""
    result = extract_pages_text_batch(AMLI_PDF, [0, 5])
    assert len(result) == 2
    assert 0 in result and 5 in result
    assert len(result[5]) > 100  # Schedule page has lots of text


def test_extract_pages_words_batch():
    """Batch word extraction should return word lists for each page."""
    result = extract_pages_words_batch(AMLI_PDF, [0, 5])
    assert len(result) == 2
    assert len(result[5]) > 10
    assert "text" in result[5][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_pdf_utils.py::test_extract_pages_text_batch tests/test_pdf_utils.py::test_extract_pages_words_batch -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement batch functions**

Add to `app/utils/pdf_utils.py`:

```python
def extract_pages_text_batch(pdf_path: str, page_indices: list[int]) -> dict[int, str]:
    """Extract full text from multiple pages, opening PDF once.
    Returns {page_index: text}.
    """
    result = {}
    with pdfplumber.open(pdf_path) as pdf:
        for idx in page_indices:
            if 0 <= idx < len(pdf.pages):
                result[idx] = pdf.pages[idx].extract_text() or ""
    return result


def extract_pages_words_batch(pdf_path: str, page_indices: list[int]) -> dict[int, list[dict]]:
    """Extract words from multiple pages, opening PDF once.
    Returns {page_index: [word_dicts]}.
    """
    result = {}
    with pdfplumber.open(pdf_path) as pdf:
        for idx in page_indices:
            if 0 <= idx < len(pdf.pages):
                words = pdf.pages[idx].extract_words(keep_blank_chars=False, use_text_flow=False)
                result[idx] = [
                    {
                        "text": w.get("text", ""),
                        "x0": w.get("x0", 0),
                        "y0": w.get("top", 0),
                        "x1": w.get("x1", 0),
                        "y1": w.get("bottom", 0),
                    }
                    for w in words
                ]
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_pdf_utils.py::test_extract_pages_text_batch tests/test_pdf_utils.py::test_extract_pages_words_batch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/pdf_utils.py tests/test_pdf_utils.py
git commit -m "feat: add batch PDF text/word extraction helpers"
```

---

## Chunk 2: LLM-Based Schedule Parser

### Task 4: Rewrite `schedule_parser.py` for LLM-based type extraction

**Files:**
- Modify: `app/stages/schedule_parser.py`
- Test: `tests/test_schedule_parser.py`

This is the core change. The schedule parser will:
1. Extract text from schedule pages (pdfplumber or LLM vision for rasterized)
2. Send the text to LLM to extract fixture type codes
3. Return the structured list

- [ ] **Step 1: Write the failing test with mocked LLM**

Rewrite `tests/test_schedule_parser.py`:

```python
import json
import pytest
from unittest.mock import patch
from app.stages.schedule_parser import parse_fixture_schedule, extract_fixture_types_llm

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


class TestExtractFixtureTypesLLM:
    """Tests for the LLM-based fixture type extraction."""

    def test_extracts_types_from_schedule_text(self):
        """Given schedule text, LLM should return fixture type codes."""
        mock_response = json.dumps({
            "fixture_types": ["D1A", "D1B", "D2", "DF1", "L-22", "X1"]
        })
        schedule_text = "TYPE  DESCRIPTION\nD1A   6\" Downlight\nD1B   4\" Downlight"

        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            types = extract_fixture_types_llm(schedule_text)
            assert types == ["D1A", "D1B", "D2", "DF1", "L-22", "X1"]

    def test_handles_markdown_wrapped_json(self):
        """LLM sometimes wraps JSON in markdown code blocks."""
        mock_response = '```json\n{"fixture_types": ["AL1", "BH1", "SS9"]}\n```'
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            types = extract_fixture_types_llm("schedule text")
            assert types == ["AL1", "BH1", "SS9"]

    def test_handles_empty_response(self):
        """Empty or malformed LLM response should return empty list."""
        with patch("app.stages.schedule_parser.llm_text_query", return_value="sorry"):
            types = extract_fixture_types_llm("schedule text")
            assert types == []

    def test_handles_compound_and_em_types(self):
        """Should preserve compound types (AS1/AS2) and EM variants."""
        mock_response = json.dumps({
            "fixture_types": ["AS1", "AS1/AS2", "LP1 EM", "D1A-EM", "B1.8'"]
        })
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            types = extract_fixture_types_llm("schedule text")
            assert "AS1/AS2" in types
            assert "LP1 EM" in types
            assert "D1A-EM" in types
            assert "B1.8'" in types


class TestParseFixtureSchedule:
    """Integration tests for the full schedule parsing flow."""

    def test_text_extractable_schedule(self):
        """AMLI BREA schedule page 5 has extractable text — should use pdfplumber + LLM."""
        mock_response = json.dumps({
            "fixture_types": ["AL1", "AS1", "B1", "BH1", "U1", "SS9"]
        })
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            result = parse_fixture_schedule(AMLI_PDF, [5])
            assert result["success"] is True
            assert len(result["fixture_types"]) > 0
            type_codes = [ft["type_code"] for ft in result["fixture_types"]]
            assert "AL1" in type_codes

    def test_rasterized_schedule_uses_vision(self):
        """Chase Bank schedule page 102 is rasterized — should fall back to LLM vision."""
        # Mock both text query (for type extraction) and vision query (for OCR)
        vision_response = "TYPE  DESCRIPTION\nD1A   Downlight\nL-22  Linear"
        llm_response = json.dumps({"fixture_types": ["D1A", "L-22"]})

        with patch("app.stages.schedule_parser.llm_vision_query", return_value=vision_response):
            with patch("app.stages.schedule_parser.llm_text_query", return_value=llm_response):
                result = parse_fixture_schedule(CHASE_PDF, [102])
                assert result["success"] is True
                type_codes = [ft["type_code"] for ft in result["fixture_types"]]
                assert "D1A" in type_codes

    def test_returns_structured_output(self):
        """Output should have correct structure."""
        mock_response = json.dumps({"fixture_types": ["X1"]})
        with patch("app.stages.schedule_parser.llm_text_query", return_value=mock_response):
            result = parse_fixture_schedule(AMLI_PDF, [5])
            assert "success" in result
            assert "fixture_types" in result
            assert "error" in result
            for ft in result["fixture_types"]:
                assert "type_code" in ft
                assert isinstance(ft["type_code"], str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_schedule_parser.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_fixture_types_llm'`

- [ ] **Step 3: Implement the new schedule_parser.py**

Rewrite `app/stages/schedule_parser.py`:

```python
import json
import logging
import re
import time
from app.config import SCHEDULE_TEXT_THRESHOLD, PDFPLUMBER_PAGE_TIMEOUT
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
    "You are an expert at reading engineering drawing tables."
)

_VISION_OCR_PROMPT = (
    "Read this lighting fixture schedule table. "
    "Return all text you can see, preserving the table structure."
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
    "SPEC", "REF", "QTY", "DERA", "DERA1",
}


def parse_fixture_schedule(pdf_path: str, page_indices: list[int]) -> dict:
    """Extract fixture type codes from schedule pages using LLM.

    Steps:
    1. Extract text from each schedule page (pdfplumber or LLM vision)
    2. Combine text and send to LLM for type code extraction

    Returns:
        {
            "success": bool,
            "fixture_types": [{"type_code": str}],
            "error": str | None,
        }
    """
    logger.info("Schedule parser: extracting text from %d pages", len(page_indices))
    t0 = time.time()

    # Step 1: Extract text from schedule pages
    combined_text = _extract_schedule_text(pdf_path, page_indices)
    logger.info(
        "Schedule parser: extracted %d chars in %.1fs",
        len(combined_text), time.time() - t0,
    )

    if not combined_text.strip():
        return {
            "success": False,
            "fixture_types": [],
            "error": (
                f"No text extracted from schedule pages {[i + 1 for i in page_indices]}. "
                "The schedule may be empty or unreadable."
            ),
        }

    # Step 2: LLM extracts fixture type codes
    t1 = time.time()
    fixture_types = extract_fixture_types_llm(combined_text)
    logger.info(
        "Schedule parser: LLM extracted %d types in %.1fs",
        len(fixture_types), time.time() - t1,
    )

    if not fixture_types:
        return {
            "success": False,
            "fixture_types": [],
            "error": "LLM could not extract any fixture types from the schedule text.",
        }

    return {
        "success": True,
        "fixture_types": [{"type_code": t} for t in fixture_types],
        "error": None,
    }


def _extract_schedule_text(pdf_path: str, page_indices: list[int]) -> str:
    """Extract text from schedule pages, falling back to LLM vision for rasterized pages."""
    # Try pdfplumber batch extraction first
    page_texts = extract_pages_text_batch(pdf_path, page_indices)

    parts = []
    for idx in page_indices:
        text = page_texts.get(idx, "")
        if len(text) >= SCHEDULE_TEXT_THRESHOLD:
            logger.info("  Page %d: %d chars (text-extractable)", idx, len(text))
            parts.append(f"--- Page {idx + 1} ---\n{text}")
        else:
            logger.info("  Page %d: %d chars (below threshold %d, trying LLM vision)",
                        idx, len(text), SCHEDULE_TEXT_THRESHOLD)
            vision_text = _extract_page_with_vision(pdf_path, idx)
            if vision_text:
                parts.append(f"--- Page {idx + 1} (vision) ---\n{vision_text}")
            else:
                logger.warning("  Page %d: LLM vision also returned no text", idx)

    return "\n\n".join(parts)


def _extract_page_with_vision(pdf_path: str, page_index: int) -> str:
    """Render a page and use LLM vision to read its text."""
    try:
        image_bytes = render_page_to_image(pdf_path, page_index, dpi=300)
        response = llm_vision_query(_VISION_OCR_SYSTEM, _VISION_OCR_PROMPT, image_bytes)
        return response.strip()
    except Exception as e:
        logger.warning("Vision extraction failed for page %d: %s", page_index, e)
        return ""


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

    logger.warning("Could not parse fixture types from LLM response: %s", text[:200])
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_schedule_parser.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/stages/schedule_parser.py tests/test_schedule_parser.py
git commit -m "feat: rewrite schedule_parser to use LLM for fixture type extraction"
```

---

## Chunk 3: Pipeline Integration — 4-Step Discovery

### Task 5: Replace `_detect_pages()` and `_discover_types()` in pipeline.py

**Files:**
- Modify: `app/pipeline.py`

This replaces the hardcoded regex discovery with the new 4-step flow:
1. Parse sheet index → find schedule + lighting pages
2. Extract schedule text (pdfplumber or LLM vision)
3. LLM extracts fixture types from schedule text
4. Cross-validate against floor plan words

- [ ] **Step 1: Write a unit test for cross-validation logic**

Create `tests/test_fixture_discovery.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from app.pipeline import _cross_validate_types


def test_cross_validate_finds_floor_plan_only_types():
    """Types on floor plan but not in schedule should be flagged."""
    schedule_types = ["D1A", "D1B", "L-22"]
    floor_plan_words = ["D1A", "D1B", "D2", "L-22", "L-7", "WALL", "DOOR"]

    result = _cross_validate_types(schedule_types, floor_plan_words)
    assert "D1A" in result
    assert "D1B" in result
    assert "L-22" in result
    # D2 shares 'D' prefix with D1A — should be flagged as floor_plan_only candidate
    assert "D2" in result
    # WALL and DOOR should NOT be in results (excluded or no matching prefix)
    assert "WALL" not in result
    assert "DOOR" not in result


def test_cross_validate_empty_floor_plan():
    """If no floor plan words, should return schedule types unchanged."""
    schedule_types = ["AL1", "BH1", "SS9"]
    result = _cross_validate_types(schedule_types, [])
    assert result == ["AL1", "BH1", "SS9"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_fixture_discovery.py -v`
Expected: FAIL with `ImportError: cannot import name '_cross_validate_types'`

- [ ] **Step 3: Implement the new pipeline discovery functions**

Replace the relevant functions in `app/pipeline.py`. The key changes:

1. Remove `_FIXTURE_TYPE_RE` regex
2. Remove `_discover_fixture_types_from_pages()`
3. Replace `_detect_pages()` with version that tries sheet index first
4. Replace `_discover_types()` with 4-step discovery
5. Add `_cross_validate_types()` for Step 4

Updated `app/pipeline.py` — replace the imports, regex, and discovery functions:

```python
import logging
import os
import re
import time
from collections import Counter
from app.stages.classifier import classify_pdf
from app.stages.page_classifier import classify_pages, detect_lighting_pages
from app.stages.schedule_parser import parse_fixture_schedule, EXCLUDE_WORDS
from app.stages.counter import count_fixtures_multi_page, normalize_fixture_code
from app.stages.llm_counter import count_fixtures_with_llm_multi_page
from app.stages.reconciler import reconcile_counts, write_csv
from app.config import CONFIDENCE_THRESHOLD
from app.utils.pdf_utils import (
    extract_page_words,
    parse_sheet_index,
    extract_pages_words_batch,
)

logger = logging.getLogger(__name__)
```

**Note:** `_EXCLUDE_WORDS` is imported from `schedule_parser.py` as `EXCLUDE_WORDS` (renamed from `_EXCLUDE_WORDS` to make it a public export). Update `schedule_parser.py` to rename `_EXCLUDE_WORDS` → `EXCLUDE_WORDS` so it can be shared.

Replace `_detect_pages()`:

```python
def _detect_pages(pdf_path: str) -> tuple[dict, dict | None]:
    """Detect lighting, schedule, and unit pages.

    Strategy (3-tier fallback):
    1. Try parse_sheet_index() for deterministic detection (fast, reliable).
    2. If no sheet index → try detect_lighting_pages() (fast regex scan via fitz).
    3. If neither works → fall back to full LLM page classification.

    Returns (page_result, error_or_None).
    """
    logger.info("Detecting pages...")

    # Tier 1: Try sheet index parsing
    t0 = time.time()
    index_result = parse_sheet_index(pdf_path)
    schedule_pages = index_result["schedule_pages"]
    lighting_pages = index_result["lighting_pages"]
    unit_pages = index_result["unit_pages"]

    if schedule_pages or lighting_pages:
        logger.info(
            "Page detection: Sheet index parsed in %.1fs — schedule=%s, lighting=%s, unit=%s",
            time.time() - t0, schedule_pages, lighting_pages, unit_pages,
        )
    else:
        logger.info("Page detection: No sheet index found, trying deterministic detection...")

    # Tier 2: If sheet index didn't find lighting pages, try fast regex detection
    if not lighting_pages:
        t0 = time.time()
        lighting_pages = detect_lighting_pages(pdf_path)
        if lighting_pages:
            logger.info(
                "Page detection: Deterministic detection in %.1fs — %d lighting pages: %s",
                time.time() - t0, len(lighting_pages), lighting_pages,
            )

    # Tier 3: If still no lighting pages, fall back to full LLM classification
    if not lighting_pages:
        logger.info("Page detection: No pages found deterministically, falling back to LLM...")
        t0 = time.time()
        page_map = classify_pages(pdf_path)
        lighting_pages = page_map["lighting_plans"]
        if not schedule_pages:
            schedule_pages = page_map["fixture_schedules"]
        unit_pages = page_map["unit_plans"]
        logger.info(
            "Page detection: LLM done in %.1fs — lighting=%d, schedule=%d, unit=%d",
            time.time() - t0, len(lighting_pages), len(schedule_pages), len(unit_pages),
        )

    if not lighting_pages:
        logger.warning("PIPELINE ABORT: No lighting plan pages found")
        return {}, {
            "status": "error",
            "fixture_types": [],
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": ["No lighting plan pages identified in the PDF."],
        }

    return {
        "lighting_plans": lighting_pages,
        "fixture_schedules": schedule_pages,
        "unit_plans": unit_pages,
    }, None
```

Replace `_discover_types()`:

```python
def _discover_types(
    pdf_path: str, lighting_pages: list[int], schedule_pages: list[int]
) -> tuple[list[str], dict | None]:
    """Discover fixture types using the 4-step pipeline.

    Steps:
    1. Schedule pages already identified by _detect_pages()
    2. Extract schedule content (pdfplumber or LLM vision) — handled by schedule_parser
    3. LLM extracts fixture types from schedule text — handled by schedule_parser
    4. Cross-validate against floor plan words

    Returns (fixture_types, error_or_None).
    """
    logger.info("Discovering fixture types...")
    t0 = time.time()
    fixture_types = []

    # Steps 2-3: Parse fixture schedule (text extraction + LLM type extraction)
    if schedule_pages:
        logger.info("  Parsing schedule from pages (0-indexed): %s", schedule_pages)
        schedule_result = parse_fixture_schedule(pdf_path, schedule_pages)
        if schedule_result["success"]:
            fixture_types = [ft["type_code"] for ft in schedule_result["fixture_types"]]
            logger.info("  Found %d types from schedule: %s", len(fixture_types), fixture_types[:20])
        else:
            logger.warning("  Schedule parse failed: %s", schedule_result["error"])

    # Fallback: if no schedule types, discover from floor plan words
    if not fixture_types:
        logger.info("  No schedule types found — falling back to floor plan discovery...")
        floor_words = _extract_floor_plan_words(pdf_path, lighting_pages[:3])
        # Use any short uppercase word that looks like a fixture code
        seen = set()
        for word in floor_words:
            if word not in EXCLUDE_WORDS and re.match(r'^[A-Z]+[-]?\d', word):
                if word not in seen:
                    fixture_types.append(word)
                    seen.add(word)
        if fixture_types:
            logger.info("  Discovered %d types from floor plans: %s", len(fixture_types), fixture_types[:20])

    if not fixture_types:
        logger.warning("  No fixture types found anywhere")
        return [], {
            "status": "error",
            "fixture_types": [],
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": ["No fixture types found in schedule or floor plan pages."],
        }

    # Step 4: Cross-validate against floor plan words
    logger.info("  Cross-validating against %d lighting plan pages...", len(lighting_pages))
    t1 = time.time()
    floor_plan_words = _extract_floor_plan_words(pdf_path, lighting_pages[:3])
    fixture_types = _cross_validate_types(fixture_types, floor_plan_words)
    logger.info("  Cross-validation done in %.1fs — %d final types", time.time() - t1, len(fixture_types))

    logger.info("Type discovery: Done in %.1fs — %d fixture types", time.time() - t0, len(fixture_types))
    return fixture_types, None


def _extract_floor_plan_words(pdf_path: str, page_indices: list[int]) -> list[str]:
    """Extract short uppercase words from floor plan pages for cross-validation."""
    if not page_indices:
        return []
    words_by_page = extract_pages_words_batch(pdf_path, page_indices)
    all_words = []
    for idx in page_indices:
        for w in words_by_page.get(idx, []):
            text = w["text"].strip().upper()
            if 2 <= len(text) <= 10:
                all_words.append(text)
    return all_words


def _cross_validate_types(
    schedule_types: list[str], floor_plan_words: list[str]
) -> list[str]:
    """Cross-validate schedule types against floor plan words.

    Checks which schedule types appear on floor plans.
    Also detects potential missed types that share a prefix with known schedule types.

    Returns combined list of types (schedule types + floor-plan-only candidates).
    """
    if not floor_plan_words:
        return schedule_types

    # Build prefix set from schedule types
    prefixes = set()
    for t in schedule_types:
        # Extract letter prefix (everything before the first digit or special char)
        m = re.match(r'^([A-Z]+)', t.upper())
        if m:
            prefixes.add(m.group(1))

    # Find floor plan words that match schedule type prefixes
    schedule_set = {t.upper() for t in schedule_types}
    candidates = set()
    word_counts = Counter(floor_plan_words)

    for word, count in word_counts.items():
        if word in schedule_set:
            continue  # Already known
        if word in EXCLUDE_WORDS:
            continue
        # Check if word shares a prefix with any schedule type
        m = re.match(r'^([A-Z]+)', word)
        if m and m.group(1) in prefixes:
            # Must look like a fixture code: letters followed by digits/special chars
            if re.match(r'^[A-Z]+[-]?\d', word) or re.match(r'^[A-Z]+\(', word):
                candidates.add(word)

    if candidates:
        logger.info("  Cross-validation: %d floor-plan-only candidates: %s",
                     len(candidates), sorted(candidates))

    # Combine: schedule types first, then floor-plan-only candidates
    result = list(schedule_types)
    for c in sorted(candidates):
        if c not in schedule_set:
            result.append(c)

    return result
```

Remove `_FIXTURE_TYPE_RE` and `_discover_fixture_types_from_pages()` — they are no longer used.

**Note on `PDFPLUMBER_PAGE_TIMEOUT`:** The timeout is imported in config but timeout enforcement is deferred to Task 7 (iteration). If pdfplumber hangs during verification (Task 6), add a `concurrent.futures.ThreadPoolExecutor` wrapper around `extract_pages_text_batch()` with `PDFPLUMBER_PAGE_TIMEOUT` as the timeout.

- [ ] **Step 4: Run the unit test**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_fixture_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests to check for regressions**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_main.py tests/test_schedule_parser.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/pipeline.py tests/test_fixture_discovery.py
git commit -m "feat: replace hardcoded regex with 4-step generic fixture discovery pipeline"
```

---

## Chunk 4: Verification and Iteration

### Task 6: Start the server and run verification

**Files:**
- Reference: `docs/fixture-type-verification.md`

This is the critical checkpoint. Run the API against both test PDFs and compare to ground truth. **If results are poor, stop and report findings — do not push through.**

- [ ] **Step 1: Start the server**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && uvicorn app.main:app --port 8000 &`

- [ ] **Step 2: Test Chase Bank**

```bash
curl -s -X POST http://localhost:8000/fixtures \
  -H "Content-Type: application/json" \
  -d '{"file_path": "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"}' \
  | python3 -m json.tool
```

Compare returned `fixture_types` against the 30 expected types from `docs/fixture-type-verification.md`.

- [ ] **Step 3: Test AMLI BREA**

```bash
curl -s -X POST http://localhost:8000/fixtures \
  -H "Content-Type: application/json" \
  -d '{"file_path": "04_Electrical_1-16-2026.pdf"}' \
  | python3 -m json.tool
```

Compare returned `fixture_types` against the 83 expected types.

- [ ] **Step 4: Compute metrics**

For each dataset, compute:
- Missing types (expected but not returned)
- False positives (returned but not expected)
- Recall = matched / total_expected
- Precision = matched / total_returned

When comparing, normalize by stripping parenthesized size suffixes: `L1A (4')` → `L1A`, but keep `B1.8'` as-is.

- [ ] **Step 5: Decision point**

| If... | Then... |
|-------|---------|
| Both datasets ≥90% recall, ≥90% precision | Proceed to Task 7 (refine) |
| One dataset <90% recall | Stop. Report which types are missing and why. Investigate: Was the schedule page found? Was the text extracted? Did the LLM miss types? Propose plan update. |
| Many false positives | Investigate: Are they from cross-validation? From LLM hallucination? Tighten the prompt or cross-validation logic. |

**User's instruction:** "After implementation, if you find that we are not getting good result because of the architectural issue, then let me know and update the implementation plan according to it."

- [ ] **Step 6: Update baseline in docs/fixture-type-verification.md**

After verification, fill in the Baseline Results table with actual numbers.

---

### Task 7: Iterate on accuracy (if needed)

This task is conditional — only execute if Task 6 reveals issues.

Common fixes by failure type:

| Failure | Fix |
|---------|-----|
| Schedule page not found by sheet index | Debug `_parse_sheet_entries()` regex — print the actual index page text |
| Rasterized page not detected | Adjust `SCHEDULE_TEXT_THRESHOLD` in config |
| LLM misses types from schedule text | Refine the `_EXTRACT_TYPES_PROMPT` — add examples, be more specific |
| LLM hallucinates types | Add a post-filter: only keep types that appear in the schedule text |
| Cross-validation adds noise | Tighten prefix matching or remove cross-validation if schedule extraction is reliable enough |
| pdfplumber timeout | The `PDFPLUMBER_PAGE_TIMEOUT` fallback to vision kicks in automatically |

- [ ] **Step 1: Identify the root cause from Task 6 metrics**
- [ ] **Step 2: Apply the targeted fix**
- [ ] **Step 3: Re-run verification (repeat Task 6 steps 2-4)**
- [ ] **Step 4: Commit fix**

---

### Task 8: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Per the design spec: "CLAUDE.md must be updated to reflect these changes after implementation."

- [ ] **Step 1: Update CLAUDE.md**

Changes to make:
1. Remove "LLM is verification only" statement — LLM is now used for interpretation in fixture type discovery
2. Remove "Rasterized fixture schedules are rejected" — they are now handled via LLM vision
3. Update Stage 3 description to reflect LLM-based extraction
4. Add note about sheet index parsing in Stage 2

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md to reflect LLM-based fixture type discovery"
```

---

### Task 9: Update test_pipeline.py and test_e2e_validation.py

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_e2e_validation.py`

Per the spec, these test files need updating to verify the new discovery flow.

- [ ] **Step 1: Read current test files**

Read `tests/test_pipeline.py` and `tests/test_e2e_validation.py` to understand current assertions.

- [ ] **Step 2: Update test_pipeline.py**

Ensure the integration test still works with the new discovery flow. The existing test calls `run_pipeline()` which now uses the 4-step discovery internally. Update any hardcoded fixture type assertions if they relied on the old regex-based discovery.

- [ ] **Step 3: Update test_e2e_validation.py**

Add a fixture discovery validation test that calls `run_fixture_discovery()` and compares the returned `fixture_types` against the ground-truth CSVs, following the comparison logic in `docs/fixture-type-verification.md`.

- [ ] **Step 4: Run updated tests**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/test_pipeline.py tests/test_e2e_validation.py -v`
Note: These tests require API keys and the actual PDF files.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline.py tests/test_e2e_validation.py
git commit -m "test: update pipeline and e2e tests for new fixture discovery flow"
```

---

### Task 10: Final verification and commit

- [ ] **Step 1: Run all deterministic tests**

Run: `cd /Users/magic-kiri/Desktop/Codes/lighting && python3.11 -m pytest tests/ -v --ignore=tests/test_pipeline.py --ignore=tests/test_e2e_validation.py --ignore=tests/test_llm_client.py --ignore=tests/test_page_classifier.py`

All tests should pass.

- [ ] **Step 2: Run both verification checks one final time**

Verify Chase Bank: 30/30 types, 100% recall, 100% precision
Verify AMLI BREA: 83/83 types, 100% recall, 100% precision

- [ ] **Step 3: Final commit if any remaining changes**

Stage only the specific files that were changed (avoid `git add -A` to prevent accidentally including debug artifacts):

```bash
git add app/ tests/ docs/ CLAUDE.md
git commit -m "feat: generic fixture type discovery — complete implementation"
```
