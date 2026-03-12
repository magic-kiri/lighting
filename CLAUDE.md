# Commercial Lighting - Fixture Takeoff Automation

## Project Overview
Automate the "lighting fixture takeoff" process for Commercial Lighting Industries (CLI).

**Current manual process**: Engineers receive architectural/electrical PDF drawings, manually read fixture schedules, count fixture symbols across all floor plan pages, and produce a Bill of Materials Excel file for quoting.

**Goal**: Build a system that takes engineering drawing PDFs as input and produces a structured Excel file with fixture types, quantities, catalog numbers, and descriptions.

## Business Context
- **Company**: Commercial Lighting Industries (CLI), Indio, CA
- **Contact**: Kaz Halcovich (National Account Sales Manager), Farren Halcovich
- **Client of**: Techjays (Philip Samuelraj) - building the POC
- **Domain**: Commercial lighting distribution - they supply lighting fixtures for construction projects

## Sample Data (3 difficulty levels)
| Project | Difficulty | PDF Pages | PDF Size | Fixture Types |
|---------|-----------|-----------|----------|---------------|
| Popeyes (Newberg, OR) | Easy | 15 | 5.3 MB | ~14 types |
| Chase Bank (Newport Beach) | Medium | 173 | 93 MB | ~30+ types |
| AMLI BREA (Brea, CA) | Very Large | 135 | 157 MB | 80+ types |

## Key Files
- `Email.txt` - Original email from Kaz with project links and Popeyes counts
- `AMLI-BREA, CA COUNTS.xlsx` - Expected output for AMLI BREA project
- `CHASE BANK - NEWPORT BEACH COUNTS.xlsx` - Expected output for Chase Bank project
- `Newberg Popeyes Permit Set Revised_ E-Sheets.pdf` - Popeyes engineering drawings
- `04_Electrical_1-16-2026.pdf` - AMLI BREA electrical drawings
- `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf` - Chase Bank drawings

## Output Excel Structure
The output Excel file has a "Quote to Customer" sheet with columns:
`Type | Quantity | CLI Catalog # | Ceiling Type | Ceiling Color | Manufacturer/Catalog # | Custom | Description`

There is also an "Import" sheet used for internal system integration with columns:
`DocID | Customer Number | Item Number | QTY | Price | LineType | Sector | Jobname | Custom | RowNumber | WorkSheetName`

## Engineering Drawing Structure
1. **Cover/Index pages** - project info, sheet index
2. **General notes pages** - electrical specs, code references
3. **Lighting Fixture Schedule page(s)** - TABLE listing each fixture type with: Type code, Manufacturer, Catalog #, Lamp info, Wattage, Voltage, Remarks
4. **Floor plan pages** - CAD drawings with fixture symbols placed on the plan, labeled with type codes (e.g., "AL1", "GA", "D1A")
5. **Panel schedules, single-line diagrams** - electrical distribution info

## Technical Notes
- PDFs are CAD-generated (AutoCAD .dwg exported to PDF), so they contain a mix of extractable text and graphical elements
- Fixture symbols on floor plans are graphical - they need visual/spatial recognition to count
- The Lighting Fixture Schedule pages contain structured text that can be extracted with PyMuPDF
- Large PDFs (100MB+) cannot be read by the built-in PDF reader tool
- Python packages available: `openpyxl`, `pymupdf` (fitz)
