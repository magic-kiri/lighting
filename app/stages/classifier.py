from app.utils.pdf_utils import get_pdf_metadata, get_page_count, extract_page_text


def classify_pdf(pdf_path: str) -> dict:
    """Check if a PDF has text-extractable fixture labels.
    Returns: {"extractable": bool, "producer": str, "page_count": int, "error": str|None}
    """
    meta = get_pdf_metadata(pdf_path)
    producer = meta.get("producer", "Unknown")
    page_count = get_page_count(pdf_path)

    is_bluebeam = "bluebeam" in producer.lower()

    sample_indices = _sample_page_indices(page_count, n=5)
    total_chars = 0
    for idx in sample_indices:
        chars = extract_page_text(pdf_path, idx)
        total_chars += len(chars)

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


def _sample_page_indices(page_count: int, n: int = 5) -> list[int]:
    if page_count <= n:
        return list(range(page_count))
    step = page_count // (n + 1)
    return [step * (i + 1) for i in range(n)]
