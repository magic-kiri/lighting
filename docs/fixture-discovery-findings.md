# Fixture Type Discovery — Findings & Learnings

## Date: 2026-03-13

## What We Built

Replaced the hardcoded-regex fixture type discovery (`_FIXTURE_TYPE_RE` in `pipeline.py`) with a generic 4-step pipeline:

1. **Sheet Index Parsing** — deterministic, using fitz to find schedule/lighting/unit pages from the PDF's table of contents
2. **Schedule Text Extraction** — pdfplumber for text-extractable pages, LLM vision for rasterized pages
3. **LLM Type Extraction** — send schedule text/image to LLM, get fixture type codes back as JSON
4. **Cross-Validation** — check schedule types against floor plan words, catch missed types

## Architecture Changes

### New/Modified Files
- `app/config.py` — Added `SCHEDULE_TEXT_THRESHOLD` (1500), `PDFPLUMBER_PAGE_TIMEOUT` (60), `VISION_PROVIDER`
- `app/utils/pdf_utils.py` — Added `parse_sheet_index()`, `extract_pages_text_batch()`, `extract_pages_words_batch()`
- `app/stages/schedule_parser.py` — Rewritten: LLM-based extraction replacing regex, direct vision extraction for rasterized pages
- `app/pipeline.py` — 3-tier page detection (sheet index → deterministic → LLM), new `_discover_types()` with fallback, `_cross_validate_types()`, `_extract_floor_plan_words()`
- `app/utils/llm_client.py` — Added `VISION_PROVIDER` support (separate provider for vision vs text)
- `.env` — Added `VISION_PROVIDER=google`, switched to `gemini-2.5-flash` for vision, `gpt-4.1` for text

### New Tests
- `tests/test_fixture_discovery.py` — 3 tests for cross-validation logic
- `tests/test_schedule_parser.py` — 7 tests (mocked LLM, no API key needed)
- `tests/test_pdf_utils.py` — 4 new tests for sheet index and batch extraction

## Results

### Accuracy (as of 2026-03-13)

| Dataset | Recall | Precision | Returned | Expected |
|---------|--------|-----------|----------|----------|
| Chase Bank | 60% | 62% | 29 | 30 |
| AMLI BREA | 61% | 50% | 137 | 111 |

### What Works Well

1. **Sheet index parsing** — Correctly identifies schedule, lighting, and unit pages for both PDFs. Fast (~12s) and deterministic.
2. **3-tier page detection fallback** — Sheet index → `detect_lighting_pages()` → LLM classification. Robust for different PDF structures.
3. **Text-extractable schedule pages** — pdfplumber + GPT-4.1 text extraction works well. AMLI page 5 (13K chars) correctly yields 14 fixture types.
4. **Hybrid vision provider** — Using Gemini for vision and OpenAI for text queries. Each model plays to its strengths.
5. **Cross-validation with 2+ letter prefix** — Catches missed types (e.g., DF3, DF4 on floor plans) without adding room numbers (A103, A201).

### What Doesn't Work Well

1. **Rasterized schedule pages** — The biggest bottleneck. Pages 6-8 of AMLI and page 103 of Chase Bank are rasterized (fixture schedule content is vector/raster, not text). Vision OCR is the only option.

2. **Vision OCR quality** — Both GPT-4.1 and Gemini 2.5 Flash struggle with dense engineering drawing tables:
   - **GPT-4o/4.1**: Refuses to read complex images ("too detailed") or hallucinates sequential patterns (L1A → L1B, L1C, L1D...)
   - **Gemini 2.0 Flash**: Better at reading but makes character-level errors (G→Q, S→B, causing GH2→QH1, AS1→AB1)
   - **Gemini 2.5 Flash**: Best overall but still hallucinates non-existent types and misses some real ones

3. **Compound types** — AS1/AS2, SC1/SC3, BX(D), BX(S) are frequently missed by vision OCR. The slash and parentheses confuse the models.

4. **EM variants** — "LP1 EM" (space-separated) and "D1A-EM" (dash-separated) are inconsistently captured. The models sometimes merge them with the base type.

5. **Size-embedded codes** — B1.8', B1.12' are missed; the apostrophe and dot notation confuses vision models.

6. **LT-1xx high numbers** — LT-112 through LT-118 consistently missed (likely on a section of the page the model doesn't reach).

## Key Learnings

### LLM Model Comparison for Vision OCR

| Model | Reads content? | Accuracy | Hallucination | Cost |
|-------|---------------|----------|---------------|------|
| GPT-4o | Often refuses | Low | High (sequential patterns) | Medium |
| GPT-4.1 | Often refuses | Low | High (sequential patterns) | Medium |
| Gemini 2.0 Flash | Yes | Medium | Low | Low |
| Gemini 2.5 Flash | Yes | Medium-High | Medium | Low |

**Recommendation**: Gemini 2.5 Flash is the best available option for vision OCR on engineering drawings. It reads more types correctly but also invents some false positives.

### DPI Matters

- 300 DPI: Images too large (23 MB), models refuse or timeout
- 200 DPI: Good balance (~3-9 MB), readable
- 150 DPI: Faster but more OCR errors

### Direct Extraction > Two-Step OCR

For rasterized pages, directly asking the vision model to extract fixture type codes (1-step) works better than:
1. OCR the full page text
2. Send OCR text to another LLM for type extraction

The 2-step approach loses information and the intermediate OCR text is noisy.

### Post-Processing Helps

`_clean_type_code()` strips trailing descriptions from vision-extracted types:
- "D2 DOWNLIGHT" → "D2"
- "L2A STRAIGHT" → "L2A"
- "DF01 (AL)" → "DF01"

But it can't fix character-level misreads (QH1 for GH2) or hallucinated types (AS3, DP1).

### Cross-Validation Needs Careful Prefix Matching

- Single-letter prefixes (A, D, E) match too many words on floor plans (room numbers A103, drawing refs E-211)
- 2+ letter prefix requirement filters room numbers while still catching real types (DF3, SS7, LP3)

## Recommended Next Steps

### Option C: Floor-Plan-First Approach

Instead of relying on vision OCR of rasterized schedules, consider:

1. **Extract ALL words from lighting plan pages** using pdfplumber (which works well for Bluebeam PDFs)
2. **Filter words** that match fixture code patterns (letter(s) + digit(s), short length, not in EXCLUDE_WORDS)
3. **Use schedule pages (if text-extractable) as the authoritative source** — types from text-extractable schedule pages are high-confidence
4. **For rasterized schedule pages** — skip vision entirely, rely on floor plan extraction
5. **Cross-validate** — merge schedule types + floor plan types, deduplicate

This approach leverages pdfplumber's strength (reliable text extraction from Bluebeam PDFs) and avoids the vision OCR bottleneck entirely for type discovery. Vision would only be used for counting (Stage 4b), where it's already working.

### Other Improvements

- Try `gemini-2.5-flash` with higher temperature or multiple passes for rasterized pages
- Add retry logic with slightly different prompts for vision extraction
- Normalize returned types more aggressively (strip leading zeros, normalize dashes)
- Filter types by minimum occurrence count on floor plans (types appearing only once are likely noise)
