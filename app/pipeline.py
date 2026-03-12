import logging
import os
import re
import time
from app.stages.classifier import classify_pdf
from app.stages.page_classifier import classify_pages
from app.stages.schedule_parser import parse_fixture_schedule
from app.stages.counter import count_fixtures_multi_page
from app.stages.llm_counter import count_fixtures_with_llm_multi_page
from app.stages.reconciler import reconcile_counts, write_csv
from app.config import CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)


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

    # --- Stage 2: Page Classification ---
    logger.info("[Stage 2/5] Classifying pages (LLM)...")
    t0 = time.time()
    page_map = classify_pages(pdf_path)
    lighting_pages = page_map["lighting_plans"]
    schedule_pages = page_map["fixture_schedules"]
    unit_pages = page_map["unit_plans"]
    other_pages = page_map["other"]
    logger.info(
        "[Stage 2/5] Done in %.1fs — lighting=%d, schedule=%d, unit=%d, other=%d pages",
        time.time() - t0, len(lighting_pages), len(schedule_pages), len(unit_pages), len(other_pages),
    )
    if lighting_pages:
        logger.info("  Lighting plan pages (0-indexed): %s", lighting_pages)
    if schedule_pages:
        logger.info("  Fixture schedule pages (0-indexed): %s", schedule_pages)
    if unit_pages:
        logger.info("  Unit plan pages (0-indexed): %s", unit_pages)
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
            "pages_analyzed": page_map,
            "pattern": None,
            "errors": ["No lighting plan pages identified in the PDF."],
        }

    # Detect counting pattern
    pattern = "unit_multiplication" if unit_pages else "direct_counting"
    logger.info("Counting pattern: %s", pattern)

    # --- Stage 3: Fixture Schedule ---
    logger.info("[Stage 3/5] Parsing fixture schedule...")
    t0 = time.time()
    if schedule_pages:
        logger.info("  Parsing schedule from pages (0-indexed): %s", schedule_pages)
        schedule_result = parse_fixture_schedule(pdf_path, schedule_pages)
    else:
        logger.warning("  No schedule pages identified by LLM in Stage 2.")
        logger.warning("  This can happen when the fixture schedule is rasterized (image-based) rather than text.")
        logger.warning("  The LLM may not have classified any page as FIXTURE_SCHEDULE.")
        schedule_result = {"success": False, "fixture_types": [], "error": "No schedule pages found. The LLM did not classify any page as FIXTURE_SCHEDULE. The schedule may be rasterized (image-based)."}

    if not schedule_result["success"]:
        logger.warning("[Stage 3/5] Failed in %.1fs — %s", time.time() - t0, schedule_result["error"])
        errors.append(schedule_result["error"])
        logger.warning("PIPELINE ABORT at Stage 3: Cannot proceed without fixture types from schedule.")
        logger.warning("  Lighting pages found: %s", lighting_pages)
        logger.warning("  Schedule pages found: %s", schedule_pages)
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
            "errors": errors,
        }

    fixture_types = [ft["type_code"] for ft in schedule_result["fixture_types"]]
    logger.info("[Stage 3/5] Done in %.1fs — %d fixture types found: %s", time.time() - t0, len(fixture_types), fixture_types[:10])

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
