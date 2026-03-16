# Approach B: Multi-Run Vision on Schedule + pdfplumber on Floor Plans — Design Spec

## Goal

Fix the rasterized schedule recall problem by running GPT-4.1 vision 3 times per schedule page and taking the union, while keeping the proven pdfplumber extraction for floor plan pages.

## Problem Statement

The current system has two weaknesses:
1. Vision OCR of rasterized schedule pages is non-deterministic — each run finds different types
2. pdfplumber floor plan scanning has complex filtering that drops some real types

Approach B fixes problem #1 (the bigger blocker) while keeping the deterministic floor plan extraction.

## Solution

**Multi-run vision (3x) for rasterized schedule pages. pdfplumber for floor plans.**

### Pipeline

1. **Classify PDF** — existing extractability check (keep as-is)
2. **Detect pages** — existing sheet index parser + deterministic detection (keep as-is)
3. **Schedule extraction:**
   - Text-extractable schedule pages → pdfplumber text + LLM text extraction (existing, keep as-is)
   - Rasterized schedule pages → GPT-4.1 vision × 3 runs per page. Take union of all types found. Types in 2+ of 3 runs = high confidence. Types in 1 of 3 runs = lower confidence (kept but flagged).
4. **Floor plan extraction** — existing pdfplumber word extraction + pattern matching (keep as-is with current filters)
5. **Merge** — combine schedule types + floor plan types, deduplicate
6. **Hallucination filter** — existing filter (keep as-is) handles cross-project contamination

### Key Design Decisions

- **3 runs per rasterized page** — each run may find different types due to model non-determinism. The union maximizes recall. 3 runs is the sweet spot: 2 runs miss too many, 4+ adds cost with diminishing returns.
- **GPT-4.1 for all 3 runs** — same model, same prompt, different random seed. The non-determinism comes from the model's sampling, not from using different models.
- **Keep pdfplumber for floor plans** — it's deterministic, fast for text-extractable pages, and proven. The apartment number filtering bugs are manageable and mostly fixed.
- **1-of-3 types still kept** — a type found in only 1 of 3 runs might be real (the model read it correctly once). The downstream hallucination filter handles false positives.

### Files

- **Modify:** `app/stages/schedule_parser.py` — add multi-run logic to `_extract_types_with_vision()`
- **Keep:** `app/pipeline.py` — no structural changes, `_discover_types()` works as-is
- **Keep:** all other files unchanged

### Expected Performance

| Dataset | Schedule API Calls | Cost | Runtime | Recall | Precision |
|---------|-------------------|------|---------|--------|-----------|
| Chase Bank | 3 (1 rasterized page × 3 runs) | ~$0.06 | ~3-5 min | 85-95% | 80-90% |
| AMLI BREA | 9 (3 rasterized pages × 3 runs) | ~$0.18 | ~8-15 min | 80-90% | 70-85% |

### Verification

After implementation, run `verify_fixtures.py` against both datasets. Target: 95%+ recall on both. If recall is below target, increase to 5 runs per page. If precision is below target, require 2-of-N consensus for schedule-only types.
