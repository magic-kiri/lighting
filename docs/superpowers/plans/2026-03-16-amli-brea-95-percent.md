# AMLI BREA 95%+ Accuracy Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Achieve 95%+ recall AND precision on AMLI BREA fixture type discovery (111 expected types) using only Gemini + OpenAI APIs.

**Architecture:** Three-pronged approach: (1) Fix rasterized schedule OCR by enabling dual-model and using GPT-4.1 as primary with better prompts, (2) Expand floor plan scanning to recover 12 types on unscanned pages, (3) Tighten hallucination filtering to reduce false positives from vision and apartment numbers.

**Tech Stack:** Python, FastAPI, pdfplumber, fitz (PyMuPDF), OpenAI GPT-4.1 (vision), Google Gemini 2.5 Flash (vision), PIL

**Current Baseline:** ~70% recall (78/111), ~50% precision (78/138)

**Target:** 95%+ recall (106+/111), 95%+ precision

---

## Type Categorization (111 expected types)

| Category | Count | Types | Source |
|----------|-------|-------|--------|
| A: Text schedule (page 5) | 13 | B1-B4, GA, GA1, U1-U4, U8, BX, XA | pdfplumber text -> LLM |
| B: Floor-plan findable | 74 | AL1, AS1-2, BH1-2, DF1/DF1A/DF4, DP3, FS1-4, GH2-4, LP1-3, LR1-5, LS2-3, LT-101/104/107-109/112-113, PH1-3, RA1-5, RD2-8, RW1/3, SC1-3, SR1-2, SS3-9, U1A/5/9, WR1-2, WS1-4, DW1, GL2 | pdfplumber words on floor/electrical plan pages |
| C: Rasterized schedule ONLY | 24 | LT-102/103/105/106 variants/110/115-118, B1.8'/B1.12', PH3-POLE, XK, AS1/AS2, SC1/SC3, BX(D)/BX(S), LP1-2 EM, LR3 EM, LT106/LT106.1 | Vision OCR only |

---

## Chunk 1: Fix Rasterized Schedule OCR (HIGH IMPACT)

### Task 1: Enable dual-model vision for ALL rasterized schedule pages

The current `use_dual = len(text_schedule_types) == 0` disables GPT-4.1 when AMLI has a text schedule (13 types). But AMLI has 3 rasterized pages with 80+ additional types that need GPT-4.1.

**Files:**
- Modify: `app/pipeline.py` (~line 241)

- [ ] **Step 1: Fix the use_dual_model flag**

In `_discover_types()`, change the dual model logic to always enable dual model for rasterized pages:

```python
# BEFORE:
use_dual = len(text_schedule_types) == 0

# AFTER:
use_dual = True  # Always use both models for rasterized schedule OCR
```

- [ ] **Step 2: Verify server starts**

Run: `kill $(lsof -ti :8000) 2>/dev/null; sleep 2; uvicorn app.main:app --port 8000 &>/tmp/uvicorn.log & sleep 5 && curl -s http://localhost:8000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 3: Commit**

```bash
git add app/pipeline.py
git commit -m "fix: enable dual-model vision for all rasterized schedule pages"
```

### Task 2: Make GPT-4.1 the PRIMARY vision model for rasterized schedules

GPT-4.1 reads structured tables more consistently than Gemini Flash. Its hallucinations (cross-project types) are filterable by floor-plan cross-referencing. Gemini Flash's inconsistency causes non-deterministic recall drops.

**Files:**
- Modify: `app/stages/schedule_parser.py`, `_extract_types_with_vision()`

- [ ] **Step 1: Reorder vision passes — GPT-4.1 first, Gemini second**

In `_extract_types_with_vision()`, swap Pass 1 and Pass 2 so GPT-4.1 runs the full-page pass and Gemini runs the sectioned pass:

```python
# --- Pass 1: GPT-4.1 full page (primary — best at structured tables) ---
if OPENAI_API_KEY:
    try:
        response = _openai_vision_query(
            _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, image_bytes
        )
        gpt_types = _parse_fixture_types_response(response)
        if len(gpt_types) <= _MAX_TYPES_PER_SECTION:
            logger.info("  Vision pass 1 (GPT-4.1 full-page): %d types", len(gpt_types))
            pass_results.append([_clean_type_code(t) for t in gpt_types])
        else:
            logger.warning("  Vision pass 1: %d types — DISCARDED", len(gpt_types))
    except Exception as e:
        logger.warning("  GPT-4.1 vision failed: %s", str(e)[:100])

# --- Pass 2: Default provider (Gemini) sectioned ---
# (keep existing sectioned code, remove the old Gemini full-page pass)
```

- [ ] **Step 2: Also do a GPT-4.1 sectioned pass for coverage**

Add a second GPT-4.1 pass with the top and bottom sections:

```python
# --- Pass 3: GPT-4.1 sectioned (top half + bottom half) ---
if OPENAI_API_KEY:
    for name, top_f, bot_f in [("gpt-top", 0.0, 0.50), ("gpt-bot", 0.45, 1.0)]:
        try:
            crop = img.crop((0, int(h * top_f), w, int(h * bot_f)))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            response = _openai_vision_query(
                _VISION_OCR_SYSTEM, _VISION_EXTRACT_PROMPT, buf.getvalue()
            )
            section_types = _parse_fixture_types_response(response)
            if len(section_types) <= _MAX_TYPES_PER_SECTION:
                pass_results.append([_clean_type_code(t) for t in section_types])
        except Exception as e:
            logger.warning("  GPT-4.1 %s failed: %s", name, str(e)[:100])
```

- [ ] **Step 3: Commit**

```bash
git add app/stages/schedule_parser.py
git commit -m "feat: use GPT-4.1 as primary vision for rasterized schedule OCR"
```

### Task 3: Improve rasterized schedule vision prompt to reduce hallucinations

**Files:**
- Modify: `app/stages/schedule_parser.py`, `_VISION_EXTRACT_PROMPT`

- [ ] **Step 1: Add anti-hallucination guardrails to the prompt**

```python
_VISION_EXTRACT_PROMPT = """Look at this lighting fixture schedule from an engineering drawing.
Extract ALL unique fixture type codes from the TYPE column (usually the first or leftmost column).

CRITICAL RULES:
1. Read EVERY row in the table, including partially visible ones
2. Type codes are SHORT identifiers in the LEFTMOST column: L-2, L-7, D1A, DF1, SS9, LT-104.1
3. Include EM variants: D1A-EM, LP1 EM, L500-EM, L8EM
4. Include compound types: AS1/AS2, SC1/SC3
5. Include size variants: B1.8', B1.12', L1A (4')
6. Include parenthesized: BX(S), BX(D)
7. Include POLE variants: PH3-POLE

DO NOT:
- Include manufacturer names, catalog numbers, wattages, or descriptions
- Invent or guess types not clearly visible in the image
- Include types from memory or other projects — ONLY what you see HERE

Return ONLY valid JSON: {{"fixture_types": ["TYPE1", "TYPE2", ...]}}"""
```

- [ ] **Step 2: Commit**

```bash
git add app/stages/schedule_parser.py
git commit -m "feat: improve vision prompt with anti-hallucination guardrails"
```

---

## Chunk 2: Expand Floor Plan Scanning (HIGH IMPACT)

### Task 4: Lower page expansion threshold and fix MECHANICAL exclusion

12 expected types exist on pages currently excluded by the `min_codes=30` threshold or the MECHANICAL keyword exclusion.

**Files:**
- Modify: `app/pipeline.py`, `_find_all_fixture_pages()` and call site

- [ ] **Step 1: Lower min_codes from 30 to 8**

In `_discover_types()` call site:
```python
additional = _find_all_fixture_pages(pdf_path, scan_pages + schedule_pages, min_codes=8)
```

- [ ] **Step 2: Fix MECHANICAL exclusion to allow "MECHANICAL ROOM LIGHTING PLAN"**

In `_find_all_fixture_pages()`, change the exclusion logic:

```python
# BEFORE:
exclude_words = {'DETAIL', 'SCHEDULE', 'NOTE', 'SPEC', 'DIAGRAM',
                 'RISER', 'CALCULATION', 'COVER', 'INDEX', 'LEGEND',
                 'DEMOLITION', 'DEMO', 'POWER', 'SINGLE LINE',
                 'PANEL', 'MECHANICAL', 'PLUMBING'}

# AFTER:
exclude_words = {'DETAIL', 'SCHEDULE', 'NOTE', 'SPEC', 'DIAGRAM',
                 'RISER', 'CALCULATION', 'COVER', 'INDEX', 'LEGEND',
                 'DEMOLITION', 'DEMO', 'SINGLE LINE', 'PANEL', 'PLUMBING'}
# Exclude POWER pages unless they also say LIGHTING
# Exclude MECHANICAL pages unless they also say LIGHTING
```

And add conditional exclusion logic:
```python
if any(w in tail for w in exclude_words):
    continue
# POWER and MECHANICAL pages excluded unless also LIGHTING
if ('POWER' in tail or 'MECHANICAL' in tail) and 'LIGHTING' not in tail:
    continue
```

- [ ] **Step 3: Commit**

```bash
git add app/pipeline.py
git commit -m "feat: expand floor plan scanning to cover more electrical pages"
```

### Task 5: Add vision schedule prefixes to floor plan anchor set

Types like DW1, GL2 have unique prefixes not in the text schedule. If vision found types with these prefixes, floor plan scanning should accept them.

**Files:**
- Modify: `app/pipeline.py`, the code block that builds `all_schedule_set`

- [ ] **Step 1: Add ALL vision schedule types as trusted anchors**

```python
# BEFORE (current code adds only prefixes with 3+ vision types):
all_schedule_set = {t.upper() for t in text_schedule_types}
vision_prefix_count: dict[str, int] = {}
for t in raw_vision_types:
    m = re.match(r'^([A-Z]+)', t.upper())
    if m:
        vision_prefix_count[m.group(1)] = vision_prefix_count.get(m.group(1), 0) + 1
for t in raw_vision_types:
    m = re.match(r'^([A-Z]+)', t.upper())
    if m and vision_prefix_count.get(m.group(1), 0) >= 3:
        all_schedule_set.add(t.upper())

# AFTER: Trust all vision schedule types (they come from schedule pages)
all_schedule_set = {t.upper() for t in text_schedule_types}
for t in raw_vision_types:
    all_schedule_set.add(t.upper())
```

Note: This may increase FPs. The hallucination filter downstream will handle most of it. But if precision drops too much, revert to the 3+ prefix threshold.

- [ ] **Step 2: Commit**

```bash
git add app/pipeline.py
git commit -m "feat: trust all vision schedule types as floor plan anchors"
```

---

## Chunk 3: Fix Hallucination Filtering (HIGH IMPACT for precision)

### Task 6: Fix letter-only code filter to allow schedule-sourced codes

The current filter drops ALL 2-3 letter codes from vision (kills XK, XA). Schedule-sourced letter-only codes should be trusted.

**Files:**
- Modify: `app/pipeline.py`, `_filter_vision_hallucinations()`

- [ ] **Step 1: Allow letter-only codes that match schedule patterns**

```python
# BEFORE:
# Drop letter-only codes from vision (ED, SF) — too ambiguous
if re.match(r'^[A-Z]{2,3}$', upper) and upper not in text_set:
    logger.debug("  Vision filter: dropping %s (letter-only code from vision)", t)
    continue

# AFTER:
# Drop letter-only codes ONLY if they're common abbreviations, not fixture codes
# Schedule-sourced letter-only codes (GA, XA, XK) should pass
_LETTER_ONLY_EXCLUDE = {'ED', 'SF', 'AC', 'DC', 'EM', 'AM', 'PM', 'IC', 'ID',
                         'AS', 'IS', 'IT', 'IF', 'OR', 'ON', 'IN', 'AT', 'TO'}
if re.match(r'^[A-Z]{2,3}$', upper):
    if upper in _LETTER_ONLY_EXCLUDE and upper not in text_set:
        logger.debug("  Vision filter: dropping %s (ambiguous letter-only code)", t)
        continue
```

- [ ] **Step 2: Commit**

```bash
git add app/pipeline.py
git commit -m "fix: allow schedule-sourced letter-only codes (XK, XA) through vision filter"
```

### Task 7: Tighten hallucination filter for vision-only types without floor plan support

Cross-project hallucinations (types from Chase Bank appearing in AMLI) need stricter filtering.

**Files:**
- Modify: `app/pipeline.py`, `_filter_vision_hallucinations()`

- [ ] **Step 1: Add cross-project hallucination filter**

After the existing filters, add:

```python
# Cross-project hallucination filter: vision-only types whose prefix
# appears in NEITHER text schedule NOR floor plans AND has < 2 types
# with that prefix in vision → likely hallucinated from another project
m_prefix = re.match(r'^([A-Z]+)', upper)
if m_prefix:
    prefix = m_prefix.group(1)
    if prefix not in known_prefixes:
        prefix_n = vision_prefix_count.get(prefix, 0)
        if prefix_n < 2:
            if norm not in floor_set and upper not in floor_set:
                logger.debug("  Vision filter: dropping %s (unknown single-prefix, no floor plan support)", t)
                continue
```

This is already partially implemented. Verify the threshold is `< 2` (not `< 3`) so isolated hallucinations from unknown prefixes are caught.

- [ ] **Step 2: Commit**

```bash
git add app/pipeline.py
git commit -m "fix: tighten cross-project hallucination filter for vision-only types"
```

---

## Chunk 4: Verification & Iteration

### Task 8: Run verification and iterate

- [ ] **Step 1: Restart server**

```bash
kill $(lsof -ti :8000) 2>/dev/null; sleep 2
uvicorn app.main:app --port 8000 &>/tmp/uvicorn.log &
sleep 5 && curl -s http://localhost:8000/health
```

- [ ] **Step 2: Run AMLI BREA verification**

```bash
PYTHON="/opt/homebrew/Cellar/python@3.11/3.11.11/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python"
$PYTHON verify_fixtures.py
```

Compare results against the verification doc targets.

- [ ] **Step 3: Run Chase Bank verification (regression check)**

Ensure Chase Bank doesn't regress from 96.7% recall, 85.3% precision.

- [ ] **Step 4: Analyze results and iterate**

If recall < 95%: Check which types are still missing and whether they're rasterized-schedule-only or floor-plan-findable. Adjust thresholds.
If precision < 95%: Check which FPs remain and whether they're vision hallucinations, apartment numbers, or panel references. Add specific filters.

- [ ] **Step 5: Update baseline in docs/fixture-type-verification.md**

- [ ] **Step 6: Commit final results**

```bash
git add -A
git commit -m "feat: AMLI BREA fixture discovery improvements - XX% recall, YY% precision"
```
