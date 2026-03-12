# Frontend Design — Fixture Takeoff UI

## Overview
Single-page demo UI for the Commercial Lighting fixture takeoff system. Vanilla HTML/CSS/JS, no build step, no dependencies.

## Scope
- Demo/exploration only — not production
- Frontend and backend in same repo
- Frontend reads PDF list from `input-files/` via API
- Sends local file path to backend for extraction

## Tech Stack
- Single `frontend/index.html` file (HTML + embedded CSS + JS)
- Served by FastAPI static file serving
- No external frameworks or libraries
- CSS-only animations for loaders

## API Contract

### GET /files
Returns list of PDF filenames available in `input-files/`.

**Response:**
```json
{
  "files": [
    "04_Electrical_1-16-2026.pdf",
    "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf",
    "Newberg Popeyes Permit Set Revised_ E-Sheets.pdf"
  ]
}
```

### POST /extract
Accepts a JSON body with the file path. Backend reads the file from disk.

**Request:**
```json
{
  "file_path": "input-files/04_Electrical_1-16-2026.pdf"
}
```

**Response (success):**
```json
{
  "status": "success",
  "project_name": "Chase Bank - Newport Beach",
  "pattern": "direct_counting",
  "fixture_counts": [
    {"type": "D1A", "quantity": 37, "confidence": "high"},
    {"type": "EM", "quantity": 29, "confidence": "review", "note": "pdfplumber=34, llm=29"}
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

**Response (error):**
```json
{
  "status": "error",
  "error": "PDF is not text-extractable...",
  "fixture_counts": [],
  "csv_path": null
}
```

## UI Layout

```
┌──────────────────────────────────────────────┐
│  Commercial Lighting - Fixture Takeoff       │
├──────────────────────────────────────────────┤
│                                              │
│  Select PDF:  [▼ dropdown ─────────────]     │
│                                              │
│  [ Extract Counts ]                          │
│                                              │
├──────────────────────────────────────────────┤
│                                              │
│  Loading State: animated pulse/shimmer       │
│  "Analyzing pages..."                        │
│                                              │
│  Results Table:                              │
│  Type │ Qty │ Confidence │ Notes             │
│                                              │
│  Error State: red alert with message         │
│                                              │
│  Metadata: project name, pattern, pages      │
│                                              │
└──────────────────────────────────────────────┘
```

## UI States
1. **Initial** — Dropdown populated, button enabled, no results
2. **Loading** — Button disabled, animated skeleton loader with shimmer effect, status text
3. **Success** — Results table with confidence badges (green=high, amber=review), metadata footer
4. **Error** — Red alert box with error message from backend

## Styling
- Clean modern design with CSS custom properties
- Dark card on light background
- CSS-only pulse + shimmer animation for loading state
- Confidence color coding: green (#22c55e) = high, amber (#f59e0b) = review
- Responsive but optimized for desktop (demo use)
