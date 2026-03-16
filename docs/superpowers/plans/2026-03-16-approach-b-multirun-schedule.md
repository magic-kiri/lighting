# Approach B: Multi-Run Vision on Schedule + pdfplumber on Floor Plans — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix rasterized schedule recall by running GPT-4.1 vision 3 times per schedule page and taking the union, while keeping deterministic pdfplumber extraction for floor plan pages.

**Architecture:** Two-path approach: (1) For schedule pages, render to image and run GPT-4.1 vision 3 times independently, union all results, keep types found in 2+ runs as high confidence. (2) For floor plan pages, use existing pdfplumber word extraction with pattern matching. Merge both sources.

**Tech Stack:** Python, FastAPI, pdfplumber (floor plans), fitz (rendering), OpenAI GPT-4.1 (vision), ThreadPoolExecutor

**Spec:** `docs/superpowers/specs/2026-03-16-multirun-schedule-vision-design.md`

**Prerequisite:** Only implement this if Approach A (`docs/superpowers/plans/2026-03-16-approach-a-vision-first.md`) did not achieve 95%+ accuracy.

**Current .env config:**
```
OPENAI_API_KEY=sk-svcacct-...
OPENAI_MODEL=gpt-4.1
```

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/stages/schedule_parser.py` | **Modify** | Replace `_extract_types_with_vision()` with multi-run GPT-4.1 logic |
| `app/pipeline.py` | **Modify** | Revert `_discover_types_v2` back to `_discover_types` (the original hybrid approach), ensure rasterized schedule uses new multi-run logic |
| All other files | No change | |

---

## Chunk 1: Multi-Run Schedule Vision

### Task 1: Replace `_extract_types_with_vision` with multi-run GPT-4.1

**Files:**
- Modify: `app/stages/schedule_parser.py`

- [ ] **Step 1: Rewrite `_extract_types_with_vision` for multi-run**

Replace the entire `_extract_types_with_vision` function with:

```python
def _extract_types_with_vision(pdf_path: str, page_index: int, use_dual_model: bool = False) -> list[str]:
    """Run GPT-4.1 vision 3 times on a rasterized schedule page, union results.

    Multiple independent runs catch different types due to model non-determinism.
    The union maximizes recall. Downstream hallucination filter handles false positives.
    """
    import base64
    from collections import Counter
    from openai import OpenAI
    from app.config import OPENAI_API_KEY, OPENAI_MODEL

    if not OPENAI_API_KEY:
        logger.warning("  OPENAI_API_KEY not set, falling back to default vision")
        return _extract_types_with_vision_default(pdf_path, page_index)

    image_bytes = render_page_to_image(pdf_path, page_index, dpi=200)
    logger.info("  Rendering page %d: %.1f KB at 200 DPI", page_index, len(image_bytes) / 1024)

    client = OpenAI(api_key=OPENAI_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    N_RUNS = 3
    all_types: list[str] = []
    type_run_count: Counter = Counter()  # how many runs found each type
    norm_to_raw: dict[str, str] = {}

    for run in range(1, N_RUNS + 1):
        try:
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _VISION_OCR_SYSTEM},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": _VISION_EXTRACT_PROMPT},
                    ]},
                ],
                max_tokens=4096,
            )
            run_types = _parse_fixture_types_response(resp.choices[0].message.content)
            run_types = [_clean_type_code(t) for t in run_types]
            logger.info("  Run %d/%d: %d types", run, N_RUNS, len(run_types))

            # Track per-run occurrences
            seen_this_run = set()
            for t in run_types:
                norm = _dedup_normalize(t.strip().upper())
                if norm and norm not in seen_this_run:
                    seen_this_run.add(norm)
                    type_run_count[norm] += 1
                    if norm not in norm_to_raw:
                        norm_to_raw[norm] = t.strip()

        except Exception as e:
            logger.warning("  Run %d/%d failed: %s", run, N_RUNS, str(e)[:100])

    # Return union of all types found across runs
    # Types in 2+ runs are high confidence, 1-run types are kept for downstream filtering
    high = {n for n, c in type_run_count.items() if c >= 2}
    low = {n for n, c in type_run_count.items() if c == 1}
    logger.info("  Multi-run results: %d in 2+ runs, %d in 1 run only", len(high), len(low))

    result = []
    for norm in sorted(type_run_count, key=lambda n: (-type_run_count[n], n)):
        result.append(norm_to_raw[norm])

    return result
```

- [ ] **Step 2: Add fallback function for non-OpenAI configurations**

Add this below the new function:

```python
def _extract_types_with_vision_default(pdf_path: str, page_index: int) -> list[str]:
    """Fallback: single-pass vision using configured VISION_PROVIDER."""
    try:
        image_bytes = render_page_to_image(pdf_path, page_index, dpi=200)
        response = llm_vision_query(
            _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, image_bytes
        )
        return [_clean_type_code(t) for t in _parse_fixture_types_response(response)]
    except Exception as e:
        logger.warning("  Default vision failed for page %d: %s", page_index, e)
        return []
```

- [ ] **Step 3: Verify server starts**

```bash
kill $(lsof -ti :8000) 2>/dev/null; sleep 2
uvicorn app.main:app --port 8000 &>/tmp/uvicorn.log &
sleep 5 && curl -s http://localhost:8000/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add app/stages/schedule_parser.py
git commit -m "feat: multi-run GPT-4.1 vision for rasterized schedule pages"
```

---

## Chunk 2: Revert Pipeline to Hybrid Approach

### Task 2: Ensure pipeline uses `_discover_types` (not v2)

**Files:**
- Modify: `app/pipeline.py`

- [ ] **Step 1: Verify `run_fixture_discovery` calls `_discover_types`**

In `run_fixture_discovery()`, ensure it calls the original hybrid `_discover_types` function (not the vision-first v2). If Approach A left it pointing to `_discover_types_v2`, change it back:

```python
fixture_types, error = _discover_types(
    pdf_path, lighting_pages, schedule_pages, unit_pages
)
```

- [ ] **Step 2: Commit**

```bash
git add app/pipeline.py
git commit -m "fix: revert pipeline to hybrid discovery for Approach B"
```

---

## Chunk 3: Verification

### Task 3: Run verification on both datasets

- [ ] **Step 1: Test Chase Bank**

```bash
PYTHON="/opt/homebrew/Cellar/python@3.11/3.11.11/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python"
$PYTHON verify_fixtures.py
```

- [ ] **Step 2: Analyze results**

If recall < 95%: increase N_RUNS from 3 to 5.
If precision < 95%: require 2-of-N consensus for types from schedule-only.

- [ ] **Step 3: Update baseline in `docs/fixture-type-verification.md`**

- [ ] **Step 4: Commit final results**

```bash
git add -A
git commit -m "feat: multi-run schedule vision — Approach B"
```
