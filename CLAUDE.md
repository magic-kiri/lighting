# Commercial Lighting - Fixture Takeoff Automation

## Project Overview
Automate the "lighting fixture takeoff" process for Commercial Lighting Industries (CLI).

**Current manual process**: Engineers receive architectural/electrical PDF drawings, manually read fixture schedules, count fixture symbols across all floor plan pages, and produce a Bill of Materials Excel file for quoting.

**Goal**: Build a system that takes engineering drawing PDFs as input and produces a CSV with fixture Type + Quantity, using pdfplumber (deterministic) + LLM vision (verification).

## Business Context
- **Company**: Commercial Lighting Industries (CLI), Indio, CA
- **Contact**: Kaz Halcovich (National Account Sales Manager), Farren Halcovich
- **Client of**: Techjays (Philip Samuelraj) - building the POC
- **Domain**: Commercial lighting distribution - they supply lighting fixtures for construction projects

## Architecture

5-stage pipeline (see `docs/plans/2026-03-12-fixture-extractor-design.md` for full design):

1. **Stage 1 — PDF Classifier** (`app/stages/classifier.py`): Checks if PDF is text-extractable (Bluebeam). Rejects non-extractable PDFs.
2. **Stage 2 — Page Classifier** (`app/stages/page_classifier.py`): LLM classifies every page as LIGHTING_PLAN, FIXTURE_SCHEDULE, UNIT_PLAN, or OTHER.
3. **Stage 3 — Schedule Parser** (`app/stages/schedule_parser.py`): Extracts fixture type codes from schedule pages using pdfplumber.
4. **Stage 4 — Fixture Counter**:
   - 4a. Deterministic (`app/stages/counter.py`): pdfplumber spatial extraction with exclusion zones (`app/utils/spatial.py`)
   - 4b. LLM Vision (`app/stages/llm_counter.py`): Renders pages to images, LLM counts fixtures
   - 4c. Reconciler (`app/stages/reconciler.py`): Compares 4a vs 4b, assigns confidence (high/review)
5. **Stage 5 — Output** (`app/stages/reconciler.py`): Writes CSV with Type, Quantity, Confidence, Note

Pipeline orchestrator: `app/pipeline.py`
FastAPI endpoint: `app/main.py` — `POST /extract` (full pipeline), `POST /fixtures` (type discovery only), `GET /health`
Frontend: `frontend/index.html` — Single-page UI for uploading PDFs and viewing results

## Tech Stack
- **Language**: Python 3.11+
- **API Framework**: FastAPI + uvicorn
- **PDF Text Extraction**: pdfplumber (best CID/Identity-H handling for Bluebeam PDFs)
- **PDF Page Rendering**: PyMuPDF (fitz) — renders pages to images for LLM vision
- **LLM SDKs**: anthropic, openai, google-generativeai — direct SDKs with thin wrapper (`app/utils/llm_client.py`)
- **Config**: `.env` file (see `.env.example`) — API keys, model selection, thresholds
- **Output**: CSV (Type, Quantity, Confidence)

## Counting Patterns
- **Direct Counting** (Chase Bank): Count fixture labels on lighting plan pages directly
- **Unit Multiplication** (AMLI BREA): Count per unit type, multiply by unit instances (TODO: full implementation)

## Sample Data (3 difficulty levels)
| Project | Difficulty | PDF Pages | Fixture Types | Pattern |
|---------|-----------|-----------|---------------|---------|
| Popeyes (Newberg, OR) | Easy (out of scope v1) | 15 | ~14 types | Direct AutoCAD export — NOT extractable |
| Chase Bank (Newport Beach) | Medium | 173 | ~30+ types | Direct counting |
| AMLI BREA (Brea, CA) | Very Large | 135 | 80+ types | Unit multiplication |

## Key Data Files
- `Email.txt` - Original email from Kaz with project links and Popeyes counts
- `AMLI-BREA, CA COUNTS.xlsx` - Expected output for AMLI BREA project
- `CHASE BANK - NEWPORT BEACH COUNTS.xlsx` - Expected output for Chase Bank project
- `Newberg Popeyes Permit Set Revised_ E-Sheets.pdf` - Popeyes engineering drawings
- `04_Electrical_1-16-2026.pdf` - AMLI BREA electrical drawings
- `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf` - Chase Bank drawings

## Project Structure
```
app/
  main.py                  # FastAPI app, POST /extract, GET /health
  config.py                # Env vars, model config, thresholds
  pipeline.py              # Orchestrates Stage 1-5
  stages/
    classifier.py          # Stage 1: PDF extractability check
    page_classifier.py     # Stage 2: LLM page classification
    schedule_parser.py     # Stage 3: Fixture schedule extraction
    counter.py             # Stage 4a: pdfplumber spatial counting
    llm_counter.py         # Stage 4b: LLM vision counting
    reconciler.py          # Stage 4c: Compare, reconcile, CSV output
  utils/
    pdf_utils.py           # pdfplumber/fitz helpers
    spatial.py             # Exclusion zone detection
    llm_client.py          # Thin wrapper over provider SDKs
frontend/
  index.html               # Single-page UI
tests/
  test_classifier.py       # Stage 1 tests (3 tests)
  test_page_classifier.py  # Stage 2 tests (requires LLM API key)
  test_schedule_parser.py  # Stage 3 tests (3 tests)
  test_counter.py          # Stage 4a tests (2 tests)
  test_llm_counter.py      # Stage 4b tests (3 deterministic + 1 LLM)
  test_reconciler.py       # Stage 4c tests (4 tests)
  test_pdf_utils.py        # PDF utility tests (7 tests)
  test_llm_client.py       # LLM client tests (requires API key)
  test_main.py             # FastAPI endpoint tests (2 tests)
  test_pipeline.py         # Pipeline integration test (requires API key)
  test_e2e_validation.py   # E2E comparison against expected Excel counts
docs/
  plans/                   # Design and implementation plans
  results/                 # Experiment results and learnings (READ BEFORE CHANGING TYPE DISCOVERY)
    2026-03-16-fixture-type-discovery-results.md  # Comprehensive results from 5 approaches tested
  superpowers/plans/       # Implementation plans for approaches A and B
  superpowers/specs/       # Design specs for approaches A and B
  fixture-type-verification.md  # Verification process, ground truth, and baseline results
  pdf-encoding-analysis.md # PDF encoding analysis across 3 samples
  popeyes-counts-derivation.md
  how-counts-are-derived.md
```

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Set up API keys
cp .env.example .env
# Edit .env with your API key

# Run tests (deterministic only — no API key needed)
pytest tests/test_classifier.py tests/test_schedule_parser.py tests/test_counter.py tests/test_reconciler.py tests/test_llm_counter.py tests/test_main.py -v

# Run the server
uvicorn app.main:app --reload --port 8000

# Extract fixtures from a PDF
curl -X POST "http://localhost:8000/extract" -F "file=@your-drawing.pdf"
```

## Verification

See `docs/fixture-type-verification.md` for the full process. Summary:

- **After any change to fixture type extraction**, run `POST /fixtures` against both test PDFs and compare results to ground-truth CSVs.
- **Ground-truth CSVs**: `chase-bank-newport-beach-counts.csv` (30 types), `amli-brea-counts.csv` (83 types).
- **Metrics**: Recall (did we find all expected types?) and Precision (did we avoid false positives?). Both must be 100% target, and neither may regress from the recorded baseline.
- **Key rule**: If the ground-truth CSV shows a type with a non-zero quantity, the API must return that type. Types with zero or empty quantity are also expected but lower priority.

## Fixture Type Discovery — Key Learnings (READ FIRST)

**Before changing any fixture type extraction code**, read `docs/results/2026-03-16-fixture-type-discovery-results.md`. It documents 5 approaches tried and why each succeeded or failed.

### Critical Facts
- Both test PDFs have **rasterized fixture schedule pages** (embedded images, not extractable text). This is the #1 blocker to 95%+ accuracy.
- **Gemini 2.5 Flash** is the best available vision model — it doesn't hallucinate cross-project types. Currently runs 3× per rasterized page (multi-run union).
- **GPT-4.1 is unusable for schedule OCR** — it hallucinates fixture types from other projects in its training data.
- **GPT-4.1 is unusable for floor plan scanning** — it can't distinguish fixture labels from room/office numbers.
- **pdfplumber is best for floor plans** (text-extractable pages) — deterministic, pattern-matchable. Vision fails on floor plans.
- **Apartment number filtering** is critical for AMLI BREA (residential project). Single-letter prefix isolation (`schedule_prefixes_single`) prevents apartment codes from polluting results.
- A **valid Anthropic API key** (Claude Sonnet) or **Gemini 2.5 Pro** would likely break through the accuracy ceiling.

### Current Baseline
| Dataset | Recall | Precision |
|---------|--------|-----------|
| Chase Bank | 70% | 87.5% |
| AMLI BREA | 73.9% | 64.1% |

## Technical Notes
- Only Bluebeam-exported PDFs are supported in v1 (direct AutoCAD exports have SHX vector strokes, not extractable text)
- pdfplumber finds ~2.5x more fixture labels than PyMuPDF due to better CID/Identity-H handling
- Rasterized fixture schedules are now handled via multi-run Gemini vision (3× per page)
- Classifier threshold set to 2000 avg chars to correctly reject Popeyes (has title block text but no fixture labels)
