# Fixture Extractor — Design Document

**Date**: 2026-03-12
**Status**: Approved

---

## Goal

Build a FastAPI service that takes an engineering drawing PDF (Bluebeam-exported) and outputs a CSV with fixture Type + Quantity.

The system uses **pdfplumber for deterministic text extraction** as the primary counting engine, and **LLM vision as a verification layer** to cross-check counts. When both agree, confidence is high. When they disagree, the output flags the discrepancy for human review.

---

## Scope

### In Scope (v1)
- Bluebeam-exported PDFs with text-extractable fixture labels
- Two counting patterns:
  - **Direct counting** (e.g., Chase Bank) — count fixture labels on lighting plan pages
  - **Unit multiplication** (e.g., AMLI BREA) — count per unit type, multiply by unit instances
- CSV output: Type, Quantity, Confidence
- FastAPI REST endpoint: `POST /extract` accepting PDF upload
- Multi-provider LLM support (Claude, GPT-4o, Gemini) via direct SDKs

### Out of Scope (v1)
- Non-Bluebeam PDFs (direct AutoCAD export with SHX vector strokes) — rejected with clear error
- Rasterized fixture schedules — rejected with clear error (not OCR'd)
- BOM expansion (accessories, drivers, mounting hardware) — not in the PDF
- Full Excel output format — CSV only
- Popeyes-type PDFs

---

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.11+ | pdfplumber, PyMuPDF, FastAPI all Python-native |
| API Framework | FastAPI | Async, auto-docs, file upload support |
| PDF Text Extraction | pdfplumber | Best CID/Identity-H text handling for Bluebeam PDFs |
| PDF Page Rendering | PyMuPDF (fitz) | Renders pages to high-DPI images for LLM vision |
| LLM SDKs | anthropic, openai, google-generativeai | Direct SDKs with thin custom wrapper. No LiteLLM/LangChain — overkill for our few specific calls |
| Config | .env file | API keys, model selection, thresholds |
| Output | Python stdlib csv | No external dependency needed |

---

## Architecture

```
POST /extract (PDF upload)
       │
       ▼
┌──────────────────────────────────────────┐
│  Stage 1: PDF Classifier                 │
│  Check extractability (metadata + text)  │
│  Method: pdfplumber                      │
│  LLM: No                                │
│  → Pass or reject with error             │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  Stage 2: Page Classifier                │
│  Categorize every page by sheet title    │
│  Method: Extract titles → LLM classifies │
│  LLM: Yes (1 call per PDF)              │
│  Categories:                             │
│    LIGHTING_PLAN — count fixtures here   │
│    FIXTURE_SCHEDULE — type definitions   │
│    UNIT_PLAN — per-unit layouts           │
│    OTHER — ignore                        │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  Stage 3: Fixture Schedule Parser        │
│  Extract type codes from schedule page   │
│  Method: pdfplumber table parsing        │
│  LLM: No                                │
│  → List of valid fixture type codes      │
│  → If rasterized: reject with error      │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  Stage 4: Fixture Counter                │
│                                          │
│  4a. Deterministic (pdfplumber)          │
│    - Extract text with (x, y) coords    │
│    - Filter to known fixture type codes  │
│    - Spatial filtering: exclude title    │
│      block, legend, schedule zones       │
│    - Count remaining labels per type     │
│                                          │
│  4b. LLM Verification                   │
│    - Render page at 300-400 DPI (fitz)   │
│    - Send image + type list to LLM      │
│    - "Count every fixture of each type"  │
│    - 1 LLM call per lighting plan page   │
│                                          │
│  4c. Reconciliation                      │
│    - Compare 4a vs 4b per fixture type   │
│    - Agree → confidence: "high"          │
│    - Disagree → confidence: "review"     │
│      with both counts in notes           │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  Stage 5: Output                         │
│  CSV: Type, Quantity, Confidence         │
│  API response: JSON with counts + meta   │
└──────────────────────────────────────────┘
```

---

## Counting Patterns

### Pattern 1: Direct Counting (Chase Bank)

Simple: fixture labels on lighting plan pages = actual fixture count.

```
Lighting plan pages → count fixture labels → output
```

### Pattern 2: Unit Multiplication (AMLI BREA)

Residential projects with repeating unit types:

```
Unit plan pages:  Count fixtures per unit type
                  e.g., Unit "A2" has 3x U1, 2x U3, 1x U4

Floor plan pages: Count unit instances
                  e.g., 45 instances of "A2" across all floors

Multiply:         U1 = 3 × 45 = 135
                  U3 = 2 × 45 = 90
                  U4 = 1 × 45 = 45
```

The Stage 2 page classifier detects which pattern applies by identifying UNIT_PLAN pages. If unit plans exist → multiplication pattern. If not → direct counting.

---

## LLM Usage Summary

| Stage | LLM Call | Input Size | Purpose |
|-------|----------|------------|---------|
| Stage 2 | 1 call per PDF | ~200-500 tokens (sheet titles) | Page classification |
| Stage 4b | 1 call per lighting plan page (typically 2-5 pages) | ~1 image + ~100 tokens | Count verification |

**Total LLM calls per PDF**: ~3-6 calls
**Total cost estimate**: < $0.50 per PDF (varies by model and page count)

The LLM is never the sole source of truth — it's always a cross-check against the deterministic pdfplumber extraction.

---

## Project Structure

```
commercial-lighting/
├── app/
│   ├── main.py                  # FastAPI app, POST /extract endpoint
│   ├── config.py                # Env vars, model config, thresholds
│   ├── pipeline.py              # Orchestrates Stage 1→5
│   │
│   ├── stages/
│   │   ├── classifier.py        # Stage 1: PDF extractability check
│   │   ├── page_classifier.py   # Stage 2: LLM page classification
│   │   ├── schedule_parser.py   # Stage 3: Fixture schedule extraction
│   │   ├── counter.py           # Stage 4a: pdfplumber spatial counting
│   │   ├── llm_counter.py       # Stage 4b: LLM vision counting
│   │   └── reconciler.py        # Stage 4c: Compare and reconcile
│   │
│   └── utils/
│       ├── pdf_utils.py         # pdfplumber/fitz helpers
│       ├── spatial.py           # Exclusion zone detection
│       └── llm_client.py        # Thin wrapper over provider SDKs
│
├── tests/
│   ├── test_pipeline.py         # End-to-end with sample PDFs
│   ├── test_schedule_parser.py
│   └── test_counter.py
│
├── data/
│   ├── input/                   # Drop PDFs here
│   └── output/                  # CSVs go here
│
├── .env                         # API keys, MODEL config
├── requirements.txt
└── README.md
```

---

## API Interface

### Request

```
POST /extract
Content-Type: multipart/form-data
Body: file=<PDF>
```

### Response

```json
{
  "status": "success",
  "project_name": "Chase Bank - Newport Beach",
  "pattern": "direct_counting",
  "fixture_counts": [
    {"type": "D1A", "quantity": 37, "confidence": "high"},
    {"type": "L1A", "quantity": 32, "confidence": "high"},
    {"type": "EM",  "quantity": 29, "confidence": "review",
     "note": "pdfplumber=34, llm=29"}
  ],
  "csv_path": "data/output/chase-bank-counts.csv",
  "pages_analyzed": {
    "lighting_plans": [112, 113],
    "fixture_schedule": [103],
    "unit_plans": []
  },
  "schedule_types_found": 15,
  "errors": []
}
```

### Error Response (non-extractable PDF)

```json
{
  "status": "error",
  "error": "PDF is not text-extractable. Producer: 'Autodesk DWG PDF Writer'. Fixture labels are encoded as vector strokes, not text objects. Please re-export through Bluebeam or provide a Bluebeam-produced PDF.",
  "fixture_counts": [],
  "csv_path": null
}
```

### Error Response (rasterized schedule)

```json
{
  "status": "error",
  "error": "Fixture schedule on page 103 (Sheet E-005) is rasterized as an image. Text extraction not possible. Manual schedule input required.",
  "fixture_counts": [],
  "csv_path": null
}
```

---

## Validation Plan

Test against both sample PDFs and compare output with Kaz's expected counts:

| PDF | Expected Source | Fixture Types | Pattern |
|-----|----------------|---------------|---------|
| AMLI BREA (`04_Electrical_1-16-2026.pdf`) | `AMLI-BREA, CA COUNTS.xlsx` | ~80+ types | Unit multiplication |
| Chase Bank (`20251119_JPMFC_...pdf`) | `CHASE BANK - NEWPORT BEACH COUNTS.xlsx` | ~30+ types | Direct counting |

Success criteria: Output CSV type+quantity matches the Excel expected counts for both projects.

---

## Key Design Decisions

1. **pdfplumber over PyMuPDF for text extraction**: pdfplumber finds 2.5x more fixture labels on the same page due to better CID/Identity-H handling.

2. **LLM for page classification, not keywords**: Sheet titles vary wildly across engineering firms. LLM handles any naming convention. Cost is negligible (one small call per PDF).

3. **LLM as verification, not primary counter**: Deterministic extraction does the heavy lifting. LLM catches edge cases. This gives accuracy close to 100% without full AI dependency.

4. **Reject rather than OCR for rasterized schedules**: OCR adds complexity and error risk. Better to reject clearly and handle later than to silently produce wrong results.

5. **Direct SDKs over LiteLLM/LangChain**: We make 3-6 specific LLM calls per PDF. A thin wrapper over direct SDKs is simpler, more transparent, and easier to debug than a framework.
