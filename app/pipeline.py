import logging
import os
import re
import time
from collections import Counter
from app.stages.classifier import classify_pdf
from app.stages.page_classifier import classify_pages, detect_lighting_pages
from app.stages.schedule_parser import parse_fixture_schedule, EXCLUDE_WORDS
from app.stages.counter import count_fixtures_multi_page
from app.stages.llm_counter import count_fixtures_with_llm_multi_page
from app.stages.reconciler import reconcile_counts, write_csv
from app.config import CONFIDENCE_THRESHOLD, SCHEDULE_TEXT_THRESHOLD
from app.utils.pdf_utils import (
    parse_sheet_index,
    extract_pages_words_batch,
    extract_pages_text_batch,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixture-code pattern matching (generic for engineering drawings)
# ---------------------------------------------------------------------------
# In commercial lighting, fixture type codes use 1-2 letter prefixes.
# Codes with 3+ letter prefixes (CAT6E, WAC60, BLGA-13) are product/equipment
# identifiers, not fixture type codes.

# Standard code: 1-2 letters, optional dash/dot, digits, optional suffix
_PAT_STANDARD = re.compile(
    r"^[A-Z]{1,2}[-.]?\d+[A-Z]?(?:[.-]\d+)?[']?$"
)
# EM variants: D1A-EM, L500-EM, L8EM
_PAT_EM = re.compile(r"^[A-Z]{1,2}[-.]?\d+[A-Z]?-?EM$")
# Compound: AS1/AS2, SC1/SC3 — same prefix on both sides (rejects P2/A001)
_PAT_COMPOUND = re.compile(r"^([A-Z]{1,2})\d+[A-Z]?/\1\d+[A-Z]?$")
# Parenthesized: BX(D), BX(S)
_PAT_PAREN = re.compile(r"^[A-Z]{1,2}\([A-Z]+\)$")
# POLE variant: PH3-POLE
_PAT_POLE = re.compile(r"^[A-Z]{1,2}\d+[A-Z]?-POLE$")

_FIXTURE_PATTERNS = [_PAT_STANDARD, _PAT_EM, _PAT_COMPOUND, _PAT_PAREN, _PAT_POLE]

# Sheet/section reference: letter + optional digit + dot + digits (E0.04, A.3, M.5)
# These are drawing section references, not fixture codes.
_PAT_SHEET_REF = re.compile(r"^[A-Z]\d?\.\d+$")

# Minimum frequency on floor plans for types whose prefix is NOT in the schedule
_MIN_FREQ_NEW_PREFIX = 3


def run_fixture_discovery(pdf_path: str) -> dict:
    """Classify PDF, detect pages, and discover fixture types (no counting).

    Returns:
        {
            "status": "success" | "error",
            "fixture_types": [str],
            "pages_analyzed": {"lighting_plans": [], "fixture_schedules": [], "unit_plans": []},
            "pattern": "direct_counting" | "unit_multiplication" | None,
            "errors": [str]
        }
    """
    t_start = time.time()
    filename = os.path.basename(pdf_path)
    logger.info("=" * 60)
    logger.info("FIXTURE DISCOVERY START: %s", filename)

    classification, error = _classify_extractability(pdf_path)
    if error:
        return error

    page_result, error = _detect_pages(pdf_path)
    if error:
        return error

    lighting_pages = page_result["lighting_plans"]
    schedule_pages = page_result["fixture_schedules"]
    unit_pages = page_result["unit_plans"]
    pattern = "unit_multiplication" if unit_pages else "direct_counting"

    fixture_types, error = _discover_types(
        pdf_path, lighting_pages, schedule_pages, unit_pages
    )
    if error:
        error["pages_analyzed"] = {
            "lighting_plans": lighting_pages,
            "fixture_schedules": schedule_pages,
            "unit_plans": unit_pages,
        }
        error["pattern"] = pattern
        return error

    total = time.time() - t_start
    logger.info("FIXTURE DISCOVERY COMPLETE: %s — %d types, %.1fs", filename, len(fixture_types), total)
    logger.info("=" * 60)

    return {
        "status": "success",
        "fixture_types": fixture_types,
        "pages_analyzed": {
            "lighting_plans": lighting_pages,
            "fixture_schedules": schedule_pages,
            "unit_plans": unit_pages,
        },
        "pattern": pattern,
        "errors": [],
    }


def _classify_extractability(pdf_path: str) -> tuple[dict, dict | None]:
    """Check if the PDF contains extractable text. Returns (classification, error_response_or_None)."""
    logger.info("Classifying PDF extractability...")
    t0 = time.time()
    classification = classify_pdf(pdf_path)
    logger.info("Extractability check done in %.1fs — extractable=%s", time.time() - t0, classification["extractable"])
    if not classification["extractable"]:
        logger.warning("PIPELINE ABORT: PDF not extractable — %s", classification["error"])
        return classification, {
            "status": "error",
            "fixture_types": [],
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": [classification["error"]],
        }
    return classification, None


def _detect_pages(pdf_path: str) -> tuple[dict, dict | None]:
    """Detect lighting, schedule, and unit pages.

    Strategy (3-tier fallback):
    1. Try parse_sheet_index() for deterministic detection (fast, reliable).
    2. If no sheet index → try detect_lighting_pages() (fast regex scan via fitz).
    3. If neither works → fall back to full LLM page classification.

    Returns (page_result, error_or_None).
    """
    logger.info("Detecting pages...")

    # Tier 1: Try sheet index parsing
    t0 = time.time()
    index_result = parse_sheet_index(pdf_path)
    schedule_pages = index_result["schedule_pages"]
    lighting_pages = index_result["lighting_pages"]
    unit_pages = index_result["unit_pages"]

    if schedule_pages or lighting_pages:
        logger.info(
            "Page detection: Sheet index parsed in %.1fs — schedule=%s, lighting=%s, unit=%s",
            time.time() - t0, schedule_pages, lighting_pages, unit_pages,
        )
    else:
        logger.info("Page detection: No sheet index found, trying deterministic detection...")

    # Tier 2: If sheet index didn't find lighting pages, try fast regex detection
    if not lighting_pages:
        t0 = time.time()
        lighting_pages = detect_lighting_pages(pdf_path)
        if lighting_pages:
            logger.info(
                "Page detection: Deterministic detection in %.1fs — %d lighting pages: %s",
                time.time() - t0, len(lighting_pages), lighting_pages,
            )

    # Tier 3: If still no lighting pages, fall back to full LLM classification
    if not lighting_pages:
        logger.info("Page detection: No pages found deterministically, falling back to LLM...")
        t0 = time.time()
        page_map = classify_pages(pdf_path)
        lighting_pages = page_map["lighting_plans"]
        if not schedule_pages:
            schedule_pages = page_map["fixture_schedules"]
        unit_pages = page_map["unit_plans"]
        logger.info(
            "Page detection: LLM done in %.1fs — lighting=%d, schedule=%d, unit=%d",
            time.time() - t0, len(lighting_pages), len(schedule_pages), len(unit_pages),
        )

    if not lighting_pages:
        logger.warning("PIPELINE ABORT: No lighting plan pages found")
        return {}, {
            "status": "error",
            "fixture_types": [],
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": ["No lighting plan pages identified in the PDF."],
        }

    return {
        "lighting_plans": lighting_pages,
        "fixture_schedules": schedule_pages,
        "unit_plans": unit_pages,
    }, None


def _discover_types(
    pdf_path: str,
    lighting_pages: list[int],
    schedule_pages: list[int],
    unit_pages: list[int] | None = None,
) -> tuple[list[str], dict | None]:
    """Discover fixture types using schedule + floor-plan extraction.

    Strategy:
    1a. Text-extractable schedule pages → pdfplumber + LLM text extraction (high confidence).
    1b. Rasterized schedule pages → vision OCR (medium confidence, hallucination-filtered).
    2.  Extract fixture-code words from lighting + unit pages using pdfplumber.
    3.  Filter vision hallucinations using text schedule + floor plan evidence.
    4.  Merge text schedule + filtered vision + floor plan types, deduplicate.

    Returns (fixture_types, error_or_None).
    """
    logger.info("Discovering fixture types (schedule + floor-plan)...")
    t0 = time.time()
    unit_pages = unit_pages or []

    # --- Step 1a: Text-extractable schedule pages (high confidence) ---
    text_schedule_types = []
    raw_vision_types = []
    vision_types_by_page: dict[int, list[str]] = {}
    if schedule_pages:
        text_pages, raster_pages = _classify_schedule_pages(pdf_path, schedule_pages)
        if text_pages:
            logger.info("  Schedule (text): parsing %d pages: %s", len(text_pages), text_pages)
            result = parse_fixture_schedule(pdf_path, text_pages)
            if result["success"]:
                text_schedule_types = _normalize_schedule_output(
                    [ft["type_code"] for ft in result["fixture_types"]]
                )
                logger.info("  Schedule (text): %d types", len(text_schedule_types))

        # --- Step 1b: Rasterized schedule pages (vision, needs filtering) ---
        # Process each rasterized page individually so we can track per-page
        # prefix appearances for cross-page consensus filtering.
        if raster_pages:
            logger.info("  Schedule (vision): parsing %d rasterized pages individually: %s",
                        len(raster_pages), raster_pages)
            for rp in raster_pages:
                result = parse_fixture_schedule(pdf_path, [rp])
                if result["success"]:
                    page_types = _normalize_schedule_output(
                        [ft["type_code"] for ft in result["fixture_types"]]
                    )
                    vision_types_by_page[rp] = page_types
                    logger.info("  Schedule (vision) page %d: %d types", rp, len(page_types))
                else:
                    vision_types_by_page[rp] = []
            # Flatten all vision types (deduplicated later)
            for types in vision_types_by_page.values():
                raw_vision_types.extend(types)

    # --- Step 2: Floor plan word extraction from lighting + unit pages ---
    scan_pages = sorted(set(lighting_pages + unit_pages))
    logger.info("  Floor plans: scanning %d pages %s for fixture codes...",
                len(scan_pages), scan_pages)
    t1 = time.time()
    words_by_page = extract_pages_words_batch(pdf_path, scan_pages)
    logger.info("  Floor plans: word extraction done in %.1fs", time.time() - t1)

    text_schedule_set = {t.upper() for t in text_schedule_types}
    floor_plan_types = _find_fixture_codes_in_words(words_by_page, text_schedule_set)
    logger.info("  Floor plans: %d candidate types", len(floor_plan_types))

    # --- Step 3: Filter vision hallucinations ---
    filtered_vision = _filter_vision_hallucinations(
        raw_vision_types, text_schedule_types, floor_plan_types
    )
    logger.info("  Vision filtered: %d/%d types kept", len(filtered_vision), len(raw_vision_types))

    # --- Step 4: Merge text schedule + filtered vision + floor plan types ---
    schedule_types = text_schedule_types + filtered_vision
    all_types = _merge_type_sources(schedule_types, floor_plan_types)

    if not all_types:
        logger.warning("  No fixture types found anywhere")
        return [], {
            "status": "error",
            "fixture_types": [],
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": ["No fixture types found in schedule or floor plan pages."],
        }

    logger.info("Type discovery: %d types in %.1fs", len(all_types), time.time() - t0)
    return all_types, None


def _normalize_schedule_output(raw_types: list[str]) -> list[str]:
    """Normalize and filter schedule parser output.

    Applies: leading zero strip (DF01→DF1), fixture code pattern check,
    EM variant handling.
    """
    result = []
    for t in raw_types:
        norm = _normalize_type_code(t)
        upper = norm.upper()
        if _looks_like_fixture_code(upper) or " EM" in upper or "-EM" in upper:
            result.append(norm)
        else:
            logger.debug("  Schedule: dropping non-fixture code: %s", t)
    return result


def _filter_vision_hallucinations(
    vision_types: list[str],
    text_schedule_types: list[str],
    floor_plan_types: list[str],
    vision_types_by_page: dict[int, list[str]] | None = None,
) -> list[str]:
    """Filter hallucination patterns from vision OCR.

    Filters applied:

    1. **Alphabetic suffix detection**: If a base (prefix+number) has 5+
       letter suffix variants (L1A→L1Z), it's a hallucination pattern.
       Keep only A and B suffixes.

    2. **Numeric sequence detection**: Dense runs of 10+ types with same
       prefix (L-401 to L-436) indicate the model filled in a range.
       Keep only types corroborated by floor plans.

    Note: Per-section cap in schedule_parser.py (40 types) handles
    catastrophic hallucination at the source. Cross-page consensus was
    removed because schedule types are listed once per page, making
    prefix-level consensus too aggressive for real types.
    """
    text_set = {_normalize_type_code(t.upper()) for t in text_schedule_types}

    # --- Detect alphabetic suffix sequences ---
    alpha_groups: dict[str, set[str]] = {}  # {base: {suffix_letters}}
    for t in vision_types:
        m = re.match(r'^([A-Z]{1,2}[-.]?\d+)([A-Z])$', t.upper())
        if m:
            alpha_groups.setdefault(m.group(1), set()).add(m.group(2))

    # Bases with 5+ letter variants are suspicious
    suspect_alpha = {base for base, suffixes in alpha_groups.items() if len(suffixes) >= 5}
    if suspect_alpha:
        logger.info("  Vision filter: suspect alphabetic bases: %s", sorted(suspect_alpha))

    # --- Detect numeric sequence hallucinations ---
    # Group types by prefix+separator pattern: e.g., "L-" → {401, 402, ..., 436}
    # Dense numeric runs (10+ members) indicate the model saw a few real codes
    # and filled in the range.
    floor_set = {_normalize_type_code(t.upper()) for t in floor_plan_types}
    numeric_groups: dict[str, set[int]] = {}  # {"L-": {401, 402, ...}}
    numeric_type_map: dict[str, tuple[str, int]] = {}  # {"L-411": ("L-", 411)}
    for t in vision_types:
        upper = t.upper()
        m = re.match(r'^([A-Z]{1,2}[-.]?)(\d+)$', upper)
        if m:
            prefix_part = m.group(1)
            num = int(m.group(2))
            numeric_groups.setdefault(prefix_part, set()).add(num)
            numeric_type_map[upper] = (prefix_part, num)

    suspect_numeric: set[str] = set()  # prefix_parts with dense numeric runs
    for prefix_part, numbers in numeric_groups.items():
        if len(numbers) >= 10:
            # Check density: span vs count
            span = max(numbers) - min(numbers) + 1
            density = len(numbers) / span if span > 0 else 0
            if density >= 0.5:  # More than half the range is filled
                suspect_numeric.add(prefix_part)
                logger.info("  Vision filter: suspect numeric sequence: %s (%d types in range %d–%d, density=%.0f%%)",
                            prefix_part, len(numbers), min(numbers), max(numbers), density * 100)

    # --- Filter ---
    filtered = []
    seen = set()
    for t in vision_types:
        upper = t.upper()
        norm = _normalize_type_code(upper)

        # Deduplicate within vision types
        if norm in seen:
            continue
        seen.add(norm)
        seen.add(upper)

        # Skip types already in text schedule (avoid duplicates)
        if norm in text_set or upper in text_set:
            continue

        # Alphabetic suffix hallucination: keep only A and B variants
        m_alpha = re.match(r'^([A-Z]{1,2}[-.]?\d+)([A-Z])$', upper)
        if m_alpha and m_alpha.group(1) in suspect_alpha:
            suffix = m_alpha.group(2)
            if suffix not in ('A', 'B'):
                logger.debug("  Vision filter: dropping %s (alphabetic hallucination)", t)
                continue

        # Numeric sequence hallucination: only keep if corroborated by
        # text schedule or floor plans
        if upper in numeric_type_map:
            prefix_part, _ = numeric_type_map[upper]
            if prefix_part in suspect_numeric:
                if norm not in floor_set and upper not in floor_set:
                    logger.debug("  Vision filter: dropping %s (numeric hallucination, not on floor plans)", t)
                    continue

        filtered.append(t)

    dropped = len(vision_types) - len(filtered)
    if dropped:
        logger.info("  Vision filter: dropped %d/%d types", dropped, len(vision_types))

    return filtered


def run_pipeline(pdf_path: str, output_dir: str = "data/output") -> dict:
    """Run the full extraction pipeline on a PDF.

    Returns:
        {
            "status": "success" | "error",
            "fixture_counts": [{"type", "quantity", "confidence", "note"}],
            "csv_path": str | None,
            "pages_analyzed": {"lighting_plans": [], "fixture_schedules": [], "unit_plans": []},
            "pattern": "direct_counting" | "unit_multiplication",
            "errors": [str]
        }
    """
    pipeline_start = time.time()
    errors = []
    filename = os.path.basename(pdf_path)
    logger.info("=" * 60)
    logger.info("PIPELINE START: %s", filename)

    _, error = _classify_extractability(pdf_path)
    if error:
        return error

    page_result, error = _detect_pages(pdf_path)
    if error:
        return error

    lighting_pages = page_result["lighting_plans"]
    schedule_pages = page_result["fixture_schedules"]
    unit_pages = page_result["unit_plans"]
    pattern = "unit_multiplication" if unit_pages else "direct_counting"
    logger.info("Counting pattern: %s", pattern)

    fixture_types, error = _discover_types(
        pdf_path, lighting_pages, schedule_pages, unit_pages
    )
    if error:
        error["pages_analyzed"] = {
            "lighting_plans": lighting_pages,
            "fixture_schedules": schedule_pages,
            "unit_plans": unit_pages,
        }
        error["pattern"] = pattern
        return error

    logger.info("Counting fixtures...")
    t0 = time.time()
    if pattern == "direct_counting":
        fixture_counts = _direct_counting(pdf_path, lighting_pages, fixture_types)
    else:
        fixture_counts = _unit_multiplication_counting(
            pdf_path, unit_pages, lighting_pages, fixture_types
        )
    logger.info("Counting done in %.1fs — %d fixture types with counts", time.time() - t0, len(fixture_counts))

    logger.info("Writing CSV output...")
    t0 = time.time()
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    basename = re.sub(r'[^\w\-]', '_', basename)[:50]
    csv_path = os.path.join(output_dir, f"{basename}_counts.csv")
    write_csv(fixture_counts, csv_path)
    logger.info("CSV written in %.1fs — %s", time.time() - t0, csv_path)

    total = time.time() - pipeline_start
    logger.info("PIPELINE COMPLETE: %s — %d fixtures, %.1fs total", filename, len(fixture_counts), total)
    logger.info("=" * 60)

    return {
        "status": "success",
        "fixture_counts": fixture_counts,
        "csv_path": csv_path,
        "pages_analyzed": {
            "lighting_plans": lighting_pages,
            "fixture_schedules": schedule_pages,
            "unit_plans": unit_pages,
        },
        "pattern": pattern,
        "errors": errors,
    }


def _classify_schedule_pages(
    pdf_path: str, schedule_pages: list[int]
) -> tuple[list[int], list[int]]:
    """Split schedule pages into text-extractable vs rasterized."""
    page_texts = extract_pages_text_batch(pdf_path, schedule_pages)
    text_pages = []
    raster_pages = []
    for idx in schedule_pages:
        char_count = len(page_texts.get(idx, ""))
        if char_count >= SCHEDULE_TEXT_THRESHOLD:
            text_pages.append(idx)
        else:
            raster_pages.append(idx)
            logger.info("  Schedule page %d: %d chars — rasterized", idx, char_count)
    return text_pages, raster_pages


def _looks_like_fixture_code(word: str) -> bool:
    """Check if a word matches generic fixture code patterns.

    Requires at least one letter and one digit (letter-only codes like GA, XA
    are only accepted from schedule pages, not floor plan scanning).
    Rejects room numbers (A103) and sheet references (E0.04).
    """
    if not word or len(word) < 2 or len(word) > 12:
        return False
    if word in EXCLUDE_WORDS:
        return False
    if not word[0].isalpha():
        return False
    if not any(c.isdigit() for c in word):
        return False
    # Reject sheet/section references: E0.04, A.3, etc.
    if _PAT_SHEET_REF.match(word):
        return False
    return any(p.match(word) for p in _FIXTURE_PATTERNS)


def _normalize_type_code(code: str) -> str:
    """Normalize a fixture type code.

    - Strip leading zeros in the numeric part: DF01 → DF1, F05 → F5
    - But preserve multi-digit numbers: LT-101 stays LT-101
    """
    # Match letter prefix + optional separator + zero-padded single digit
    m = re.match(r'^([A-Z]{1,4}[-.]?)0(\d)([A-Z]?)$', code)
    if m:
        return m.group(1) + m.group(2) + m.group(3)
    return code


def _find_fixture_codes_in_words(
    words_by_page: dict[int, list[dict]],
    schedule_type_set: set[str],
) -> list[str]:
    """Extract fixture type candidates from pdfplumber word data.

    Uses pattern matching, EM adjacency merging, normalization, and
    frequency-based filtering. The key insight for distinguishing fixture
    codes from room numbers: fixture labels appear MULTIPLE times on a
    single page (many fixtures of same type), while room numbers appear
    at most once per page (each room is unique).
    """
    # Count codes per-page and total
    per_page_counts: dict[str, Counter] = {}  # {code: Counter({page: count})}
    for page_idx, page_words in words_by_page.items():
        for w in page_words:
            text = w["text"].strip().upper()
            if _looks_like_fixture_code(text):
                normalized = _normalize_type_code(text)
                if normalized not in per_page_counts:
                    per_page_counts[normalized] = Counter()
                per_page_counts[normalized][page_idx] += 1

    # Compute total, max-single-page, and page-spread frequencies
    code_total: Counter = Counter()
    code_max_page: dict[str, int] = {}
    code_page_spread: dict[str, int] = {}
    for code, page_counter in per_page_counts.items():
        code_total[code] = sum(page_counter.values())
        code_max_page[code] = max(page_counter.values())
        code_page_spread[code] = len(page_counter)

    # Find EM variants via spatial adjacency (e.g., "LP1" + "EM" → "LP1 EM")
    em_variants = _find_em_variants(words_by_page)
    for em_type in em_variants:
        code_total[em_type] += 1
        code_max_page.setdefault(em_type, 1)

    # Find compound types (e.g., "AS1/AS2" as one token)
    compound_types = _find_compound_types(words_by_page)
    for ct in compound_types:
        code_total[ct] += 1
        code_max_page.setdefault(ct, 1)

    # Build prefix sets from schedule types
    schedule_prefixes = set()
    for t in schedule_type_set:
        m = re.match(r'^([A-Z]+)', t)
        if m:
            schedule_prefixes.add(m.group(1))

    # --- Self-bootstrapping anchor approach ---
    # Step A: Find anchor types and build prefix sets.
    # Any code with max_page >= _MIN_FREQ_NEW_PREFIX becomes an anchor.
    # Room numbers are filtered separately by pattern and page-spread heuristics.
    anchor_prefixes = set(schedule_prefixes)
    for code in code_total:
        max_page = code_max_page.get(code, 0)
        m = re.match(r'^([A-Z]+)', code.upper())
        if not m:
            continue
        prefix = m.group(1)
        if max_page >= _MIN_FREQ_NEW_PREFIX:
            anchor_prefixes.add(prefix)

    logger.info("  Floor plan anchor prefixes: %s", sorted(anchor_prefixes))

    # Step B: Accept codes using tiered criteria
    candidates = []
    for code in code_total:
        upper = code.upper()
        if upper in schedule_type_set:
            continue  # Already in schedule, will be included via merge
        m = re.match(r'^([A-Z]+)', upper)
        prefix = m.group(1) if m else ""
        max_page = code_max_page.get(code, 0)
        total = code_total[code]
        page_spread = code_page_spread.get(code, 0)

        # Room/unit number filter:
        # 4+ digits with single-letter prefix = almost always room/apt numbers (A2603, A4001)
        if (len(prefix) == 1 and re.match(r'^[A-Z]\d{4,}', upper)
                and prefix not in schedule_prefixes):
            logger.debug("  Floor plan: dropping %s (likely room number: 1-letter + 4+ digits)", code)
            continue
        # 3 digits with single-letter prefix, no letter suffix = likely room number (A111, A302)
        # unless high per-page frequency (L500 appears many times on lighting plans)
        if (len(prefix) == 1 and re.match(r'^[A-Z]\d{3}$', upper)
                and max_page < _MIN_FREQ_NEW_PREFIX
                and prefix not in schedule_prefixes):
            logger.debug("  Floor plan: dropping %s (likely room number: 1-letter + 3 digits, max_page=%d)",
                         code, max_page)
            continue

        # Room number heuristic: single-letter prefix codes that appear
        # across many pages but few times per page are likely room/unit numbers
        if len(prefix) == 1 and page_spread >= 3 and max_page <= 2:
            if prefix not in schedule_prefixes:
                logger.debug("  Floor plan: dropping %s (likely room number: spread=%d, max_page=%d)",
                             code, page_spread, max_page)
                continue

        if prefix in schedule_prefixes:
            # Known from schedule: accept at any frequency
            candidates.append(code)
        elif max_page >= _MIN_FREQ_NEW_PREFIX:
            # High per-page frequency: strong fixture signal
            candidates.append(code)
        elif prefix in anchor_prefixes and len(prefix) >= 2 and total >= 1:
            # 2-letter+ anchor match: accept even single occurrence
            candidates.append(code)
        elif prefix in anchor_prefixes and total >= 2:
            # 1-letter anchor match: need at least 2 total occurrences
            candidates.append(code)
        else:
            logger.debug("  Floor plan: dropping %s (total=%d, max_page=%d, prefix=%s)",
                         code, total, max_page, prefix)

    return candidates


def _find_em_variants(words_by_page: dict[int, list[dict]]) -> list[str]:
    """Find space-separated EM variants by spatial adjacency.

    Looks for "EM" words near fixture codes on the same line.
    Returns deduplicated list like ["LP1 EM", "LR3 EM"].
    """
    found = set()
    for page_idx, page_words in words_by_page.items():
        # Build index of EM word positions on this page
        em_positions = []
        for i, w in enumerate(page_words):
            if w["text"].strip().upper() == "EM":
                em_positions.append((i, w))

        if not em_positions:
            continue

        for em_idx, em_word in em_positions:
            # Search nearby preceding words (within 5 positions, same line, close x)
            for j in range(max(0, em_idx - 5), em_idx):
                prev = page_words[j]
                prev_text = prev["text"].strip().upper()
                y_diff = abs(prev["y0"] - em_word["y0"])
                x_gap = em_word["x0"] - prev["x1"]
                if y_diff < 5 and 0 < x_gap < 50 and _looks_like_fixture_code(prev_text):
                    normalized = _normalize_type_code(prev_text)
                    found.add(f"{normalized} EM")
                    break
    return list(found)


def _find_compound_types(words_by_page: dict[int, list[dict]]) -> list[str]:
    """Find compound types like AS1/AS2 that might be extracted as one token."""
    found = set()
    for page_idx, page_words in words_by_page.items():
        for w in page_words:
            text = w["text"].strip().upper()
            if _PAT_COMPOUND.match(text):
                found.add(text)
    return list(found)


def _merge_type_sources(
    schedule_types: list[str], floor_plan_types: list[str]
) -> list[str]:
    """Merge schedule types (high confidence) with floor plan types.

    Schedule types come first; floor plan types are appended if not already present.
    Deduplication is case-insensitive.
    """
    seen = set()
    result = []
    for t in schedule_types:
        upper = t.upper()
        if upper not in seen:
            seen.add(upper)
            result.append(t)
    for t in sorted(floor_plan_types):
        upper = t.upper()
        if upper not in seen:
            # Also check normalized form to avoid DF01 + DF1 duplicates
            norm = _normalize_type_code(upper)
            if norm not in seen:
                seen.add(upper)
                seen.add(norm)
                result.append(t)
    return result


def _direct_counting(
    pdf_path: str, lighting_pages: list[int], fixture_types: list[str]
) -> list[dict]:
    """Direct counting pattern: count fixture labels on lighting plan pages."""
    # Stage 4a: pdfplumber spatial count
    logger.info("  [4a] pdfplumber spatial counting on pages %s...", lighting_pages)
    t0 = time.time()
    pdfplumber_counts = count_fixtures_multi_page(pdf_path, lighting_pages, fixture_types)
    logger.info("  [4a] Done in %.1fs — %d types counted", time.time() - t0, len(pdfplumber_counts))

    # Stage 4b: LLM verification count
    logger.info("  [4b] LLM vision counting on pages %s...", lighting_pages)
    t0 = time.time()
    llm_counts = count_fixtures_with_llm_multi_page(pdf_path, lighting_pages, fixture_types)
    logger.info("  [4b] Done in %.1fs — %d types counted", time.time() - t0, len(llm_counts))

    # Stage 4c: Reconcile
    logger.info("  [4c] Reconciling pdfplumber vs LLM counts...")
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=CONFIDENCE_THRESHOLD)
    high = sum(1 for r in result if r.get("confidence") == "high")
    logger.info("  [4c] Done — %d high confidence, %d review", high, len(result) - high)
    return result


def _unit_multiplication_counting(
    pdf_path: str,
    unit_pages: list[int],
    lighting_pages: list[int],
    fixture_types: list[str],
) -> list[dict]:
    """Unit multiplication pattern: count per unit, then multiply by instances.

    TODO: Full implementation needs to:
    1. Parse each unit plan to get fixtures-per-unit-type
    2. Count unit instances on floor plan pages
    3. Multiply and sum
    For now, we count all pages together as a starting point.
    """
    all_pages = unit_pages + lighting_pages
    logger.info("  Unit multiplication — counting across %d pages (unit=%d, lighting=%d)", len(all_pages), len(unit_pages), len(lighting_pages))

    # Stage 4a: pdfplumber count across all relevant pages
    logger.info("  [4a] pdfplumber spatial counting on pages %s...", all_pages)
    t0 = time.time()
    pdfplumber_counts = count_fixtures_multi_page(pdf_path, all_pages, fixture_types)
    logger.info("  [4a] Done in %.1fs — %d types counted", time.time() - t0, len(pdfplumber_counts))

    # Stage 4b: LLM count across all relevant pages
    logger.info("  [4b] LLM vision counting on pages %s...", all_pages)
    t0 = time.time()
    llm_counts = count_fixtures_with_llm_multi_page(pdf_path, all_pages, fixture_types)
    logger.info("  [4b] Done in %.1fs — %d types counted", time.time() - t0, len(llm_counts))

    # Stage 4c: Reconcile
    logger.info("  [4c] Reconciling pdfplumber vs LLM counts...")
    result = reconcile_counts(pdfplumber_counts, llm_counts, threshold=CONFIDENCE_THRESHOLD)
    high = sum(1 for r in result if r.get("confidence") == "high")
    logger.info("  [4c] Done — %d high confidence, %d review", high, len(result) - high)
    return result
