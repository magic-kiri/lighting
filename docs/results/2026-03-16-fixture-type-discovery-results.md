# Fixture Type Discovery — Results & Learnings (2026-03-16)

## Current Performance

| Dataset | Recall | Precision | Types Found | Types Expected | Runtime |
|---------|--------|-----------|-------------|----------------|---------|
| Chase Bank | 70.0% | 87.5% | 21/30 | 30 | ~90s |
| AMLI BREA | 73.9% | 64.1% | 82/111 | 111 | ~500s |

## Architecture

The `/fixtures` endpoint uses a hybrid pipeline:

1. **Page classification** (deterministic, fast): Sheet index parser identifies schedule, lighting, and unit plan pages
2. **Text schedule extraction** (deterministic): pdfplumber text + LLM text extraction + regex extraction for text-extractable schedule pages
3. **Rasterized schedule extraction** (non-deterministic): Multi-run Gemini 2.5 Flash vision (3× per page) for rasterized schedule pages
4. **Floor plan word extraction** (deterministic): pdfplumber word extraction + pattern matching + frequency filtering
5. **Hallucination filtering**: Alphabetic suffix detection, numeric sequence detection, EM variant validation, compound type validation, unknown prefix filtering
6. **Merge & dedup**: Separator-normalized deduplication across all sources

## What Blocks 95%+ Accuracy

### Root Cause: Rasterized Fixture Schedules

Both test PDFs have fixture schedule pages that are **embedded images** (not extractable text). pdfplumber returns only title block text (~1000 chars) from these pages.

- **Chase Bank**: 1 rasterized schedule page (E-005, page 103). Contains ALL 30 fixture types.
- **AMLI BREA**: 3 rasterized schedule pages (E0.04.1-3, pages 6-8). Contain ~80 of 111 fixture types. Only 1 text-extractable schedule page (13 types).

### Missing Types (Only on Rasterized Pages)

**Chase Bank (9 missing):** L-2, L-2-EM, L-411, L-412, L-7-EM, L1A-EM, L500, L500-EM, L8EM

**AMLI BREA (20+ missing):** LT-102, LT-103, LT-105, LT106, LT106.1, LT-106.2 through LT-106.5, LT-110, LT-115 through LT-118, B1.8', B1.12', PH3-POLE, XK, AS1/AS2, SC1/SC3, LP1 EM, LP2 EM, LR3 EM

## Approaches Tried & Results

### 1. Single-pass Gemini + pdfplumber (original)
- **Chase**: 66-97% recall, 73-85% precision (non-deterministic)
- **AMLI**: 57-75% recall, 41-57% precision
- **Problem**: Gemini misses different types each run

### 2. Dual-model (Gemini + GPT-4.1) + pdfplumber
- **Chase**: 60-100% recall, 40-85% precision
- **AMLI**: 67-84% recall, 13-57% precision
- **Problem**: GPT-4.1 hallucinates types from other projects (AMLI types appear in Chase results and vice versa). More passes = more hallucinations.

### 3. Vision-first (GPT-4.1 on all classified pages, no pdfplumber)
- **Chase**: 23% recall, 58% precision
- **Problem**: GPT-4.1 cannot distinguish fixture labels from room/office numbers on dense engineering floor plans. Reads "L10" (room) instead of "D1A" (fixture).

### 4. Multi-run GPT-4.1 (3× per rasterized schedule page)
- **Chase**: 63% recall, 10-20% precision
- **AMLI**: 84% recall, 26% precision
- **Problem**: 3 runs × GPT hallucinations = massive FP explosion. Cross-project contamination across all runs.

### 5. Multi-run Gemini (3× per rasterized schedule page) — CURRENT
- **Chase**: 70% recall, 87.5% precision
- **AMLI**: 73.9% recall, 64.1% precision
- **Why best**: Gemini doesn't cross-project hallucinate. Multi-run catches different types each run. Union maximizes recall without destroying precision.

## Key Technical Learnings

### Vision Model Behavior

| Model | Strengths | Weaknesses |
|-------|-----------|------------|
| **Gemini 2.5 Flash** | No cross-project hallucination. Good at reading large fixture labels on floor plans. | Non-deterministic on small text in rasterized tables. Sometimes returns 600+ types (hallucination burst). |
| **GPT-4.1** | Reads structured tables well. Finds more types per run. | Hallucinates types from other projects in training data. Cannot distinguish fixture codes from room numbers on floor plans. |

### pdfplumber vs Vision for Floor Plans

- **pdfplumber wins for text-extractable floor plans**: Deterministic, reliable, pattern-matchable
- **Vision fails for floor plans**: Can't distinguish fixture labels (D1A) from room numbers (L10), office labels, panel references
- **Vision wins for rasterized schedules**: Only option when text isn't extractable

### Apartment Number Filtering (AMLI-specific)

AMLI BREA is a residential project with apartment type codes (A1-A8, C4, C5) that structurally resemble fixture codes. Key filters:

- Single-letter prefixes not in text schedule → unconditional reject (when text schedule exists)
- Single-letter + 3-digit codes (A125, C320D) → reject unless 10+ per-page frequency
- `schedule_prefixes_single` separates actual single-letter fixture prefixes (B, U) from multi-letter prefixes whose first letter happens to match (AL→A, SC→S)

### Hallucination Patterns

1. **Cross-project contamination** (GPT-4.1 only): Model has seen multiple fixture schedules in training data. When reading one schedule, it "recalls" types from others.
2. **Alphabetic suffix extension**: Vision sees D1A, D1B and invents D1C, D1D, D1E
3. **Numeric range filling**: Vision sees L-411 and fills in L-400 through L-450
4. **Fabricated variants**: Vision creates B1.4', B1.6', B1.16' from seeing B1.8', B1.12'

## Configuration

```
LLM_PROVIDER=openai
VISION_PROVIDER=google
OPENAI_MODEL=gpt-4.1
GOOGLE_MODEL=gemini-2.5-flash
```

## Recommendations for Next Iteration

1. **Get a valid Anthropic API key**: Claude Sonnet has the best vision quality for engineering drawings. This is the single highest-impact change for rasterized schedule accuracy.

2. **Try Gemini 2.5 Pro**: Same Google API key, substantially better OCR. Model name: `gemini-2.5-pro`. Only needed for the 1-4 rasterized schedule pages per PDF (~$0.05 extra).

3. **Request Bluebeam-flattened PDFs**: If the client can re-export the schedules as text-extractable (not rasterized images), pdfplumber handles them perfectly.

4. **Consider dedicated OCR**: AWS Textract or Google Cloud Vision OCR may read the rasterized schedule tables more accurately than general-purpose vision LLMs.

## Files Modified

| File | What Changed |
|------|-------------|
| `app/stages/schedule_parser.py` | Multi-run Gemini (3×), improved vision prompt, regex text extraction, dedup normalization |
| `app/pipeline.py` | Vision-first discovery (v2), expanded page scanning, apartment number filtering, hallucination filter improvements |
| `app/stages/vision_scanner.py` | New module (Approach A — abandoned but kept for reference) |
| `verify_fixtures.py` | Verification script for both datasets |
