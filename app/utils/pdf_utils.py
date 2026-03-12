import pdfplumber
import fitz


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


def render_page_to_image(pdf_path: str, page_index: int, dpi: int = 300) -> bytes:
    """Render a PDF page to PNG bytes using PyMuPDF."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes
