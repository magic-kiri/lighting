import os
import re
from app.stages.classifier import classify_pdf
from app.stages.page_classifier import classify_pages
from app.stages.schedule_parser import parse_fixture_schedule
from app.stages.counter import count_fixtures_multi_page
from app.stages.llm_counter import count_fixtures_with_llm_multi_page
from app.stages.reconciler import reconcile_counts, write_csv
from app.config import CONFIDENCE_THRESHOLD


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
    errors = []

    # --- Stage 1: PDF Classification ---
    classification = classify_pdf(pdf_path)
    if not classification["extractable"]:
        return {
            "status": "error",
            "fixture_counts": [],
            "csv_path": None,
            "pages_analyzed": {},
            "pattern": None,
            "errors": [classification["error"]],
        }

    # --- Stage 2: Page Classification ---
    page_map = classify_pages(pdf_path)
    lighting_pages = page_map["lighting_plans"]
    schedule_pages = page_map["fixture_schedules"]
    unit_pages = page_map["unit_plans"]

    if not lighting_pages:
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

    # --- Stage 3: Fixture Schedule ---
    if schedule_pages:
        schedule_result = parse_fixture_schedule(pdf_path, schedule_pages)
    else:
        schedule_result = {"success": False, "fixture_types": [], "error": "No schedule pages found."}

    if not schedule_result["success"]:
        errors.append(schedule_result["error"])
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

    # --- Stage 4: Counting ---
    if pattern == "direct_counting":
        fixture_counts = _direct_counting(pdf_path, lighting_pages, fixture_types)
    else:
        fixture_counts = _unit_multiplication_counting(
            pdf_path, unit_pages, lighting_pages, fixture_types
        )

    # --- Stage 5: Output ---
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    basename = re.sub(r'[^\w\-]', '_', basename)[:50]
    csv_path = os.path.join(output_dir, f"{basename}_counts.csv")
    write_csv(fixture_counts, csv_path)

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
    pdfplumber_counts = count_fixtures_multi_page(pdf_path, lighting_pages, fixture_types)

    # Stage 4b: LLM verification count
    llm_counts = count_fixtures_with_llm_multi_page(pdf_path, lighting_pages, fixture_types)

    # Stage 4c: Reconcile
    return reconcile_counts(pdfplumber_counts, llm_counts, threshold=CONFIDENCE_THRESHOLD)


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

    # Stage 4a: pdfplumber count across all relevant pages
    pdfplumber_counts = count_fixtures_multi_page(pdf_path, all_pages, fixture_types)

    # Stage 4b: LLM count across all relevant pages
    llm_counts = count_fixtures_with_llm_multi_page(pdf_path, all_pages, fixture_types)

    # Stage 4c: Reconcile
    return reconcile_counts(pdfplumber_counts, llm_counts, threshold=CONFIDENCE_THRESHOLD)
