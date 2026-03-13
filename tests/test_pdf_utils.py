import pytest
from app.utils.pdf_utils import get_pdf_metadata, extract_page_text, render_page_to_image, get_page_count, extract_page_words, extract_page_full_text, parse_sheet_index, extract_pages_text_batch, extract_pages_words_batch

AMLI_PDF = "04_Electrical_1-16-2026.pdf"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_get_pdf_metadata_amli():
    meta = get_pdf_metadata(AMLI_PDF)
    assert "producer" in meta
    assert "Bluebeam" in meta["producer"]


def test_get_pdf_metadata_chase():
    meta = get_pdf_metadata(CHASE_PDF)
    assert "Bluebeam" in meta["producer"]


def test_get_page_count():
    count = get_page_count(AMLI_PDF)
    assert count == 135


def test_extract_page_text_returns_chars():
    chars = extract_page_text(AMLI_PDF, page_index=5)
    assert len(chars) > 100
    first = chars[0]
    assert "text" in first
    assert "x0" in first
    assert "y0" in first


def test_extract_page_words():
    words = extract_page_words(AMLI_PDF, page_index=5)
    assert len(words) > 10
    first = words[0]
    assert "text" in first
    assert "x0" in first


def test_extract_page_full_text():
    text = extract_page_full_text(AMLI_PDF, page_index=5)
    assert len(text) > 100


def test_render_page_to_image():
    img_bytes = render_page_to_image(AMLI_PDF, page_index=5, dpi=150)
    assert isinstance(img_bytes, bytes)
    assert img_bytes[:4] == b'\x89PNG'


# --- parse_sheet_index tests ---

def test_parse_sheet_index_chase():
    """Chase Bank has a sheet index. Should find schedule and lighting pages."""
    result = parse_sheet_index(CHASE_PDF)
    assert "schedule_pages" in result
    assert "lighting_pages" in result
    assert "sheet_map" in result
    # Chase Bank has lighting schedule pages
    assert len(result["schedule_pages"]) > 0
    assert len(result["lighting_pages"]) > 0
    # All page indices should be non-negative integers
    for p in result["schedule_pages"] + result["lighting_pages"]:
        assert isinstance(p, int)
        assert p >= 0


def test_parse_sheet_index_amli():
    """AMLI BREA has a sheet index. Should find schedule and lighting pages."""
    result = parse_sheet_index(AMLI_PDF)
    assert len(result["schedule_pages"]) > 0
    assert len(result["lighting_pages"]) > 0


# --- batch extraction tests ---

def test_extract_pages_text_batch():
    """Batch extraction should return text for each requested page."""
    result = extract_pages_text_batch(AMLI_PDF, [0, 5])
    assert len(result) == 2
    assert 0 in result and 5 in result
    assert len(result[5]) > 100  # Schedule page has lots of text


def test_extract_pages_words_batch():
    """Batch word extraction should return word lists for each page."""
    result = extract_pages_words_batch(AMLI_PDF, [0, 5])
    assert len(result) == 2
    assert len(result[5]) > 10
    assert "text" in result[5][0]
