from app.utils.pdf_utils import classify_pdf_fast


def classify_pdf(pdf_path: str) -> dict:
    """Check if a PDF has text-extractable fixture labels.
    Returns: {"extractable": bool, "producer": str, "page_count": int, "error": str|None}
    """
    return classify_pdf_fast(pdf_path)


def _sample_page_indices(page_count: int, n: int = 5) -> list[int]:
    if page_count <= n:
        return list(range(page_count))
    step = page_count // (n + 1)
    return [step * (i + 1) for i in range(n)]
