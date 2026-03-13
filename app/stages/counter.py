import re
from collections import Counter
from app.utils.pdf_utils import extract_page_words
from app.utils.spatial import identify_title_block_region, identify_legend_regions, is_in_region
import pdfplumber


def normalize_fixture_code(code: str) -> str:
    """Normalize fixture codes: DF01→DF1, DF03→DF3, etc."""
    return re.sub(r'^(DF)0+(\d)', r'\1\2', code)


def count_fixtures_on_page(pdf_path: str, page_index: int, fixture_types: list[str]) -> dict[str, int]:
    """Count fixture labels on a single page using spatial filtering."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        page_width = page.width
        page_height = page.height

    words = extract_page_words(pdf_path, page_index)

    title_block = identify_title_block_region(page_width, page_height)
    legend_regions = identify_legend_regions(words, page_width, page_height)
    exclusion_zones = [title_block] + legend_regions

    # Normalize type codes and build lookup
    type_set = {normalize_fixture_code(t.upper().strip()) for t in fixture_types}
    type_patterns = {}
    for t in type_set:
        escaped = re.escape(t)
        type_patterns[t] = re.compile(f'^{escaped}$', re.IGNORECASE)

    counts = Counter()

    for word in words:
        text = normalize_fixture_code(word["text"].strip().upper())
        x0, y0 = word["x0"], word["y0"]

        in_exclusion = False
        for zone in exclusion_zones:
            if is_in_region(x0, y0, zone):
                in_exclusion = True
                break
        if in_exclusion:
            continue

        for type_code, pattern in type_patterns.items():
            if pattern.match(text):
                counts[type_code] += 1
                break

    return dict(counts)


def count_fixtures_multi_page(pdf_path: str, page_indices: list[int], fixture_types: list[str]) -> dict[str, int]:
    """Count fixtures across multiple pages, summing counts."""
    total = Counter()
    for page_idx in page_indices:
        page_counts = count_fixtures_on_page(pdf_path, page_idx, fixture_types)
        total.update(page_counts)
    return dict(total)
