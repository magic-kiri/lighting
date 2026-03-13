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
from app.config import CONFIDENCE_THRESHOLD
from app.utils.pdf_utils import (
    parse_sheet_index,
    extract_pages_words_batch,
)

logger = logging.getLogger(__name__)


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

    fixture_types, error = _discover_types(pdf_path, lighting_pages, schedule_pages)
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
    pdf_path: str, lighting_pages: list[int], schedule_pages: list[int]
) -> tuple[list[str], dict | None]:
    """Discover fixture types using the 4-step pipeline.

    Steps:
    1. Schedule pages already identified by _detect_pages()
    2. Extract schedule content (pdfplumber or LLM vision) — handled by schedule_parser
    3. LLM extracts fixture types from schedule text — handled by schedule_parser
    4. Cross-validate against floor plan words

    Returns (fixture_types, error_or_None).
    """
    logger.info("Discovering fixture types...")
    t0 = time.time()
    fixture_types = []

    # Steps 2-3: Parse fixture schedule (text extraction + LLM type extraction)
    if schedule_pages:
        logger.info("  Parsing schedule from pages (0-indexed): %s", schedule_pages)
        schedule_result = parse_fixture_schedule(pdf_path, schedule_pages)
        if schedule_result["success"]:
            fixture_types = [ft["type_code"] for ft in schedule_result["fixture_types"]]
            logger.info("  Found %d types from schedule: %s", len(fixture_types), fixture_types[:20])
        else:
            logger.warning("  Schedule parse failed: %s", schedule_result["error"])

    # Fallback: if no schedule types, discover from floor plan words
    if not fixture_types:
        logger.info("  No schedule types found — falling back to floor plan discovery...")
        floor_words = _extract_floor_plan_words(pdf_path, lighting_pages[:3])
        seen = set()
        for word in floor_words:
            if word not in EXCLUDE_WORDS and re.match(r'^[A-Z]+[-]?\d', word):
                if word not in seen:
                    fixture_types.append(word)
                    seen.add(word)
        if fixture_types:
            logger.info("  Discovered %d types from floor plans: %s", len(fixture_types), fixture_types[:20])

    if not fixture_types:
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

    # Step 4: Cross-validate against floor plan words
    logger.info("  Cross-validating against %d lighting plan pages...", len(lighting_pages))
    t1 = time.time()
    floor_plan_words = _extract_floor_plan_words(pdf_path, lighting_pages[:3])
    fixture_types = _cross_validate_types(fixture_types, floor_plan_words)
    logger.info("  Cross-validation done in %.1fs — %d final types", time.time() - t1, len(fixture_types))

    logger.info("Type discovery: Done in %.1fs — %d fixture types", time.time() - t0, len(fixture_types))
    return fixture_types, None


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

    fixture_types, error = _discover_types(pdf_path, lighting_pages, schedule_pages)
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


def _extract_floor_plan_words(pdf_path: str, page_indices: list[int]) -> list[str]:
    """Extract short uppercase words from floor plan pages for cross-validation."""
    if not page_indices:
        return []
    words_by_page = extract_pages_words_batch(pdf_path, page_indices)
    all_words = []
    for idx in page_indices:
        for w in words_by_page.get(idx, []):
            text = w["text"].strip().upper()
            if 2 <= len(text) <= 10:
                all_words.append(text)
    return all_words


def _cross_validate_types(
    schedule_types: list[str], floor_plan_words: list[str]
) -> list[str]:
    """Cross-validate schedule types against floor plan words.

    Checks which schedule types appear on floor plans.
    Also detects potential missed types that share a prefix (2+ letters) with
    known schedule types, filtering out room/drawing numbers.

    Returns combined list of types (schedule types + floor-plan-only candidates).
    """
    if not floor_plan_words:
        return schedule_types

    # Build prefix set from schedule types — require 2+ letter prefixes
    # to avoid matching room numbers (A103) against single-letter prefixes (A from AL1)
    prefixes = set()
    for t in schedule_types:
        m = re.match(r'^([A-Z]{2,})', t.upper())
        if m:
            prefixes.add(m.group(1))

    # Find floor plan words that match schedule type prefixes
    schedule_set = {t.upper() for t in schedule_types}
    candidates = set()
    word_counts = Counter(floor_plan_words)

    for word, count in word_counts.items():
        if word in schedule_set:
            continue
        if word in EXCLUDE_WORDS:
            continue
        # Must be short enough to be a fixture code (not a long description)
        if len(word) > 8:
            continue
        # Check if word shares a 2+ letter prefix with any schedule type
        m = re.match(r'^([A-Z]{2,})', word)
        if m and m.group(1) in prefixes:
            # Must look like a fixture code: letters followed by digit or paren
            if re.match(r'^[A-Z]{2,}[-]?\d', word) or re.match(r'^[A-Z]+\(', word):
                candidates.add(word)

    if candidates:
        logger.info("  Cross-validation: %d floor-plan-only candidates: %s",
                     len(candidates), sorted(candidates))

    # Combine: schedule types first, then floor-plan-only candidates
    result = list(schedule_types)
    for c in sorted(candidates):
        if c not in schedule_set:
            result.append(c)

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
