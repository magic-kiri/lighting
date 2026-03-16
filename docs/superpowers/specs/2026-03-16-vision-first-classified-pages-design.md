# Approach A: Vision-First on Classified Pages — Design Spec

## Goal

Replace the current mixed pdfplumber+vision fixture type discovery with a uniform GPT-4.1 vision approach applied to all classified pages, achieving 95%+ recall and precision.

## Problem Statement

The current `POST /fixtures` endpoint uses a complex hybrid approach:
- pdfplumber text extraction for text-extractable schedule pages
- Vision OCR for rasterized schedule pages
- pdfplumber word extraction + pattern matching + frequency filtering for floor plan pages

This causes:
- Non-deterministic results from vision (different types each run)
- Complex apartment number / room number filtering that still leaks false positives
- Prefix anchoring / frequency threshold logic that drops real types
- Different code paths for rasterized vs text pages

## Solution

**Single vision model (GPT-4.1), one call per classified page, frequency-based filtering.**

### Pipeline

1. **Classify PDF** — existing extractability check (keep as-is)
2. **Detect pages** — existing sheet index parser + deterministic detection (keep as-is). Returns schedule pages, lighting plan pages, unit plan pages.
3. **Expand page set** — add electrical plan pages with 15+ fixture codes (existing `_find_all_fixture_pages`, keep as-is)
4. **Vision scan** — render each page to image at 200 DPI, send to GPT-4.1 with fixture-type-extraction prompt. One API call per page. Parallel via ThreadPoolExecutor.
5. **Aggregate** — collect all types from all pages. Track which pages each type appears on.
6. **Filter** — types on 2+ pages = high confidence (keep). Types on exactly 1 page: keep if that page is a schedule page, otherwise drop. Apply pattern filter (panel refs, spec codes, exclude words).
7. **Deduplicate** — normalize separators (D1A-EM = D1A EM), strip size suffixes, deduplicate.

### Key Design Decisions

- **GPT-4.1 only, not Gemini** — GPT-4.1 is more consistent at structured table reading. Cross-project hallucinations are handled by the 2+ page frequency filter (hallucinations appear on 1 page, real types appear on schedule + floor plans).
- **No pdfplumber for type discovery** — Vision reads both rasterized and text-extractable content. Eliminates the need for two code paths.
- **Schedule page types trusted at frequency=1** — fixture schedules list each type exactly once. A type on a schedule page but no floor plan is still real (it may have zero count or appear on unscanned pages).
- **200 DPI rendering** — balances image quality vs API token cost. Engineering drawings at 200 DPI are readable by GPT-4.1.

### Prompt Design

```
You are reading a page from an engineering lighting drawing PDF.
List ALL lighting fixture type codes visible on this page.

Fixture type codes are short identifiers like: D1A, L-2, DF1, SS9, LT-104.1, BX(S), PH3-POLE
Include EM variants: D1A-EM, LP1 EM, L500-EM
Include compound types: AS1/AS2, SC1/SC3
Include size variants: B1.8', B1.12'

Return ONLY fixture type codes, not descriptions, catalog numbers, or manufacturers.
If no fixture types are visible, return an empty list.

Return valid JSON: {"fixture_types": ["TYPE1", "TYPE2", ...]}
```

### Files

- **Create:** `app/stages/vision_scanner.py` — renders pages, calls GPT-4.1, parses responses
- **Modify:** `app/pipeline.py` — new `_discover_types_v2()` using vision scanner
- **Keep:** `app/stages/classifier.py`, `app/stages/page_classifier.py`, `app/utils/pdf_utils.py` (page detection unchanged)
- **Keep:** `app/stages/schedule_parser.py` (still used by `run_pipeline` for counting, but not by fixture discovery)

### Expected Performance

| Dataset | Pages Scanned | API Calls | Cost | Runtime | Recall | Precision |
|---------|--------------|-----------|------|---------|--------|-----------|
| Chase Bank | ~8 | ~8 | ~$0.15 | ~2-3 min | 90-95% | 85-95% |
| AMLI BREA | ~43 | ~43 | ~$0.80 | ~8-12 min | 85-92% | 80-90% |

### Verification

After implementation, run `verify_fixtures.py` against both datasets. Both must achieve 95%+ recall. If not, iterate on:
1. Prompt improvements
2. DPI adjustments
3. Page classification expansion
4. Filtering threshold tuning
