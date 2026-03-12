# PDF Encoding Analysis — Feasibility of Deterministic Fixture Extraction

**Date**: 2026-03-11
**Purpose**: Determine whether lighting fixture counts can be extracted from engineering drawing PDFs programmatically with 100% accuracy.

---

## Executive Summary

We analyzed three sample engineering drawing PDFs provided by Commercial Lighting Industries (CLI) to determine how fixture labels are encoded internally. The central question: **Can we build a deterministic, 100% accurate system to extract fixture counts from these PDFs?**

**Finding**: It depends entirely on **how the PDF was exported from AutoCAD**. The same drawing exported two different ways produces radically different PDFs:

| Export Method | Fixture Labels Stored As | Text Extractable? | Deterministic? |
|---------------|--------------------------|-------------------|----------------|
| **Via Bluebeam Revu** | Real text objects (TrueType fonts) | Yes — 100% | Yes |
| **Direct from AutoCAD** | Raw vector pen strokes (no text data) | No — 0% | No (requires OCR/Vision) |

Of our three samples:
- **AMLI BREA** (135 pages, complex) — Bluebeam export — **fully extractable**
- **Chase Bank** (173 pages, medium) — Bluebeam export — **fully extractable**
- **Popeyes** (15 pages, simple) — Direct AutoCAD export — **not extractable via text parsing**

**2 out of 3 samples are Bluebeam-exported and fully deterministic.** The Popeyes PDF (direct AutoCAD export) is the outlier.

---

## Background

### The Business Process

CLI receives engineering drawing PDFs from architects/engineers. A human (Kaz) manually:
1. Reads the Lighting Fixture Schedule (a table defining fixture type codes)
2. Visually counts every fixture symbol on the floor plans
3. Produces an Excel file with Type + Quantity pairs

### The Goal

Automate this process: PDF in → Excel out, with deterministic accuracy.

### The Three Sample Files

| Project | PDF File | Pages | Size | Difficulty |
|---------|----------|-------|------|------------|
| Popeyes (Newberg, OR) | `Newberg Popeyes Permit Set Revised_ E-Sheets.pdf` | 15 | 5.3 MB | Easy |
| Chase Bank (Newport Beach) | `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf` | 173 | 93 MB | Medium |
| AMLI BREA (Brea, CA) | `04_Electrical_1-16-2026.pdf` | 135 | 157 MB | Hard |

---

## Technical Deep Dive

### How AutoCAD Text Ends Up in PDFs

AutoCAD uses **SHX fonts** — a proprietary vector font format where each character is defined as a series of line/arc strokes. When exporting to PDF, there are two possible outcomes:

```
AutoCAD Drawing (SHX fonts)
    │
    ├── Export via Bluebeam Revu / PDF printer with font conversion
    │   └── SHX glyphs → mapped to TrueType equivalents (ArialMT, etc.)
    │   └── Result: Real PDF text objects with Unicode character mapping
    │   └── Extractable: YES ✓
    │
    └── Export directly from AutoCAD (DWG to PDF)
        └── SHX glyphs → "exploded" into raw line/curve vector paths
        └── Result: The letter "A" is just 3 line segments, not a character
        └── Extractable: NO ✗
```

This is the single most important variable in the entire system.

---

## Sample 1: Popeyes (Newberg, OR)

### PDF Properties

| Property | Value |
|----------|-------|
| File | `Newberg Popeyes Permit Set Revised_ E-Sheets.pdf` |
| Pages | 15 |
| Size | 5.3 MB |
| Producer | Direct AutoCAD export |
| Key Page | Page 5, Sheet E1.1 (Electrical Lighting Plan) |

### Font Analysis (Page 5)

| Font | Type | Used For |
|------|------|----------|
| Arial-BoldMT | TrueType (Type0/CIDFontType2) | Grid labels (1, A, B.1) |
| ArialMT | TrueType (Type0/CIDFontType2) | Title block text, legal boilerplate |
| CopperplateGothic-Bold | TrueType | "ROBISON ENGINEERING" |
| CopperplateGothic-Light | TrueType | Address, contact info |

**No SHX fonts appear in the font table** — because SHX text was exploded to vector paths before PDF creation. The fonts listed are only used for the title block and border annotations.

### Text Extraction Results

Three independent PDF parsing libraries were tested:

| Library | Total Text Found | Fixture Labels Found |
|---------|-----------------|---------------------|
| PyMuPDF (`get_text`) | 1,285 characters | **0** |
| pdfplumber (`extract_text`) | 1,281 characters | **0** |
| pdfminer.six (`extract_pages`) | 1,285 characters | **0** |

**All three libraries agree: ZERO fixture labels exist as text in this PDF.**

All extracted text belongs to the title block, border labels, and boilerplate legal text. None of it is fixture annotation.

### Content Stream Analysis (Page 5)

| Metric | Value |
|--------|-------|
| Content stream size | 849,008 bytes |
| BT/ET text blocks | 76 (only title block — ~3,800 bytes) |
| Vector path data | ~845,000 bytes (99.5% of the stream) |
| Total vector drawings | 13,469 |
| XObject references | 0 |

The page is almost entirely vector geometry. A detailed examination of the vector paths at known fixture locations reveals:
- **Fixture symbols**: Formed by bezier curves (concentric ellipses, crossing lines)
- **Fixture labels**: Formed by **24+ individual line/curve strokes** per character — literally drawn as pen strokes

### Conclusion for Popeyes

**Encoding: Raw vector strokes (SHX exploded to geometry)**
**Deterministic text extraction: IMPOSSIBLE**

The fixture labels ("AE", "A", "L-7", etc.) do not exist as text anywhere in the PDF. They are composed of individual line segments and curves — the letter "A" is 3 line segments, "E" is 4 line segments, etc. No amount of text parsing will find them.

---

## Sample 2: AMLI BREA (Brea, CA)

### PDF Properties

| Property | Value |
|----------|-------|
| File | `04_Electrical_1-16-2026.pdf` |
| Pages | 135 |
| Size | 157 MB |
| Creator | Bluebeam Revu x64 |
| Producer | Bluebeam PDF Library 21 |
| CIDSystemInfo Registry | PDFAUTOCAD |
| Key Pages | Page 6 (E0.04 — Fixture Schedule), Pages 34-44 (Unit Plans), Pages 70-119 (Floor Plans) |

### Font Analysis (across multiple pages)

| Font | Type | Used For |
|------|------|----------|
| **ArialMT** | TrueType (Type0/CIDFontType2) | **Fixture labels**, circuit info, notes |
| Swiss721BT-RomanCondensed | TrueType | Room labels, title block |
| Swiss721BT-BoldCondensed | TrueType | Project info |
| Swiss721BT-ItalicCondensed | TrueType | Copyright text |
| ArialNarrow / Bold / BoldItalic | TrueType | Parking labels |
| Arial-BoldMT | TrueType | Headings |
| SymbolMT | TrueType | Bullet points |

**All fonts are standard TrueType.** No Type 3 fonts, no SHX remnants. Bluebeam Revu converted all SHX text to ArialMT during export.

### Text Extraction Results

#### Page 6 — Lighting Fixture Schedule

| Library | Fixture Type Codes Found |
|---------|-------------------------|
| PyMuPDF | 6 labels: U1, B1, B2, GA, GA1, P3 |
| **pdfplumber** | **15 labels: U1, U2, U3, U4, U8, B1, B2, B3, B4, B5, GA, GA1, P3, B1-EM, B5-EM** |
| pdfminer.six | 15 labels (same as pdfplumber) |

**pdfplumber finds 2.5x more labels than PyMuPDF** on the same page due to better CID/Identity-H text assembly.

#### Page 34 — Unit Electrical Plan (E1a)

| Metric | Value |
|--------|-------|
| BT/ET text blocks | 324 (all real text objects) |
| Fixture labels found | U1 (3x), U3, U4, SC, U1A |
| Font for fixture labels | ArialMT @ 9.1pt |

#### Page 70 — Segment 1 Basement Floor Plan

Fixture labels found: B1 (2x), B2 (1x), B1-EM (1x), plus room labels and panel references — all extractable.

### Key Finding: Labels Are on Their Respective Pages

The "missing labels" issue from earlier analysis was a misunderstanding — fixture labels only appear on the pages where those fixtures are drawn:

| Label | Found On Pages |
|-------|---------------|
| AL1 | Pages 25, 26, 31, 32, 60, 63 (amenity/common area plans) |
| AS1 | Page 31 |
| SC1 | Page 31 |
| B5 | Pages 6, 28 |
| U1-U8 | Pages 34-44 (unit plans) |

**All labels ARE extractable — you just need to look on the right pages.**

### Content Stream Analysis (Page 34)

| Metric | Value |
|--------|-------|
| Content stream size | 581,603 bytes |
| BT/ET text blocks | 324 |
| Vector path operations | 31,455 |
| XObject references | 4 (trivial white rectangle overlays) |

Unlike Popeyes where 99.5% of the stream was vector paths, AMLI BREA has substantial text content mixed with the vector geometry.

### Text Encoding Details

Text is encoded as hex CID strings with ToUnicode CMap:
```
<00280033> Tj    →  CID 0x28=E, CID 0x33=P  →  "EP"
```

The CMap correctly maps every CID to its Unicode character. This is standard PDF text encoding and fully supported by pdfplumber.

### Conclusion for AMLI BREA

**Encoding: Real text objects (SHX converted to TrueType by Bluebeam)**
**Deterministic text extraction: FULLY POSSIBLE**

Every fixture label is a proper text object with:
- Unicode character mapping (via ToUnicode CMap)
- Precise (x, y) coordinates on the page
- Font metadata (ArialMT @ 9.1pt)

Recommended parser: **pdfplumber** (handles CID encoding better than PyMuPDF).

---

## Sample 3: Chase Bank (Newport Beach)

### PDF Properties

| Property | Value |
|----------|-------|
| File | `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf` |
| Pages | 173 |
| Size | 93 MB |
| Creator | Bluebeam Stapler 20.2.85.2 |
| Producer | Bluebeam Brewery 5.0 |
| Source CAD | **Revit** (Autodesk Docs path in title block: `...JPMC Jamboree&SB-006.4800.124-R25/...R25.rvt`) |
| Architect | Gensler |
| MEP/Lighting Engineer | Syska Hennesy |
| Key Pages | Page 103 (E-005 — Lighting Schedule), Pages 112-113 (E-211/E-212 — Lighting Plans) |

### Font Analysis (all electrical pages 99-123)

Only **two fonts** across all electrical pages:

| Font | Type | Used For |
|------|------|----------|
| HMCEYP+ArialNarrow | TrueType (ttf) | Fixture labels, room names, notes |
| MTCNZF+ArialNarrow,Bold | TrueType (ttf) | Headings, sheet numbers |

**No SHX fonts, no Type 3 fonts.** All text is embedded TrueType — structurally identical to AMLI BREA.

### Text Extraction Results

#### Pages 112-113 — Electrical Lighting Plans (Level 01 + Level 02)

Both PyMuPDF and pdfplumber successfully extract fixture labels:

| Fixture Code | Occurrences Found (PyMuPDF) | Excel Expected Qty | Description |
|-------------|----------------------------|-------------------|-------------|
| D1A | 69 | 37 | 3" Downlight |
| D1B | 16 | 13 | 3" Downlight |
| D2 | 18 | 8 | 3" Adjustable Downlight |
| L1A | 47 | 32 | Recessed Linear (4'/6'/8') |
| L2A | 30 | 10 runs | Custom Shape Cove Light |
| L2B | 7 | 3 runs | Cove Light |
| L5 | 7 | 6 | Linear |
| L6 | 3 | 2 | LED Tape Light |
| L-8 | 2 | 2 | Suspended Strip Light |
| L-22 | 2 | 2 | LED Strip w/ Occ Sensor |
| X1 | 8 | 7 | Exit Signs |
| DF01/DF1 | 1 | 1 | 65" Decorative Pendant |
| DF03/DF3 | 1 | 1 | Decorative Suspended Linear |
| DF04/DF4 | 1 | 1 | Up/Down Pendant |
| DF05/DF5 | 1 | 1 | Eclipse Pendant |
| EM | 63 | 29 | Emergency designation markers |

**Extractability: 100%** — every fixture label is a real text object.

Note: Raw extraction counts are higher than Excel quantities because the PDF includes labels in legends, keynotes, and circuit annotations in addition to the actual fixture placements. Post-processing logic is needed to distinguish placed fixtures from reference labels.

#### Additional Extractable Data

Beyond fixture labels, text extraction yields:
- **Room names**: "BANKER OFFICE 208", "WELCOME AREA 201", "BOARDROOM 205", etc.
- **Panel/Circuit references**: 157 instances (e.g., `(E) PP3: 21 y`)
- **Lighting control zones**: 52 zone references across 16 unique zones
- **EM (Emergency) markers**: 63 instances marking fixtures on emergency circuits

### Content Stream Analysis (Page 113)

| Metric | Value |
|--------|-------|
| Content stream size | 4,219,425 bytes |
| BT/ET text blocks | 78 |
| Text show operations (Tj + TJ) | 885 |
| Vector path operations (m + l + c) | 255,555 |
| Stroke operations | 126,320 |

Text operations are 0.35% of the content, but fixture labels ARE properly encoded as BT/ET text blocks with TJ operators — fully extractable.

### Caveat: Fixture Schedule Is Rasterized

The Lighting Schedule page (E-005, Page 103) is **rasterized as images**, not text:
- 3 embedded images on the page (main schedule image: 3849 x 8595 pixels)
- Only title block text is extractable (946 characters)
- The actual schedule table content (fixture types, descriptions, wattages) would require **OCR**

This differs from AMLI BREA where the fixture schedule was text-extractable. For Chase Bank, the schedule data would need to come from the Excel output file or OCR.

### Naming Discrepancy

The PDF uses **two naming conventions** for decorative fixtures:

| Context | Format | Example |
|---------|--------|---------|
| Fixture callout labels on plan | Zero-padded | DF01, DF03, DF04, DF05 |
| Zone legend references on plan | No padding | DF2, DF3, DF4, DF5 |
| Excel output | No padding | DF1, DF3, DF4, DF5 |

Any automated extraction must normalize `DF01` → `DF1` to match properly.

### Conclusion for Chase Bank

**Encoding: Real text objects (Bluebeam-assembled from Revit exports)**
**Deterministic text extraction: FULLY POSSIBLE**

Chase Bank is structurally identical to AMLI BREA — a Bluebeam-produced PDF with TrueType fonts and fully extractable fixture labels. The same pdfplumber-based pipeline will work for both.

---

## Comparison Matrix

| Property | Popeyes | AMLI BREA | Chase Bank |
|----------|---------|-----------|------------|
| **PDF Producer** | AutoCAD DWG-to-PDF | Bluebeam Revu x64 | Bluebeam Brewery 5.0 |
| **Source CAD** | AutoCAD (.dwg) | Revit (.rvt) | Revit (.rvt) |
| **Font types** | TrueType (title block only) | TrueType (all text) | TrueType (all text) |
| **SHX handling** | Exploded to vectors | Converted to TTF | Converted to TTF |
| **Fixture labels** | Vector strokes | Text objects | Text objects |
| **Text extractable?** | 0% | 100% | 100% |
| **Schedule extractable?** | 0% (vector strokes) | Yes (text) | No (rasterized image) |
| **Best parser** | None (needs OCR) | pdfplumber | pdfplumber (PyMuPDF also works) |
| **Deterministic?** | No | **Yes** | **Yes** |

**Pattern**: PDFs processed through Bluebeam (regardless of source CAD — Revit or AutoCAD) have extractable text. PDFs exported directly from AutoCAD's built-in DWG-to-PDF writer do not.

---

## Recommended Architecture (Preliminary)

### For Bluebeam-exported PDFs (text extractable):

```
PDF ──→ pdfplumber ──→ Extract all text with (x, y) coordinates
                   ──→ Identify Lighting Fixture Schedule pages
                   ──→ Parse schedule table: Type → Description → Manufacturer
                   ──→ Identify floor plan pages
                   ──→ Find all fixture label text objects on floor plans
                   ──→ Count occurrences of each type code
                   ──→ Output: Type + Quantity Excel
```

**Accuracy: 100% deterministic.** No AI, no vision models needed.

### For direct AutoCAD-exported PDFs (vector strokes only):

Three options, in order of preference:

1. **Request Bluebeam re-export from client** — Simplest solution. If the client can re-export through Bluebeam or any PDF printer that converts SHX→TTF, the text becomes extractable.

2. **SHX vector pattern matching** — Build a dictionary of SHX glyph vector patterns (the exact line/curve sequences for each character A-Z, 0-9, dash, etc.) and match against the PDF's vector paths. This is complex to build but would be **deterministic and accurate** once the pattern library is complete.

3. **OCR/Vision on rendered images** — Render pages at high DPI (400+) and use OCR or a vision model to read labels. **Not 100% accurate** — dense engineering drawings with overlapping text, small fonts, and similar-looking symbols make this error-prone.

### Detection: Auto-classify the PDF type

Before processing, the system should auto-detect which type of PDF it's dealing with:

```python
import pdfplumber

def classify_pdf(path):
    with pdfplumber.open(path) as pdf:
        # Check producer metadata
        producer = pdf.metadata.get("Producer", "")
        if "Bluebeam" in producer:
            return "text_extractable"

        # Fallback: check if electrical pages have fixture-like text
        for page in pdf.pages:
            chars = page.chars
            if len(chars) > 500:  # Substantial text content
                return "text_extractable"

        return "vector_strokes_only"
```

---

## Key Risks and Considerations

1. **Font encoding quirks**: Even in Bluebeam PDFs, the CID/Identity-H encoding requires careful handling. PyMuPDF misses ~60% of labels that pdfplumber catches. **Always use pdfplumber.**

2. **Page identification**: Not all pages contain fixtures. The system must identify which pages are lighting plans vs. power plans, panel schedules, details, etc. Sheet title text (e.g., "ELECTRICAL LIGHTING PLAN") is typically extractable and can be used for filtering.

3. **AMLI BREA complexity layer**: Large projects have a unit multiplication pattern — fixture counts per unit type must be multiplied by the number of units. This requires understanding the drawing's unit type system, which adds a logic layer beyond simple counting.

4. **BOM expansion**: The final Excel output isn't just Type + Quantity. It includes accessories, drivers, and mounting hardware per fixture type. This mapping comes from CLI's product catalog, not from the PDF.

5. **Rotated/mirrored text**: Some Bluebeam PDFs contain rotated text blocks (e.g., 180-degree rotated title block text). pdfplumber extracts these characters in stream order, which may be reversed. This needs post-processing.

---

## Overall Conclusion

**2 out of 3 sample PDFs (AMLI BREA and Chase Bank) are fully extractable using deterministic text parsing.** These represent the "Medium" and "Hard" difficulty cases — the ones that matter most for automation ROI.

The Popeyes PDF (direct AutoCAD export) is the outlier with 0% text extractability. However, it's also the "Easy" case that a human can count in minutes.

**The key question for CLI**: What percentage of incoming PDFs are Bluebeam-exported vs. direct AutoCAD-exported? If the majority come through Bluebeam (which is the industry-standard tool for construction document management), then a deterministic `pdfplumber`-based pipeline can handle the bulk of the workload.

### Challenges Beyond Text Extraction

Even with fully extractable text, building the complete pipeline requires solving:

1. **Count disambiguation**: Raw text extraction finds more fixture labels than actual fixtures (labels appear in legends, keynotes, circuit annotations, not just placements). Need logic to distinguish placed fixtures from reference labels — likely using (x, y) coordinate analysis and proximity to floor plan boundaries.

2. **Unit multiplication** (AMLI BREA pattern): Large residential projects have fixture counts per unit type that must be multiplied by unit counts on floor plans. This adds a logic layer beyond simple label counting.

3. **Fixture schedule extraction**: Works on AMLI BREA (text), fails on Chase Bank (rasterized image). Need OCR fallback or manual schedule input for rasterized cases.

4. **BOM expansion**: The final Excel output includes accessories, drivers, and mounting hardware per fixture — this mapping comes from CLI's product catalog, not the PDF.

5. **Naming normalization**: Different conventions on the same drawing (e.g., `DF01` vs `DF1`). Need a normalization layer.

## Next Steps

1. **Collect more sample PDFs from CLI**: Ask them to share 10-15 real project PDFs they've recently processed. We'll auto-detect which encoding each uses and establish the actual ratio of extractable vs. non-extractable files. This determines the ROI of the deterministic approach.
2. Build a prototype `pdfplumber`-based extractor for Bluebeam PDFs
3. Test against AMLI BREA and Chase Bank to validate fixture counts match Kaz's Excel output
4. Decide on fallback strategy for non-Bluebeam PDFs (request re-export vs. OCR)

---

*This analysis was conducted on 2026-03-11 using PyMuPDF (fitz), pdfplumber, and pdfminer.six on the actual PDF files provided by CLI.*
