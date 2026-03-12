# How Fixture Counts Are Derived from Engineering Drawings

## Files Reference

| File | Type | Description |
|------|------|-------------|
| `Email.txt` | Text | Original email from Kaz Halcovich with project links and Popeyes counts |
| `04_Electrical_1-16-2026.pdf` | PDF (135 pages, 157 MB) | AMLI BREA engineering drawings (input) |
| `AMLI-BREA, CA COUNTS.xlsx` | Excel | AMLI BREA bill of materials (output) |
| `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf` | PDF (173 pages, 93 MB) | Chase Bank engineering drawings (input) |
| `CHASE BANK - NEWPORT BEACH COUNTS.xlsx` | Excel | Chase Bank bill of materials (output) |
| `Newberg Popeyes Permit Set Revised_ E-Sheets.pdf` | PDF (15 pages, 5.3 MB) | Popeyes engineering drawings (input) |

**The process**: PDF (input) → manual human work → XLSX (output)

---

## The PDF Structure (Using AMLI BREA as Example)

The engineering drawing PDF `04_Electrical_1-16-2026.pdf` contains 135 pages organized into these sections:

### Section 1: General Notes & Specs (Pages 1-5, Sheets E0.01-E0.03)
Cover sheet, abbreviations, electrical specifications. Not used for counting.

### Section 2: Lighting Fixture Schedule (Pages 6-9, Sheets E0.04-E0.04.3)
**This is the "dictionary" of fixture types.** It defines what each type code means but does NOT contain quantities.

Exact text extracted from Page 6 (Sheet E0.04):
```
LIGHTING FIXTURE SCHEDULE

TYPE    MANUFACTURER CATALOG              LAMP QTY. & TYPE                    WATTAGE  VOLTS   REMARKS
U1      MAXIM LIGHTING #57690WT           (1) 12W LED (10X00 LUMENS), 3000K   12       120     5" SURFACE MOUNTED DOWNLIGHT
B1      LITHONIA #CLX-L48-4000LM-...      (1) 28W LED (4148 LUMENS), 4000K    28       UNV     4' LINEAR LED STRIP LIGHT
B2      LUMINAIRE #TSL9-34IN-40W-...      (1) 40W LED (4114 LUMENS), 4000K    40       UNV     SURFACE/WALL MOUNTED BI-LEVEL LED
GA      LITHONIA LIGHTING #VCPG LED-...   (1) 43W LED, (5985 LUMENS), 4000K   43       UNV     SURFACE GARAGE LIGHT
GA1     LITHONIA LIGHTING #VCPG LED-...   (1) 82W LED, (10854 LUMENS), 4000K  82       UNV     PENDANT MOUNTED GARAGE LIGHT
```

### Section 3: Unit Electrical Plans (Pages 34-44, Sheets E3.1.2-E3.1.12)
**Typical apartment unit plans.** Each page shows the electrical layout of one unit type (e.g., "UNIT A2", "UNIT C4") with fixture symbols placed on it.

Fixture labels extracted per unit plan page:

| Page | Sheet | Unit Type | U1 count | U3 count | U8 count |
|------|-------|-----------|----------|----------|----------|
| 34 | E3.1.2 | E1a | 3 | 1 | 0 |
| 35 | E3.1.3 | A2 | 4 | 1 | 2 |
| 36 | E3.1.4 | A3 | 3 | 1 | 2 |
| 37 | E3.1.5 | A3a | 3 | 1 | 2 |
| 38 | E3.1.6 | A3b | 5 | 1 | 2 |
| 39 | E3.1.7 | A3c | 4 | 1 | 2 |
| 40 | E3.1.8 | C4 | 5 | 1 | 3 |
| 41 | E3.1.9 | C4a | 6 | 1 | 3 |
| 42 | E3.1.10 | C5 | 6 | 1 | 3 |
| 43 | E3.1.11 | C6 | 7 | 1 | 3 |
| 44 | E3.1.12 | D4 | 6 | 1 | 4 |

### Section 4: Amenity/Common Area Plans (Pages 45-64, Sheets E3.4.x)
Leasing office, mail room, coworking space, dog wash, fitness center, club rooms, pool restrooms, roof deck. Each has unique fixture layouts with types like LP1, LP2, RA1, RD4, etc.

### Section 5: Overall Floor Plans (Pages 65-69, Sheets E6.x)
Bird's-eye views of entire floors showing unit placements.

### Section 6: Segment Floor Plans (Pages 70-119, Sheets E7.x)
**This is where unit types are placed on the building.** Each page shows one segment of one floor. The text labels tell you which unit type goes in each location.

Unit type occurrences extracted from segment plans (pages 70-119):

| Unit Type | Occurrences | Unit Type | Occurrences |
|-----------|-------------|-----------|-------------|
| A2 | 176 | C4 | 142 |
| A2.1 | 16 | C4.1 | 56 |
| A2.2 | 11 | C4.1a | 15 |
| A3 | 40 | C4a | 12 |
| A3a | 10 | C5 | 64 |
| A3b | 82 | C6 | 24 |
| A3c | 2 | D4 | 20 |
| E1 | 22 | E1a | 15 |
| E1.1 | 6 | E1a.1 | 34 |
| E1.2 | 47 | **Total** | **~795 units** |

### Section 7: Site Electrical Plans (Pages 25-32, Sheets E1.x)
Exterior/landscape plans showing site fixtures like AL1 (landscape accent), AS1/AS2 (tree accent), BH1 (bollard), etc.

### Section 8: Facade Lighting (Pages 120-127, Sheets E8.x)
Building elevation drawings showing wall-mounted fixtures like LS2, LS2A, SS7, SS9.

---

## How the Excel Output Is Generated (Three Layers)

### Layer 1: Extract Fixture Types from the Schedule (Text-Extractable)

The Lighting Fixture Schedule (Page 6, Sheet E0.04) is a text table. It lists every fixture type code with its manufacturer and specs. This maps directly to the Excel output columns:

**From PDF Schedule** → **To Excel Columns**
```
Type code (e.g., "B1")           → Column A: "Type"
Manufacturer + Catalog #         → Column G: "Catalog #"
Remarks/Description              → Column I: "Description"
```

However, the PDF schedule uses the **engineer's catalog numbers**, not CLI's. CLI replaces them with their own sourced products. For example:

| PDF Schedule Says | Excel Output Says |
|-------------------|-------------------|
| `LITHONIA #CLX-L48-4000LM-SEF-RDL-MVOLT-GZ10-40K-80CRI-WH` | `ELI 4-OC4-LED-4000L-DIM10-MVOLT-40K-85` |
| `LUMINAIRE #TSL9-34IN-40W-40K-MVOLT-OP-*-ONOFF50` | `DEC DLSL-GEN2-4MW45-MS` |

This substitution is **CLI domain knowledge** — they source equivalent products from their vendor network.

### Layer 2: Count Fixtures Across All Plan Pages (Visual/Spatial)

This is the core "takeoff" work. A human goes through every floor plan page and counts fixture symbols.

**For residential units** (U1, U3, U4, U8 etc.), the process is:
1. Count fixtures per unit type from the unit plans (pages 34-44)
2. Count how many of each unit type appear on the segment floor plans (pages 70-119)
3. Multiply: `fixtures_per_unit × number_of_units = total`

Example calculation for U1 (surface mount downlight):
```
A2 unit has 4x U1  ×  176 A2 units on plans  =   704
A3b unit has 5x U1 ×   82 A3b units on plans =   410
C4 unit has 5x U1  ×  142 C4 units on plans  =   710
C5 unit has 6x U1  ×   64 C5 units on plans  =   384
...and so on for all unit types...
Plus common area U1 fixtures from amenity plans
─────────────────────────────────────────────────
Excel total for U1:                             4,259
```

**For site/exterior fixtures** (AL1, BH1, etc.), the process is simpler:
Count each symbol on the site plan pages (25-32).

Text extraction from site plan pages found:
```
Page 25 (E1.1 - Segment 1 Site Plan): 5x "AL1"
Page 26 (E1.2 - Segment 2 Site Plan): 5x "AL1"
Page 31 (E1.7 - Courtyard 1):        34x "AL1"
Page 32 (E1.8 - Courtyard 2):        36x "AL1"
Page 60: 2x "AL1"
Page 63: 2x "AL1"
────────────────────────────────────────────
Text extraction total:                84x AL1
Excel total:                          86x AL1
Gap: ~2 symbols are graphical and didn't extract as text
```

**Important**: Text extraction does NOT reliably capture all fixture labels. Comparison:

| Fixture | Text Extraction | Excel (Actual) | Accuracy |
|---------|----------------|----------------|----------|
| AL1 | 84 | 86 | ~98% |
| B1 | 45 | 136 | ~33% |
| GA | 1 | 244 | ~0.4% |
| GA1 | 1 | 207 | ~0.5% |
| U1 | 56 | 4,259 | ~1.3% |
| RD8 | 56 | 627 | ~8.9% |

Most fixture symbols are **embedded in CAD graphics** and cannot be extracted as text. This is why the counting has been a manual visual process.

### Layer 3: Expand into Bill of Materials (Domain Knowledge)

A single fixture type on the drawing becomes **multiple line items** in the Excel output. CLI adds all required accessories, drivers, and mounting hardware.

**Example: AL1 (Landscape Accent Light)**

The drawing just shows "AL1" symbols on the landscape plan. CLI knows each AL1 needs:

| Row in Excel | Type | Qty | Catalog # | Description | How Qty Is Determined |
|---|---|---|---|---|---|
| 16 | AL1 | 86 | WAC 5011-30BZ | LANDSCAPE ACCENT | Direct count from plans |
| 17 | AL1 | 86 | WAC 5010-SNOOT-BZ | SNOOT | 1 per fixture = 86 |
| 18 | AL1 | 86 | WAC 9000-SP9-BZ | STAKE | 1 per fixture = 86 |
| 19 | AL1 | 25 | WAC 9075-TRN-SS | 75W DRIVER | 1 driver per ~3.4 fixtures |

**Example: AS1/AS2 (Tree-Mounted Accent Lights)**

The drawing shows AS1 and AS2 symbols grouped around trees, with annotations like "(1)AS1" and "(2)AS2". CLI reads the groupings and creates sub-groups:

Group 1 — Trees with 3 fixtures (1 AS1 + 2 AS2):
```
Row 20: AS1     | 3  | HKL ZXL16-IR1SA-ABR-UNIV14W-30E-LVR      | LED ACCENT LIGHT
Row 21: AS2     | 6  | HKL ZXL16-IR1SA-ABR-120V07W-30M-GSA-SOL   | LED ACCENT LIGHT
Row 22: AS1/AS2 | 3  | HKL TS-SO-C-3-BZ                          | TREE RING FOR (3) FIXTURES
Row 23:         | NOTE |                                           | QTY (1) AS1+(2) AS2 PER TREE RING
```

Group 2 — Trees with 4 fixtures (2 AS1 + 2 AS2):
```
Row 24: AS1     | 4  | HKL ZXL16-IR1SA-ABR-UNIV14W-30E-LVR      | LED ACCENT LIGHT
Row 25: AS2     | 4  | HKL ZXL16-IR1SA-ABR-120V07W-30M-GSA-SOL   | LED ACCENT LIGHT
Row 26: AS1/AS2 | 2  | HKL TS-SO-C-4-BZ                          | TREE RING FOR (4) FIXTURES
Row 27:         | NOTE |                                           | QTY (2) AS1+(2) AS2 PER TREE RING
```

Group 3 — Trees with 2 fixtures (2 AS2 only):
```
Row 28: AS2     | 6  | HKL ZXL16-IR1SA-ABR-120V07W-30M-GSA-SOL   | LED ACCENT LIGHT
Row 29: AS2     | 3  | HKL TS-SO-C-2-BZ                          | TREE RING FOR (2) FIXTURES
Row 30:         | NOTE |                                           | QTY (2) AS2 PER TREE RING
```

Group 4 — Trees with 4 fixtures (4 AS2):
```
Row 31: AS2     | 40 | HKL ZXL16-IR1SA-ABR-120V07W-30M-GSA-SOL   | LED ACCENT LIGHT
Row 32: AS2     | 10 | HKL TS-SO-C-4-BZ                          | TREE RING FOR (4) FIXTURES
Row 33:         | NOTE |                                           | QTY (4) AS2 PER TREE RING
```

**Example: B1 (LED Strip Light)**

The drawing shows "B1" labels. But some B1 fixtures are connected in rows to make longer runs. CLI determines run lengths from the plans:

```
Row 34: B1      | 136 | ELI 4-OC4-LED-4000L-DIM10-MVOLT-40K-85                    | 4' LED STRIP
Row 35: B1.8'   | 44  | ELI 4-OC4-LED-4000L-DIM10-MVOLT-40K-85-CRM-BRACKET-HARNESS | 4' LED STRIP (CONTINUOUS ROW MOUNTING)
Row 36:         | NOTE |                                                            | QTY (2) STRIPS CONNECTED TO MAKE 8' RUN X22
Row 37: B1.12'  | 48  | ELI 4-OC4-LED-4000L-DIM10-MVOLT-40K-85-CRM-BRACKET-HARNESS | 4' LED STRIP (CONTINUOUS ROW MOUNTING)
Row 38:         | NOTE |                                                            | QTY (3) STRIPS CONNECTED TO MAKE 12' RUN X16
```

Here CLI determined there are 22 locations needing 8' runs (2 strips each = 44) and 16 locations needing 12' runs (3 strips each = 48). This comes from **measuring the run lengths on the floor plans**.

---

## The Popeyes Example (Simple Case)

From `Email.txt`, Kaz provided the Popeyes counts directly in the email:
```
AE  6
A   26
EM  6
ER  2
EX  4
L-4  5
L-6  13
L-7  17
L-7E 3
LX2  4
LX4  4
XX  4
YY  5
```

The Popeyes PDF (`Newberg Popeyes Permit Set Revised_ E-Sheets.pdf`) is only 15 pages — a single small restaurant. The fixture labels on the floor plans are almost entirely graphical (text extraction found almost nothing). For simple projects like this, the counting is done purely by **visual inspection** of the floor plan pages.

---

## Excel Output Structure

The output file `AMLI-BREA, CA COUNTS.xlsx` has three sheets:

### Sheet: "Quote to Customer (HIDE COST!)"
The main output. Header section (rows 1-13) contains:
- Company info: `Commercial Lighting Industries, 81161 Indio Boulevard, Indio, CA 92201`
- Contact: `FARREN HALCOVICH`
- Notes: `***BASED ON IFC V2 SET ADDENDUM 4 ELECTRICAL PLANS DATED 1/16/26***`
- Notes: `***NOTE: LIGHTING CONTROLS NOT INCLUDED.`
- Notes: `***NOTE: EMERGENCY FIXTURES CONNECTED TO GENERATOR.`

Data section (row 14+) columns:
```
A: Type           - Fixture type code from drawing (e.g., "AL1", "GA", "U1")
B: Quantity        - Count (number or "NOTE")
C: CLI Catalog #   - CLI's internal catalog number (often blank)
D: Ceiling Type    - (often blank)
E: Ceiling Color   - (often blank)
F: (empty)
G: Catalog #       - Manufacturer catalog number that CLI sources (e.g., "WAC 5011-30BZ")
H: Custom          - Usually "YES"
I: Description     - Product description (e.g., "LANDSCAPE ACCENT", "75W DRIVER")
```

### Sheet: "Import"
System integration sheet with columns:
```
DocID | Customer Number | Item Number | QTY | Price | LineType | Sector | Jobname | Custom | RowNumber | WorkSheetName
```
This sheet uses formulas referencing the Quote sheet to pull data for import into CLI's ordering system.

### Sheet: "Integration"
Additional integration data.

---

## Summary: What Information Comes from Where

| Information | Source | Extractability |
|------------|--------|----------------|
| Fixture type codes (AL1, GA, U1...) | PDF Fixture Schedule | Text-extractable |
| Engineer's catalog numbers | PDF Fixture Schedule | Text-extractable |
| Fixture descriptions/specs | PDF Fixture Schedule | Text-extractable |
| Fixture counts (quantities) | PDF Floor Plans | **Mostly visual/graphical** — text extraction captures only ~1-33% of labels |
| Unit type × floor multipliers | PDF Segment Plans | Partially text-extractable (unit labels found ~795 times) |
| CLI catalog numbers | CLI domain knowledge | Not in PDF — CLI substitutes their own sourced products |
| Accessory quantities | CLI domain knowledge | Not in PDF — CLI adds drivers, mounts, hardware based on product specs |
| Grouping/run lengths | PDF Floor Plans + measurement | Visual inspection + physical measurement from scaled plans |
| Notes (e.g., "QTY (4) AS2 PER TREE RING") | CLI domain knowledge | Not in PDF — CLI writes these based on plan interpretation |
