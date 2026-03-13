# Generic Fixture Type Discovery — Design Spec

**Date**: 2026-03-13
**Status**: Approved
**Scope**: Replace the hardcoded-regex fixture type discovery in `POST /fixtures` with a generic, multi-source approach that works on any engineering drawing PDF.

## Problem

The current `_FIXTURE_TYPE_RE` in `pipeline.py` hardcodes known fixture prefixes (D, L, DF, X, B, U). This fails on new projects with different naming conventions. AMLI BREA uses 25+ prefixes (AL, AS, BH, BX, DP, FS, GA, GH, GL, LP, LR, LS, LT, PH, RA, RD, RW, SC, SR, SS, WR, WS, XA, XK) — almost none match. Chase Bank is missing 17 of 30 expected types.

Additionally, the deterministic page detector bypasses LLM page classification when it finds lighting pages, which means fixture schedule pages are never identified for Chase Bank.

## Policy Change from Prior Constraints

CLAUDE.md previously stated: "Rasterized fixture schedules are rejected (not OCR'd)" and "LLM is verification only." This design intentionally changes that policy:

- **LLM is now used for interpretation**, not just verification. The fixture schedule is a structured table — LLM excels at extracting type codes from tabular text. This is more reliable than regex guessing.
- **Rasterized schedules are now handled via LLM vision** on the specific schedule pages (2-5 pages, not the full PDF). This unlocks Chase Bank which was previously unsolvable.

CLAUDE.md must be updated to reflect these changes after implementation.

## Design

### Principle

Deterministic tools extract data. LLM interprets it. Never send raw PDFs to LLM. Extract structured text first, then let LLM make intelligent decisions on that text.

### Architecture: 4-Step Pipeline

```
PDF
 │
 ├─ Step 1: Parse Sheet Index (fitz, ~2s)
 │   → Extract sheet-number-to-title mapping from index page
 │   → Identify schedule pages and lighting plan pages
 │   → Map sheet numbers to 0-indexed page indices
 │
 ├─ Step 2: Extract Schedule Content (pdfplumber or LLM vision, ~3-10s)
 │   → If text-rich (>SCHEDULE_TEXT_THRESHOLD chars): pdfplumber extracts text
 │   → If rasterized (<threshold): render page images → LLM vision reads table
 │
 ├─ Step 3: LLM Extracts Fixture Types (text LLM, ~2-5s)
 │   → Send schedule text to LLM: "Extract all fixture type codes from this schedule"
 │   → LLM returns structured list of type codes
 │   → Handles any naming convention, no regex needed
 │
 └─ Step 4: Cross-Validate Against Floor Plans (pdfplumber, ~3-6s)
     → Extract words from 2-3 lighting plan pages
     → Check which schedule types appear on floor plans
     → Flag floor-plan codes not in schedule (potential missed types)
```

Total time: ~10-20s per PDF.
LLM cost: ~$0.01-0.05 (text-only path), ~$0.10-0.30 (vision fallback for rasterized schedules).

### Step 1: Parse Sheet Index

**Input**: PDF path.
**Output**: `{schedule_pages: [int], lighting_pages: [int], sheet_map: {sheet_number: page_index}}`.

Engineering drawing PDFs contain a sheet index (table of contents) that maps sheet numbers to descriptions. Both sample PDFs have this:

- Chase Bank (page 99): `E-005 → LIGHTING SCHEDULE`
- AMLI BREA (page 0): `E0.04 → LIGHTING FIXTURE SCHEDULE`, `E0.04.1-3 → LIGHTING DESIGN FIXTURE SCHEDULE`

**Algorithm**:

1. **Find the index page**: Use fitz to scan all pages for text matching any of: `SHEET INDEX`, `DRAWING INDEX`, `SHEET LIST`, `TABLE OF CONTENTS`. Check first 10 pages and any page with >10,000 chars (index pages are text-heavy). Stop at first match.

2. **Parse sheet entries**: Extract pairs of `(sheet_number, description)` from the index page text. Sheet numbers follow patterns like `E-005`, `E0.04`, `E0.04.1`. Descriptions follow on the same or next line. Use a regex to detect sheet number patterns: `^[A-Z]{1,2}[-.]?\d[\d.]*`.

3. **Classify sheets by description**:
   - Schedule: description contains both a lighting-related word (`LIGHTING`, `LUMINAIRE`, `FIXTURE`) AND `SCHEDULE`.
   - Lighting plan: description contains `LIGHTING` AND `PLAN`.
   - Unit plan: description contains `UNIT` AND (`PLAN` OR `ELECTRICAL`).

4. **Map sheet numbers to page indices**: For each identified sheet number, scan all pages using fitz to find which page contains that sheet number in its text. To disambiguate (sheet numbers appear in cross-references too):
   - Prefer pages where the sheet number appears in the title block area (bottom-right quadrant, typically last 200 chars of page text).
   - If multiple pages match, pick the one where the sheet number appears most prominently (fewest total chars on the page = more likely a drawing page vs. a spec page with many references).
   - For sequential sheet numbers (E0.04, E0.04.1, E0.04.2), expect sequential page indices. If a match breaks the sequence, it's likely a cross-reference, not the actual page.

5. **Handle ranges**: If the index lists `E0.04.1-3`, expand to `E0.04.1`, `E0.04.2`, `E0.04.3` and map each individually.

**Fallback**: If no sheet index found, use the existing LLM page classification (`classify_pages()`). This is a single text LLM call sending page titles — cheap and already implemented.

**Failure mode**: If a sheet number from the index cannot be located in any page, log a warning and skip it. If zero schedule pages are found after the full scan, fall back to LLM page classification.

### Step 2: Extract Schedule Content

**Input**: Schedule page indices from Step 1.
**Output**: Raw text content from schedule pages.

For each schedule page:
1. Use pdfplumber to extract text (open PDF once, read all schedule pages sequentially).
2. If page has >`SCHEDULE_TEXT_THRESHOLD` chars → text-extractable, use pdfplumber output.
3. If page has <`SCHEDULE_TEXT_THRESHOLD` chars → likely rasterized (Chase Bank page 103: 946 chars of title block only). Render page as image via fitz and send to LLM vision with prompt: "Read this lighting fixture schedule table. Return all text you can see, preserving the table structure."

**Threshold**: `SCHEDULE_TEXT_THRESHOLD` defaults to 1500 chars, configured in `app/config.py`. This is distinct from the PDF-level extractability threshold (2000 chars in `classify_pdf_fast`) because schedule pages have less title block text than typical drawing pages. Chase Bank's rasterized schedule page has 946 chars; AMLI's text schedule has 13,280 chars. The 1500 threshold cleanly separates these cases.

**Timeout**: `PDFPLUMBER_PAGE_TIMEOUT` defaults to 60s, configured in `app/config.py`. If exceeded, fall back to LLM vision for that page.

**pdfplumber optimization**: Open PDF once, extract all needed pages in sequence. Current code reopens per page (adds ~1.4s overhead each time).

**Token limits**: If combined schedule text exceeds 15,000 words (~20K tokens), split into multiple LLM calls by page groups. In practice, schedule pages are 1-5 pages with 1,000-13,000 chars each — well within single-call limits.

### Step 3: LLM Extracts Fixture Types

**Input**: Combined text from all schedule pages (Step 2 output).
**Output**: List of unique fixture type codes.

This is the core improvement. Instead of regex pattern matching, send the schedule text to an LLM with a structured prompt:

```
System: You are an expert at reading lighting fixture schedules from engineering drawings.

User: Below is text extracted from a lighting fixture schedule in an engineering drawing PDF.
Extract ALL unique fixture type codes from this schedule.

Rules:
- Type codes are short identifiers like D1A, L-22, DF01, SS9, BX(S), LT-104.1
- Include EM (emergency) variants as separate types (e.g., D1A-EM, LP1 EM)
- Include compound types (e.g., AS1/AS2, SC1/SC3)
- Include size variants that are part of the code (e.g., B1.8', B1.12')
- Do NOT include descriptions, manufacturers, wattages, or catalog numbers
- Do NOT invent types that are not in the text

Return ONLY valid JSON: {"fixture_types": ["TYPE1", "TYPE2", ...]}

Schedule text:
---
{schedule_text}
---
```

**Why LLM here**: The schedule table has structured columns (TYPE | DESCRIPTION | MANUFACTURER | WATTAGE). The LLM understands tabular structure and can extract just the type column — handling noise, merged cells, multi-line entries, and formatting variations that regex cannot.

**JSON parsing**: Use defensive parsing matching the existing pattern in `page_classifier.py::_parse_llm_response()` — strip markdown code blocks, handle malformed JSON, extract the `fixture_types` array.

**Normalization**: The LLM output is used as-is. No post-processing normalization (like DF01→DF1). The LLM should return codes as they appear in the schedule. However, the counting stage (`counter.py`) still uses `normalize_fixture_code()` when matching floor plan labels to type codes — that normalization handles the DF01/DF1 mismatch during counting, not during discovery.

### Step 4: Cross-Validate Against Floor Plans

**Input**: Fixture types from Step 3, lighting plan page indices from Step 1.
**Output**: Final fixture type list with validation metadata.

1. Use pdfplumber to extract words from 2-3 lighting plan pages (open PDF once, share the handle from Step 2 if possible).
2. For each type from Step 3, check if it appears on any floor plan page (exact match or normalized match via `normalize_fixture_code`).
3. Detect potential missed types on floor plans using the schedule types as a template:
   - Extract all short uppercase words (2-10 chars) from floor plan pages.
   - Filter to words that share a prefix pattern with at least one known schedule type. For example, if the schedule contains `D1A`, then `D1B` and `D2` on the floor plan share the `D` prefix pattern and are candidates. If the schedule contains `LT-104`, then `LT-107` shares the `LT-` prefix.
   - Exclude common engineering abbreviations (the existing `_EXCLUDE_WORDS` set in `schedule_parser.py`).
   - Any candidate not already in the schedule list is flagged as `source: "floor_plan_only"`.
4. Return combined list with source metadata:
   - `source: "schedule"` — found in fixture schedule
   - `source: "floor_plan_only"` — found on floor plans but not in schedule (needs review)

**Purpose**: Catches types that are on the drawings but missing from the schedule (rare but possible — e.g., added after schedule was finalized). Also validates that schedule types actually appear in the project.

## Files to Change

| File | Change |
|------|--------|
| `app/pipeline.py` | Replace `_FIXTURE_TYPE_RE`, `_discover_fixture_types_from_pages()`, and `_discover_types()` with new 4-step discovery function. Remove the `_detect_pages()` bypass that skips schedule detection. Update `run_fixture_discovery()` and `run_pipeline()`. |
| `app/utils/pdf_utils.py` | Add `parse_sheet_index()` for Step 1. Add `extract_pages_words_batch()` to open PDF once and extract multiple pages. |
| `app/stages/schedule_parser.py` | Rewrite to use LLM for type extraction (Step 3) instead of regex. Keep pdfplumber for text extraction (Step 2). |
| `app/config.py` | Add `SCHEDULE_TEXT_THRESHOLD` (default 1500) and `PDFPLUMBER_PAGE_TIMEOUT` (default 60). |

## Files NOT to Change

| File | Reason |
|------|--------|
| `app/main.py` | API endpoints unchanged |
| `app/stages/counter.py` | Counting logic unchanged (`normalize_fixture_code` still used during counting) |
| `app/stages/llm_counter.py` | LLM counting unchanged |
| `app/stages/reconciler.py` | Reconciliation unchanged |
| `app/stages/page_classifier.py` | Kept as fallback for Step 1 when no sheet index found |
| `app/utils/llm_client.py` | Already supports text and vision queries |

## Test Plan

| Test File | Changes |
|-----------|---------|
| `tests/test_schedule_parser.py` | Rewrite: existing regex tests replaced with tests for LLM-based extraction. Add mock-based tests (mock `llm_text_query` to return known JSON) for deterministic CI. |
| `tests/test_pdf_utils.py` | Add tests for `parse_sheet_index()` — test with mock sheet index text, verify correct sheet-to-page mapping. |
| `tests/test_pipeline.py` | Update integration test to verify new discovery flow end-to-end (requires API key). |
| `tests/test_e2e_validation.py` | Update to validate fixture discovery (not just counting) against ground-truth CSVs. |
| New: `tests/test_fixture_discovery.py` | Deterministic unit tests for the 4-step flow with mocked LLM responses. Test: sheet index parsing, rasterized detection, cross-validation logic. |

## Verification

Per `docs/fixture-type-verification.md`:

### Chase Bank (30 expected types)
- Current: 19 returned, 17 missing, 3 false positives
- Target: 30 returned, 0 missing, 0 false positives
- Key test: EM variants (D1A-EM, L1A-EM), high-number types (L500, L-411, L-412), non-standard types (L8, L8EM)

### AMLI BREA (83 expected types)
- Current: Not yet baselined (regex matches almost nothing)
- Target: 83 returned, 0 missing, 0 false positives
- Key test: Completely different naming convention (AL, AS, BH, GA, GH, SS, RD, etc.)

### Pass/Fail
- Both datasets must achieve 100% recall (all expected types found)
- Both datasets must achieve 100% precision (no false positives)
- Any regression from baseline is a failure

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Sheet index not found in some PDFs | Fallback to existing LLM page classification |
| Sheet number appears on multiple pages (cross-references) | Disambiguate by title block position (bottom-right) and sequential page ordering |
| pdfplumber timeout on large pages | 60s per-page timeout, fall back to LLM vision |
| LLM hallucinates fixture types | Cross-validation against floor plan text (Step 4) |
| Schedule text is garbled (encoding issues) | LLM vision on rendered page image as fallback |
| Schedule spread across many pages (>5) | Combine text, split into multiple LLM calls if >15K words |
| LLM returns malformed JSON | Defensive parsing (strip markdown, regex fallback) matching existing `_parse_llm_response()` pattern |

## Out of Scope

- Fixture counting accuracy (separate concern, unchanged)
- Unit multiplication logic (unchanged)
- Non-Bluebeam PDFs (Popeyes — already rejected by classifier)
- BOM expansion (catalog number mapping)
- Frontend changes
