import logging
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
