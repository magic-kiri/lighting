def identify_title_block_region(page_width: float, page_height: float) -> dict:
    """Return the bounding box of the title block region to exclude.
    Title blocks are typically in the bottom-right corner of engineering drawings.
    """
    if page_width > page_height:  # Landscape
        return {"x0": page_width * 0.75, "y0": page_height * 0.85, "x1": page_width, "y1": page_height}
    else:  # Portrait
        return {"x0": page_width * 0.65, "y0": page_height * 0.80, "x1": page_width, "y1": page_height}


def is_in_region(x0: float, y0: float, region: dict) -> bool:
    """Check if a point falls within a region."""
    return (region["x0"] <= x0 <= region["x1"] and region["y0"] <= y0 <= region["y1"])


def identify_legend_regions(words: list[dict], page_width: float, page_height: float) -> list[dict]:
    """Detect legend/keynote regions. Returns list of exclusion region bounding boxes."""
    regions = [
        {"x0": 0, "y0": page_height * 0.82, "x1": page_width, "y1": page_height},
        {"x0": page_width * 0.92, "y0": 0, "x1": page_width, "y1": page_height},
        {"x0": 0, "y0": 0, "x1": page_width * 0.03, "y1": page_height},
        {"x0": 0, "y0": 0, "x1": page_width, "y1": page_height * 0.03},
    ]
    return regions
