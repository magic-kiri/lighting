# Approach C: Gemini 2.5 Pro Multi-Run + GPT-4.1 Corroborated — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize fixture type discovery accuracy using Gemini 2.5 Pro (best OCR) as primary with GPT-4.1 as corroborated secondary, targeting 90-98% recall and 85-95% precision.

**Architecture:** For rasterized schedule pages: run Gemini 2.5 Pro 3× (union for recall) + GPT-4.1 1× (only keep types corroborated by at least 1 Gemini run). For text schedules: existing pdfplumber + LLM + regex. For floor plans: existing pdfplumber word extraction. No changes to floor plan or text schedule paths.

**Tech Stack:** Python, Google Gemini 2.5 Pro (vision), OpenAI GPT-4.1 (vision), pdfplumber, fitz

**Key insight from prior experiments:** See `docs/results/2026-03-16-fixture-type-discovery-results.md`. Gemini doesn't cross-project hallucinate but misses types. GPT-4.1 finds more types but hallucinates. Solution: use GPT as a "type suggester" filtered through Gemini consensus.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/config.py` | **Modify** | Add `GOOGLE_PRO_MODEL` config |
| `.env` | **Modify** | Add `GOOGLE_PRO_MODEL=gemini-2.5-pro` |
| `app/stages/schedule_parser.py` | **Modify** | Rewrite `_extract_types_with_vision()` with Gemini Pro 3× + GPT-4.1 corroborated |
| `app/utils/llm_client.py` | **Modify** | Add `llm_vision_query_pro()` that uses Gemini Pro model |

---

## Task 1: Add Gemini Pro config and vision function

**Files:**
- Modify: `app/config.py`
- Modify: `.env`
- Modify: `app/utils/llm_client.py`

- [ ] **Step 1: Add GOOGLE_PRO_MODEL to config.py**

Add after the existing `GOOGLE_MODEL` line:

```python
GOOGLE_PRO_MODEL = os.getenv("GOOGLE_PRO_MODEL", "gemini-2.5-pro")
```

- [ ] **Step 2: Add GOOGLE_PRO_MODEL to .env**

Add after `GOOGLE_MODEL=gemini-2.5-flash`:

```
GOOGLE_PRO_MODEL=gemini-2.5-pro
```

- [ ] **Step 3: Add `llm_vision_query_pro()` to llm_client.py**

Add after the existing `llm_vision_query` function:

```python
def llm_vision_query_pro(system: str, prompt: str, image_bytes: bytes, image_media_type: str = "image/png") -> str:
    """Send a vision query to Gemini 2.5 Pro (higher quality OCR)."""
    return _google_vision_pro(system, prompt, image_bytes, image_media_type)


def _google_vision_pro(system: str, prompt: str, image_bytes: bytes, image_media_type: str) -> str:
    import google.generativeai as genai
    from app.config import GOOGLE_PRO_MODEL
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(GOOGLE_PRO_MODEL, system_instruction=system)
    image_part = {"mime_type": image_media_type, "data": image_bytes}
    resp = model.generate_content([image_part, prompt])
    return resp.text
```

- [ ] **Step 4: Verify imports**

```bash
cd /Users/magic-kiri/Desktop/Codes/lighting
python -c "from app.utils.llm_client import llm_vision_query_pro; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add app/config.py .env app/utils/llm_client.py
git commit -m "feat: add Gemini 2.5 Pro vision support"
```

---

## Task 2: Rewrite rasterized schedule vision extraction

**Files:**
- Modify: `app/stages/schedule_parser.py`

- [ ] **Step 1: Replace `_extract_types_with_vision` with Gemini Pro 3× + GPT corroborated**

Replace the entire function:

```python
def _extract_types_with_vision(pdf_path: str, page_index: int, use_dual_model: bool = False) -> list[str]:
    """Extract fixture types from rasterized schedule page using multi-model vision.

    Strategy:
    1. Gemini 2.5 Pro × 3 runs (best OCR, no cross-project hallucination)
    2. GPT-4.1 × 1 run (catches types Gemini misses)
    3. Union Gemini results. Only keep GPT types that are corroborated by >= 1 Gemini run.
    """
    from collections import Counter
    from app.utils.llm_client import llm_vision_query_pro
    from app.stages.schedule_parser import _openai_vision_query

    image_bytes = render_page_to_image(pdf_path, page_index, dpi=200)
    logger.info("  Rendering page %d: %.1f KB at 200 DPI", page_index, len(image_bytes) / 1024)

    # --- Gemini 2.5 Pro × 3 runs ---
    gemini_union: set[str] = set()  # normalized keys from ALL Gemini runs
    type_run_count: Counter = Counter()
    norm_to_raw: dict[str, str] = {}

    for run in range(1, 4):
        try:
            response = llm_vision_query_pro(
                _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, image_bytes
            )
            run_types = _parse_fixture_types_response(response)
            run_types = [_clean_type_code(t) for t in run_types]

            if len(run_types) > 60:
                logger.warning("  Gemini Pro run %d: %d types — DISCARDED (hallucination)", run, len(run_types))
                continue

            logger.info("  Gemini Pro run %d: %d types", run, len(run_types))

            seen_this_run = set()
            for t in run_types:
                norm = _dedup_normalize(t.strip().upper())
                if norm and norm not in seen_this_run:
                    seen_this_run.add(norm)
                    gemini_union.add(norm)
                    type_run_count[norm] += 1
                    if norm not in norm_to_raw:
                        norm_to_raw[norm] = t.strip()

        except Exception as e:
            logger.warning("  Gemini Pro run %d failed: %s", run, str(e)[:100])

    logger.info("  Gemini Pro union: %d unique types from 3 runs", len(gemini_union))

    # --- GPT-4.1 × 1 run (corroborated only) ---
    gpt_extra = 0
    if OPENAI_API_KEY:
        try:
            response = _openai_vision_query(
                _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, image_bytes
            )
            gpt_types = _parse_fixture_types_response(response)
            gpt_types = [_clean_type_code(t) for t in gpt_types]
            logger.info("  GPT-4.1: %d types", len(gpt_types))

            for t in gpt_types:
                norm = _dedup_normalize(t.strip().upper())
                if not norm:
                    continue
                if norm in gemini_union:
                    # Already in Gemini results — bump count
                    type_run_count[norm] += 1
                else:
                    # NOT in any Gemini run — discard (likely hallucination)
                    logger.debug("  GPT-only type DISCARDED: %s (not in any Gemini run)", t)

        except Exception as e:
            logger.warning("  GPT-4.1 failed: %s", str(e)[:100])

    # Only Gemini types are returned (GPT only boosts confidence, doesn't add new types)
    high = sum(1 for c in type_run_count.values() if c >= 2)
    logger.info("  Final: %d types (%d in 2+ runs)", len(gemini_union), high)

    result = []
    for norm in sorted(type_run_count, key=lambda n: (-type_run_count[n], n)):
        if norm in gemini_union:
            result.append(norm_to_raw[norm])

    return result
```

- [ ] **Step 2: Update import at top of schedule_parser.py**

Add import for `OPENAI_API_KEY`:

```python
from app.config import SCHEDULE_TEXT_THRESHOLD, OPENAI_API_KEY
```

- [ ] **Step 3: Verify server starts**

```bash
kill $(lsof -ti :8000) 2>/dev/null; sleep 2
uvicorn app.main:app --port 8000 &>/tmp/uvicorn.log &
sleep 5 && curl -s http://localhost:8000/health
```

- [ ] **Step 4: Commit**

```bash
git add app/stages/schedule_parser.py
git commit -m "feat: Gemini Pro 3× + GPT-4.1 corroborated for rasterized schedule OCR"
```

---

## Task 3: Verify on both datasets

- [ ] **Step 1: Run Chase Bank verification**
- [ ] **Step 2: Run AMLI BREA verification**
- [ ] **Step 3: If recall < 90%, increase Gemini runs to 5**
- [ ] **Step 4: If precision < 85%, tighten hallucination filters**
- [ ] **Step 5: Update baseline in docs/fixture-type-verification.md**
- [ ] **Step 6: Update results doc**
- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: Approach C results — Gemini Pro + GPT corroborated"
```
