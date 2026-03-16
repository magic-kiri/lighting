# Fixture Type Extraction — Verification Process

## Purpose

This document defines how to verify that the `POST /fixtures` API correctly identifies all unique lighting fixture types from an engineering PDF. Counting accuracy is out of scope — this is strictly about **type discovery completeness** and **absence of false positives**.

## Definitions

- **Expected types**: The unique fixture type codes from the ground-truth CSV for a given project. Strip size/variant suffixes like `(4')`, `(SF)`, `(SD)` to get the base type code.
- **Missing types**: Types present in the expected CSV but absent from the API response. These are failures.
- **False positives**: Types returned by the API that do not appear anywhere in the expected CSV. These are failures.
- **Recall**: `(expected - missing) / expected` — what percentage of real types we found.
- **Precision**: `(returned - false_positives) / returned` — what percentage of returned types are real.

## Datasets

### Dataset 1: Chase Bank (Medium difficulty)

- **Input PDF**: `input-files/20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf`
- **Ground-truth CSV**: `chase-bank-newport-beach-counts.csv`
- **Expected unique base types (30)**:

```
D1A, D1A-EM, D1B, D2,
DF1, DF3, DF4, DF5, DF6, DF7,
L-2, L-2-EM, L-7, L-7-EM, L-22, L-411, L-412,
L1A, L1A-EM,
L2A, L2B, L3, L4, L5, L6,
L500, L500-EM,
L8, L8EM,
X1
```

Notes:
- Types like `L1A (4')`, `L1A (6')`, `L1A (8')` all map to base type `L1A`.
- Types like `L500 (2')`, `L500 (4')` all map to base type `L500`.
- `X1 (SF)` and `X1 (SD)` both map to base type `X1`.
- `DF6` and `DF7` have quantity 0 in the CSV but are still valid types (they exist in the fixture schedule).

### Dataset 2: AMLI BREA (Very Large)

- **Input PDF**: `input-files/04_Electrical_1-16-2026.pdf`
- **Ground-truth CSV**: `amli-brea-counts.csv`
- **Expected unique base types (83)**:

```
AL1,
AS1, AS1/AS2, AS2,
B1, B1.8', B1.12', B2, B3, B4,
BH1, BH2,
BX(D), BX(S),
DF1, DF1A, DF4,
DP3, DW1,
FS1, FS2, FS3, FS4,
GA, GA1,
GH2, GH2A, GH3, GH4,
GL2,
LP1, LP1 EM, LP2, LP2 EM, LP3, LP3A, LP3B,
LR1, LR3, LR3 EM, LR5,
LS2, LS2A, LS3,
LT-101, LT-102, LT-103, LT-104, LT-104.1, LT-104.2, LT-105,
LT106, LT106.1, LT-106.2, LT-106.3, LT-106.4, LT-106.5,
LT-107, LT-108, LT-109, LT-110, LT-112, LT-113, LT-115, LT-116, LT-117, LT-118,
PH1, PH2, PH3, PH3-POLE,
RA1, RA1A, RA2, RA3, RA4, RA5,
RD2, RD3, RD4, RD6A, RD7, RD8,
RW1, RW3,
SC1, SC1/SC3, SC2, SC3,
SR1, SR2,
SS3, SS6, SS6A, SS7, SS9,
U1, U1A, U2, U3, U4, U5, U8, U9,
WR1, WR2, WS1, WS3, WS4,
XA, XK
```

Notes:
- Compound types like `AS1/AS2` and `SC1/SC3` are valid types that appear on drawings.
- Types like `B1.8'` and `B1.12'` include size as part of the type code (unlike Chase where size is parenthesized).
- `WS1 4'8"` and `WS1 7'6"` map to base type `WS1`.
- `LT106` (no dash) and `LT-106.2` (with dash) are distinct types — preserve exact formatting from the PDF.

## Verification Steps

An AI agent should follow these steps after any change to fixture type extraction logic:

### Step 1: Run the API

```bash
# Chase Bank
curl -s -X POST http://localhost:8000/fixtures \
  -H "Content-Type: application/json" \
  -d '{"file_path": "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"}' \
  | python3 -m json.tool

# AMLI BREA
curl -s -X POST http://localhost:8000/fixtures \
  -H "Content-Type: application/json" \
  -d '{"file_path": "04_Electrical_1-16-2026.pdf"}' \
  | python3 -m json.tool
```

### Step 2: Compare against ground truth

For each dataset, compute:

1. **Missing types** — expected types not found in API response.
2. **False positives** — API types not found in expected list.
3. **Recall** — `matched / total_expected` as a percentage.
4. **Precision** — `matched / total_returned` as a percentage.

When comparing, apply the following normalization to both sides:

**1. Strip size/variant suffixes in parentheses:**
- `L1A (4')` → `L1A`
- `X1 (SF)` → `X1`
- But `B1.8'` stays `B1.8'` (size is part of the code, not parenthesized)
- `WS1 4'8"` → `WS1`

**2. Normalize formatting variations in the base type code:**

After stripping suffixes, treat two type codes as equivalent if they differ only in separators, whitespace, or surrounding punctuation. Specifically, remove all dashes (`-`), spaces, underscores (`_`), quotes (`"`, `'`, `` ` ``), and any other non-alphanumeric/non-dot/non-slash characters, then compare case-insensitively.

Examples (all normalize to the same canonical form):
- `L1`, `L-1`, `L 1`, `L_1`, `"L1"` → all match
- `L1A-EM`, `L1A EM`, `L1AEM` → all match
- `DF-3`, `DF3`, `DF 3` → all match

Characters that are **preserved** during normalization (they carry meaning):
- Dots (`.`): `LT-104.1` and `LT-104.2` remain distinct
- Slashes (`/`): `AS1/AS2` and `SC1/SC3` remain compound types
- Alphanumeric characters: always preserved

This means the system should not penalize the extraction pipeline for returning `L-1` when the ground truth says `L1`, or vice versa — they are considered a match.

### Step 3: Report results

Produce a table like this for each dataset:

```
Dataset: Chase Bank
Total expected:   30
Total returned:   NN
Matched:          NN
Missing:          NN  [list them]
False positives:  NN  [list them]
Recall:           NN%
Precision:        NN%
```

### Step 4: Pass/fail criteria

| Metric    | Target | Current baseline |
|-----------|--------|------------------|
| Recall    | 100%   | TBD              |
| Precision | 100%   | TBD              |

A change is considered a **regression** if either recall or precision drops from the previously recorded baseline. Both metrics must be tracked over time.

### Step 5: Update baseline

After running verification, update the table below with current results so future runs can detect regressions.

## Baseline Results

| Date | Dataset | Recall | Precision | Missing | False Positives | Notes |
|------|---------|--------|-----------|---------|-----------------|-------|
| 2026-03-16 | Chase Bank | 70.0% (21/30) | 87.5% (21/24) | 9 (rasterized schedule only) | 3 | Multi-run Gemini (3×) for rasterized schedule. Best precision achieved. |
| 2026-03-16 | AMLI BREA | 73.9% (82/111) | 64.1% (82/128) | 28 (rasterized schedule + rare types) | 46 | Multi-run Gemini + pdfplumber floor plans. Text schedule has 13 types. |

### Approaches tried

| Approach | Chase Recall/Precision | AMLI Recall/Precision | Outcome |
|----------|----------------------|----------------------|---------|
| pdfplumber + single Gemini vision | 66-97% / 73-85% | 57-75% / 41-57% | Non-deterministic, best single-run: 96.7%/85.3% |
| pdfplumber + dual-model (Gemini+GPT-4.1) | 60-100% / 40-85% | 67-84% / 13-57% | GPT-4.1 hallucinates cross-project types |
| Vision-first (GPT-4.1 on all pages) | 23% / 58% | N/A | GPT can't distinguish fixture codes from room numbers |
| Multi-run GPT-4.1 (3× per schedule page) | 63% / 10-20% | 84% / 26% | Massive FP explosion from GPT hallucinations |
| **Multi-run Gemini (3× per schedule page)** | **70% / 87.5%** | **73.9% / 64.1%** | **Best balance. Current approach.** |

### Known limitations (rasterized schedules)

Both PDFs have fixture schedule pages embedded as **rasterized images** (not extractable text). This limits accuracy because:
1. Only vision LLM can read the schedule content (non-deterministic)
2. Gemini 2.5 Flash misses types inconsistently across runs — multi-run (3×) helps but doesn't fully solve
3. GPT-4.1 reads more types but hallucinates cross-project types (unusable for precision)
4. A valid Anthropic API key (Claude Sonnet) would significantly improve rasterized schedule OCR accuracy
5. For AMLI, 20+ of the 111 expected types exist ONLY on rasterized schedule pages — not extractable by pdfplumber

## Common failure patterns to watch for

1. **Regex too narrow**: The `_FIXTURE_TYPE_RE` pattern in `pipeline.py` only matches certain prefixes. New projects may have prefixes not yet covered (e.g., `AL`, `BH`, `GA`, `SS`, `RD`, `WR`).
2. **EM variant dropped**: Types ending in `-EM` or ` EM` (space-separated) may not match if the regex or normalization strips them.
3. **Separator normalization**: During verification comparison, formatting differences like `L-22` vs `L22`, `LT106` vs `LT-106`, `L 1` vs `L1` are normalized away (see Step 2). However, dots and slashes carry meaning and must not be stripped.
4. **Compound types**: `AS1/AS2`, `SC1/SC3` — slash-separated compound types are valid.
5. **Schedule-only types**: Some types (like `DF6`, `DF7` with qty 0) only appear in the fixture schedule, not on floor plans. If schedule parsing is skipped, these will be missed.
6. **Size-embedded codes**: `B1.8'`, `B1.12'`, `LT-104.1` — dot-separated variants are distinct types, not size suffixes to strip.
