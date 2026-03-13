import logging
import re
import time
import pdfplumber
import fitz

logger = logging.getLogger(__name__)


def get_pdf_metadata(pdf_path: str) -> dict:
    """Extract PDF metadata (producer, creator, etc.)."""
    with pdfplumber.open(pdf_path) as pdf:
        meta = pdf.metadata or {}
    return {k.lower(): v for k, v in meta.items() if v}


def get_page_count(pdf_path: str) -> int:
    """Return total number of pages."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def extract_page_text(pdf_path: str, page_index: int) -> list[dict]:
    """Extract all characters with positions from a page using pdfplumber.
    Returns list of dicts with keys: text, x0, y0, x1, y1, fontname, size
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        chars = page.chars
    return [
        {
            "text": c.get("text", ""),
            "x0": c.get("x0", 0),
            "y0": c.get("top", 0),
            "x1": c.get("x1", 0),
            "y1": c.get("bottom", 0),
            "fontname": c.get("fontname", ""),
            "size": c.get("size", 0),
        }
        for c in chars
    ]


def extract_page_words(pdf_path: str, page_index: int) -> list[dict]:
    """Extract words (grouped characters) with positions from a page.
    Returns list of dicts with keys: text, x0, y0, x1, y1
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    return [
        {
            "text": w.get("text", ""),
            "x0": w.get("x0", 0),
            "y0": w.get("top", 0),
            "x1": w.get("x1", 0),
            "y1": w.get("bottom", 0),
        }
        for w in words
    ]


def extract_page_full_text(pdf_path: str, page_index: int) -> str:
    """Extract plain text from a page."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        return page.extract_text() or ""


def extract_all_page_titles(pdf_path: str) -> dict[int, str]:
    """Extract short title text from every page using fitz (PyMuPDF) for speed.
    Returns {page_index: title_text} for all pages.

    Uses fitz instead of pdfplumber because title block text uses standard
    TrueType fonts that fitz handles fine — the CID/Identity-H advantage of
    pdfplumber only matters for fixture label counting, not page classification.
    fitz is ~100x faster (~4s vs ~350s for 173 pages).
    """
    t0 = time.time()
    titles = {}
    doc = fitz.open(pdf_path)
    page_count = doc.page_count
    logger.info("Opened PDF (%d pages), extracting all titles via fitz...", page_count)
    for i in range(page_count):
        text = doc[i].get_text()
        titles[i] = text[:500].strip() if text else "(no text)"
        if (i + 1) % 25 == 0 or i == page_count - 1:
            logger.info("  Extracted %d/%d pages (%.1fs)", i + 1, page_count, time.time() - t0)
    doc.close()
    return titles


def classify_pdf_fast(pdf_path: str, n_samples: int = 5) -> dict:
    """Classify PDF extractability using fitz for metadata (fast) and
    pdfplumber only for the sampled pages.
    Returns: {"extractable": bool, "producer": str, "page_count": int, "error": str|None}
    """
    t0 = time.time()

    # Use fitz for fast metadata + page count (no full parse)
    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}
    producer = meta.get("producer", "Unknown") or "Unknown"
    page_count = doc.page_count
    doc.close()
    logger.info("PDF metadata via fitz (%.2fs) — producer=%s, pages=%d", time.time() - t0, producer, page_count)

    is_bluebeam = "bluebeam" in producer.lower()

    # Sample page indices
    if page_count <= n_samples:
        sample_indices = list(range(page_count))
    else:
        step = page_count // (n_samples + 1)
        sample_indices = [step * (i + 1) for i in range(n_samples)]

    # Use fitz for fast text sampling (much faster than pdfplumber for simple text check)
    logger.info("Sampling text from %d pages via fitz: %s", len(sample_indices), sample_indices)
    t1 = time.time()
    total_chars = 0
    doc = fitz.open(pdf_path)
    for idx in sample_indices:
        text = doc[idx].get_text()
        total_chars += len(text)
    doc.close()
    logger.info("Text sampling done (%.2fs) — %d total chars from %d pages", time.time() - t1, total_chars, len(sample_indices))

    avg_chars = total_chars / len(sample_indices) if sample_indices else 0
    has_meaningful_text = avg_chars > 2000

    extractable = is_bluebeam or has_meaningful_text
    error = None
    if not extractable:
        error = (
            f"PDF is not text-extractable. Producer: '{producer}'. "
            "Fixture labels are likely encoded as vector strokes, not text objects. "
            "Please provide a Bluebeam-produced PDF."
        )

    return {
        "extractable": extractable,
        "producer": producer,
        "page_count": page_count,
        "error": error,
    }


def render_page_to_image(pdf_path: str, page_index: int, dpi: int = 300) -> bytes:
    """Render a PDF page to PNG bytes using PyMuPDF."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


# --- Sheet index parsing ---

# Matches sheet numbers like E-001, E0.04, E0.04.1, E3.1.10
_SHEET_NUM_RE = re.compile(r'^([A-Z]{1,2}[-.]?\d[\d./-]*)$')


def parse_sheet_index(pdf_path: str) -> dict:
    """Parse the sheet index from an engineering drawing PDF.

    Finds the sheet index page, extracts sheet entries, classifies them
    by description, and maps sheet numbers to 0-indexed page indices.

    Returns:
        {
            "schedule_pages": [int],
            "lighting_pages": [int],
            "unit_pages": [int],
            "sheet_map": {str: int},
        }
    """
    t0 = time.time()
    empty = {"schedule_pages": [], "lighting_pages": [], "unit_pages": [], "sheet_map": {}}

    doc = fitz.open(pdf_path)
    page_count = doc.page_count

    # Step 1: Find the index page (prefer electrical sheet index)
    index_page_idx = _find_index_page(doc, page_count)
    if index_page_idx is None:
        doc.close()
        logger.info("parse_sheet_index: no index page found (%.1fs)", time.time() - t0)
        return empty

    logger.info("parse_sheet_index: found index on page %d", index_page_idx)

    # Step 2: Parse sheet entries from the index page
    index_text = doc[index_page_idx].get_text()
    entries = _parse_sheet_entries(index_text)
    logger.info("parse_sheet_index: parsed %d sheet entries", len(entries))
    for sn, desc in entries[:10]:
        logger.info("  %s → %s", sn, desc)
    if len(entries) > 10:
        logger.info("  ... and %d more", len(entries) - 10)

    # Step 3: Classify entries by description
    schedule_sheets = []
    lighting_sheets = []
    unit_sheets = []
    for sheet_num, description in entries:
        desc_upper = description.upper()
        has_lighting = any(w in desc_upper for w in ("LIGHTING", "LUMINAIRE", "FIXTURE"))
        has_schedule = "SCHEDULE" in desc_upper
        has_plan = "PLAN" in desc_upper
        has_unit = "UNIT" in desc_upper
        has_electrical = "ELECTRICAL" in desc_upper
        has_demolition = any(w in desc_upper for w in ("DEMOLITION", "DEMO", "EXISTING"))

        if has_lighting and has_schedule:
            schedule_sheets.append(sheet_num)
            logger.info("  SCHEDULE: %s → %s", sheet_num, description)
        elif has_lighting and has_plan and not has_demolition:
            lighting_sheets.append(sheet_num)
            logger.info("  LIGHTING: %s → %s", sheet_num, description)
        elif has_unit and (has_plan or has_electrical):
            unit_sheets.append(sheet_num)
            logger.info("  UNIT: %s → %s", sheet_num, description)

    logger.info(
        "parse_sheet_index: classified — %d schedule, %d lighting, %d unit sheets",
        len(schedule_sheets), len(lighting_sheets), len(unit_sheets),
    )

    # Step 4: Map sheet numbers to page indices
    all_sheets = set(schedule_sheets + lighting_sheets + unit_sheets)
    sheet_map = _map_sheets_to_pages(doc, all_sheets, page_count)
    doc.close()

    logger.info("parse_sheet_index: mapped %d/%d sheets to pages (%.1fs)",
                len(sheet_map), len(all_sheets), time.time() - t0)
    for sn, pg in sorted(sheet_map.items(), key=lambda x: x[1]):
        logger.info("  %s → page %d", sn, pg)

    return {
        "schedule_pages": sorted(sheet_map[s] for s in schedule_sheets if s in sheet_map),
        "lighting_pages": sorted(sheet_map[s] for s in lighting_sheets if s in sheet_map),
        "unit_pages": sorted(sheet_map[s] for s in unit_sheets if s in sheet_map),
        "sheet_map": sheet_map,
    }


def _find_index_page(doc, page_count: int) -> int | None:
    """Find the sheet index page by scanning for keywords.

    Prefers pages that contain electrical sheet numbers (E-xxx or E0.xx)
    to avoid picking up mechanical/plumbing/fire alarm index pages.
    """
    keywords = ("SHEET INDEX", "DRAWING INDEX", "SHEET LIST", "TABLE OF CONTENTS")
    electrical_sheet_re = re.compile(r'E[-.]?\d')

    # Check first 10 pages and text-heavy pages
    candidates = list(range(min(10, page_count)))
    for i in range(page_count):
        if i not in candidates:
            text = doc[i].get_text()
            if len(text) > 10000:
                candidates.append(i)

    # Find all pages with the keyword, then prefer the one with electrical sheets
    matches = []
    for i in candidates:
        text = doc[i].get_text()
        text_upper = text.upper()
        if any(kw in text_upper for kw in keywords):
            e_count = len(electrical_sheet_re.findall(text))
            matches.append((i, e_count, len(text)))
            logger.info("  Index candidate page %d: %d electrical sheet refs, %d chars", i, e_count, len(text))

    if not matches:
        return None

    # Prefer page with most electrical sheet references
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[0][0]


def _parse_sheet_entries(text: str) -> list[tuple[str, str]]:
    """Parse (sheet_number, description) pairs from index page text.

    Engineering drawing sheet indexes typically have lines like:
        E-001
        ELECTRICAL COVER SHEET
    or:
        E-001  ELECTRICAL COVER SHEET
    """
    entries = []
    lines = text.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        m = _SHEET_NUM_RE.match(line)
        if m:
            sheet_num = m.group(1)
            # Description is on the next non-empty line
            desc = ""
            for j in range(i + 1, min(i + 3, len(lines))):
                next_line = lines[j].strip()
                if next_line and not _SHEET_NUM_RE.match(next_line):
                    desc = next_line
                    break
            if desc:
                entries.append((sheet_num, desc))
            continue

        # Also try: "SCALE  E-001  DESCRIPTION  SCALE" format (Chase Bank)
        # where sheet number is embedded in a line with other content
        parts = re.split(r'\s{2,}', line)  # split on 2+ spaces
        for idx, part in enumerate(parts):
            part = part.strip()
            if _SHEET_NUM_RE.match(part):
                # Description is the next part
                if idx + 1 < len(parts):
                    desc = parts[idx + 1].strip()
                    if desc and len(desc) > 3:
                        entries.append((part, desc))

    return entries


def _map_sheets_to_pages(doc, sheet_numbers: set, page_count: int) -> dict:
    """Map sheet numbers to 0-indexed page indices.

    Engineering drawing pages have a title block containing the sheet number
    followed by the sheet title. We look for the pattern:
        SHEET_NUMBER\\nDESCRIPTION
    This distinguishes the actual page from cross-references (where the
    sheet number appears in a list or table).
    """
    sheet_map = {}
    if not sheet_numbers:
        return sheet_map

    # For each sheet, find the page where it appears on its own line.
    # Collect all candidate pages per sheet, then pick the best one.
    candidates = {}  # {sheet_num: [(page_idx, position_in_text)]}
    for i in range(page_count):
        text = doc[i].get_text()
        if not text:
            continue
        for sn in sheet_numbers:
            pattern = f"\n{sn}\n"
            pos = text.find(pattern)
            if pos == -1 and text.startswith(f"{sn}\n"):
                pos = 0
            if pos >= 0:
                candidates.setdefault(sn, []).append((i, pos, len(text)))

    for sn, pages in candidates.items():
        if len(pages) == 1:
            sheet_map[sn] = pages[0][0]
        else:
            # Multiple pages contain this sheet number — pick the one that is NOT
            # the index page and where the sheet appears with fewest other target sheets
            best = None
            best_score = float('inf')
            for page_idx, pos, text_len in pages:
                # Count how many OTHER target sheet numbers also appear on this page
                page_text = doc[page_idx].get_text()
                co_count = sum(1 for other in sheet_numbers if other != sn and f"\n{other}\n" in page_text)
                # Lower co_count = more likely the actual page (not an index)
                if co_count < best_score:
                    best_score = co_count
                    best = page_idx
            if best is not None:
                sheet_map[sn] = best
                logger.info("  %s → page %d (chose from %d candidates, co_count=%d)",
                             sn, best, len(pages), best_score)

    unmapped = sheet_numbers - set(sheet_map.keys())
    if unmapped:
        logger.warning("  Could not map %d sheets to pages: %s", len(unmapped), sorted(unmapped))

    return sheet_map


# --- Batch extraction ---

def extract_pages_text_batch(pdf_path: str, page_indices: list[int]) -> dict[int, str]:
    """Extract full text from multiple pages, opening PDF once.
    Returns {page_index: text}.
    """
    t0 = time.time()
    result = {}
    with pdfplumber.open(pdf_path) as pdf:
        for idx in page_indices:
            if 0 <= idx < len(pdf.pages):
                result[idx] = pdf.pages[idx].extract_text() or ""
    logger.info("extract_pages_text_batch: %d pages in %.1fs", len(result), time.time() - t0)
    return result


def extract_pages_words_batch(pdf_path: str, page_indices: list[int]) -> dict[int, list[dict]]:
    """Extract words from multiple pages, opening PDF once.
    Returns {page_index: [word_dicts]}.
    """
    t0 = time.time()
    result = {}
    with pdfplumber.open(pdf_path) as pdf:
        for idx in page_indices:
            if 0 <= idx < len(pdf.pages):
                words = pdf.pages[idx].extract_words(keep_blank_chars=False, use_text_flow=False)
                result[idx] = [
                    {
                        "text": w.get("text", ""),
                        "x0": w.get("x0", 0),
                        "y0": w.get("top", 0),
                        "x1": w.get("x1", 0),
                        "y1": w.get("bottom", 0),
                    }
                    for w in words
                ]
    logger.info("extract_pages_words_batch: %d pages in %.1fs", len(result), time.time() - t0)
    return result
