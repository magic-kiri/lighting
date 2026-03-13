import logging
import os
import re
import time
from collections import Counter
from app.stages.classifier import classify_pdf
from app.stages.page_classifier import classify_pages, detect_lighting_pages
from app.stages.schedule_parser import parse_fixture_schedule
from app.stages.counter import count_fixtures_multi_page, normalize_fixture_code
from app.stages.llm_counter import count_fixtures_with_llm_multi_page
from app.stages.reconciler import reconcile_counts, write_csv
from app.config import CONFIDENCE_THRESHOLD
from app.utils.pdf_utils import extract_page_words

logger = logging.getLogger(__name__)

# Pattern for discovering fixture type codes from floor plan pages.
# Uses known lighting fixture prefixes to avoid false positives from
# sheet numbers (E-211), sensors (OS3), cables (CAT6E), etc.
_FIXTURE_TYPE_RE = re.compile(
    r'^('
    r'D\d+[A-Z]?'       # D1A, D1B, D2 (downlights)
    r'|L\d+[A-Z]?'      # L1A, L2A, L5, L6 (linear)
    r'|L-\d+'           # L-8, L-22 (linear with dash)
    r'|DF\d+'           # DF01, DF3 (decorative fixtures)
    r'|X\d+'            # X1 (exit signs)
    r'|B\d+[A-Z]?'     # B1, B2, B5
    r'|U\d+[A-Z]?'     # U1, U2
    r')(-EM)?$'
)


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

    # --- Stage 1: PDF Classification ---
    logger.info("[Stage 1/5] Classifying PDF extractability...")
    t0 = time.time()
    classification = classify_pdf(pdf_path)
    logger.info("[Stage 1/5] Done in %.1fs — extractable=%s", time.time() - t0, classification["extractable"])
    if not classification["extractable"]:
        logger.warning("PIPELINE ABORT: PDF not extractable — %s", classification["error"])
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": [classification["error"]],
        }

    # --- Stage 2: Page Detection ---
    # Try deterministic detection first (fast, no LLM API call)
    logger.info("[Stage 2/5] Detecting lighting pages...")
    t0 = time.time()
    lighting_pages = detect_lighting_pages(pdf_path)
    schedule_pages = []
    unit_pages = []

    if lighting_pages:
        logger.info(
            "[Stage 2/5] Deterministic detection done in %.1fs — %d lighting pages: %s",
            time.time() - t0, len(lighting_pages), lighting_pages,
        )
    else:
        # Fallback: LLM classification
        logger.info("[Stage 2/5] No pages found deterministically, falling back to LLM classification...")
        t0 = time.time()
        page_map = classify_pages(pdf_path)
        lighting_pages = page_map["lighting_plans"]
        schedule_pages = page_map["fixture_schedules"]
        unit_pages = page_map["unit_plans"]
        other_pages = page_map["other"]
        logger.info(
            "[Stage 2/5] LLM done in %.1fs — lighting=%d, schedule=%d, unit=%d, other=%d pages",
            time.time() - t0, len(lighting_pages), len(schedule_pages), len(unit_pages), len(other_pages),
        )
        if lighting_pages:
            logger.info("  Lighting plan pages (0-indexed): %s", lighting_pages)
        # Log raw classifications for debugging
        for item in page_map.get("raw_classifications", []):
            cat = item.get("category", "?")
            reason = item.get("reason", "")
            if cat != "OTHER":
                logger.info("  Page %d → %s (%s)", item.get("page", 0), cat, reason)

    if not lighting_pages:
        logger.warning("PIPELINE ABORT: No lighting plan pages found")
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": ["No lighting plan pages identified in the PDF."],
        }

    # Detect counting pattern
    pattern = "unit_multiplication" if unit_pages else "direct_counting"
    logger.info("Counting pattern: %s", pattern)

    # --- Stage 3: Fixture Type Discovery ---
    logger.info("[Stage 3/5] Discovering fixture types...")
    t0 = time.time()
    fixture_types = []

    # Try schedule first if we have schedule pages
    if schedule_pages:
        logger.info("  Parsing schedule from pages (0-indexed): %s", schedule_pages)
        schedule_result = parse_fixture_schedule(pdf_path, schedule_pages)
        if schedule_result["success"]:
            fixture_types = [ft["type_code"] for ft in schedule_result["fixture_types"]]
            logger.info("  Found %d types from schedule: %s", len(fixture_types), fixture_types[:10])
        else:
            logger.warning("  Schedule parse failed: %s", schedule_result["error"])

    # Fallback: discover types directly from lighting plan pages
    if not fixture_types:
        logger.info("  No schedule available — discovering types from floor plans...")
        fixture_types = _discover_fixture_types_from_pages(pdf_path, lighting_pages)
        logger.info("  Discovered %d types from floor plans: %s", len(fixture_types), fixture_types[:20])

    if not fixture_types:
        logger.warning("[Stage 3/5] Failed — no fixture types found anywhere")
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {
                "lighting_plans": lighting_pages,
                "fixture_schedules": schedule_pages,
                "unit_plans": unit_pages,
            },
            "pattern": pattern,
            "errors": ["No fixture types found on any page."],
        }

    logger.info("[Stage 3/5] Done in %.1fs — %d fixture types", time.time() - t0, len(fixture_types))

    # --- Stage 4: Counting ---
    logger.info("[Stage 4/5] Counting fixtures...")
    t0 = time.time()
    if pattern == "direct_counting":
        fixture_counts = _direct_counting(pdf_path, lighting_pages, fixture_types)
    else:
        fixture_counts = _unit_multiplication_counting(
            pdf_path, unit_pages, lighting_pages, fixture_types
        )
    logger.info("[Stage 4/5] Done in %.1fs — %d fixture types with counts", time.time() - t0, len(fixture_counts))

    # --- Stage 5: Output ---
    logger.info("[Stage 5/5] Writing CSV output...")
    t0 = time.time()
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    basename = re.sub(r'[^\w\-]', '_', basename)[:50]
    csv_path = os.path.join(output_dir, f"{basename}_counts.csv")
    write_csv(fixture_counts, csv_path)
    logger.info("[Stage 5/5] Done in %.1fs — %s", time.time() - t0, csv_path)

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


def _discover_fixture_types_from_pages(pdf_path: str, page_indices: list[int]) -> list[str]:
    """Discover fixture type codes from floor plan pages using pdfplumber.

    Scans all words on the given pages, filters by fixture code patterns,
    normalizes codes (DF01→DF1), and returns unique types sorted by frequency.
    """
    all_codes = Counter()
    for page_idx in page_indices:
        words = extract_page_words(pdf_path, page_idx)
        for w in words:
            text = w["text"].strip().upper()
            if len(text) < 2 or len(text) > 10:
                continue
            if not _FIXTURE_TYPE_RE.match(text):
                continue
            normalized = normalize_fixture_code(text)
            all_codes[normalized] += 1

    return [code for code, _ in all_codes.most_common()]


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
