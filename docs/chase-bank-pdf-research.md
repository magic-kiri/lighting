# Chase Bank Newport Beach - PDF Research Analysis

**PDF**: `20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf`
**Pages**: 173 total
**Project**: JPMFC - Jamboree and Santa Barbara Co-Location, 1470 Jamboree Rd, Newport Beach, CA
**Date**: 2026-03-13

---

## 1. PDF Structure Overview

The PDF is a **multi-discipline construction drawing set** ("All Trades") containing:

| Page Range | Sheet Series | Discipline | Count |
|-----------|-------------|-----------|-------|
| 1 | — | Cover Sheet | 1 |
| 2 | — | Sheet Index / General Info | 1 |
| 3–18 | A-002 to A-031 | Architectural: Symbols, Details, Schedules | 16 |
| 19–22 | A-101 to A-104 | Architectural: Demolition Plans & RCPs | 4 |
| 23–24 | A-201 to A-202 | Architectural: Construction Plans | 2 |
| 25–26 | A-301 to A-302 | Architectural: Power & Comm Plans | 2 |
| 27–28 | A-303 to A-304 | Architectural: Equipment Plans | 2 |
| **29–30** | **A-401 to A-402** | **Architectural: Reflected Ceiling Plans** | 2 |
| 31–73 | A-501 to A-968 | Architectural: Finish, Furniture, Elevations, Details | 43 |
| 74–79 | S-001 to S-202 | Structural | 6 |
| 80–99 | M-001 to M-804 | Mechanical (HVAC) | 20 |
| 100 | E-001 | Electrical: Cover Sheet | 1 |
| 101 | E-002 | Electrical: Notes | 1 |
| 102–103 | E-003 to E-004 | Electrical: Specifications | 2 |
| **104** | **E-005** | **Electrical: LIGHTING SCHEDULE** | **1** |
| 105–106 | E-006 to E-007 | Electrical: Title 24 Forms | 2 |
| 107–108 | E-101 to E-102 | Electrical: Power Demolition Plans | 2 |
| 109–110 | E-111 to E-112 | Electrical: Lighting Demolition Plans | 2 |
| 111–112 | E-201 to E-202 | Electrical: Power Plans | 2 |
| **113** | **E-211** | **Electrical: LIGHTING PLAN - Level 01** | **1** |
| **114** | **E-212** | **Electrical: LIGHTING PLAN - Level 02** | **1** |
| 115–117 | E-221 to E-223 | Electrical: Mech/Plumbing Power Plans | 3 |
| 118 | E-401 | Electrical: Enlarged Plan | 1 |
| 119–122 | E-501 to E-504 | Electrical: Details | 4 |
| 123 | E-601 | Electrical: Single Line Diagram | 1 |
| 124 | E-701 | Electrical: Panel Schedule | 1 |
| 125–135 | P-001 to P-701 | Plumbing | 11 |
| 136–148 | FA/FP series | Fire Alarm & Fire Protection (Gensler) | 13 |
| 149–173 | TC-000 to TC-603 | Telecommunications (RCDD) | 25 |

---

## 2. Where Lighting Types Are Defined

### Primary Source: E-005 "LIGHTING SCHEDULE" (PDF Page 104)

This is the **definitive source** of all lighting fixture types. It contains TWO side-by-side schedule tables:

| Table | Title | Content |
|-------|-------|---------|
| Left | "JPMC JAMBOREE (CHASE STANDARDS) LUMINAIRE SCHEDULE" | Chase standard fixtures (D1A, EX-2K2, ES DOWNLIGHT, L-307) |
| Right | "JPMC JAMBOREE AND SANTA BARBARA LUMINAIRE SCHEDULE" | Project-specific fixtures (D1A, D1B, D2, DF1-DF7, L1A, L2A, L2B, L5, L6, L8, L-22, X1, etc.) |

**CRITICAL FINDING**: The E-005 page is **almost entirely rasterized** (rendered as tiny image fragments):
- **4,135 embedded images** composing the schedule table
- Only **937 characters** of extractable text (just the title block)
- **Zero tables** extractable via pdfplumber
- The schedule content is NOT machine-readable from text extraction

**This means**: To read fixture type definitions from E-005, you MUST either:
1. Render the page to an image and use LLM vision / OCR
2. Or rely on the fixture labels found directly on the lighting plan pages

### Fixture Types Visible in E-005 (from visual inspection of rendered image)

**Left Table (Chase Standards):**
| Type | Description | Mounting |
|------|------------|---------|
| D1A | 3" Round Trim-less Downlight | Recessed |
| EX-2K2 | Existing 2x2 Troffer Light (relocated from demolition scope) | Recessed N/C |
| ES DOWNLIGHT | Existing Square Aperture Downlight (relocated) | Recessed |
| L-307 | 12" Linear Cove Light (Philips Color Kinetics) | Surface Mount |

**Right Table (Jamboree & Santa Barbara):**
| Type | Description |
|------|------------|
| D1A | 3" Recessed Downlight |
| D1B | 3" Recessed Downlight (variant) |
| D2 | 3" Adjustable Downlight |
| DF1 | 65" Decorative Pendant |
| DF3 | Decorative Suspended Linear |
| DF4 | Up/Down Pendant |
| DF5 | Eclipse Pendant |
| L1A | Recessed Linear (4'/6'/8' variants) |
| L2A | Cove Light (various custom lengths) |
| L2B | Cove Light (variant) |
| L5 | Linear (6'/8'/9' variants) |
| L6 | LED Tape Light |
| L8 | 4' Suspended Strip Light |
| L-22 | 4' LED Strip Light w/ Occupancy Sensor |
| X1 | Recessed Edgelit Exit Sign (SF/SD variants) |

### Secondary Source: E-001 Electrical Cover Sheet (PDF Page 100)

Contains a **symbol legend** on the left side showing electrical symbols including:
- DOWNLIGHT symbol
- EXIT SIGN symbols (1 face, 2 face)
- References to E-005 and E-701 schedules
- Mentions Daintree lighting controls

Also contains a **Daintree controls schedule** at the bottom listing control devices (wireless wall dimmers, area controllers, etc.).

---

## 3. Where to Count Fixture Quantities

### Primary Counting Pages

| PDF Page | Sheet | Title | Purpose | Fixture Labels Found |
|---------|-------|-------|---------|---------------------|
| **113** | **E-211** | Electrical Lighting Plan - Level 01 | New lighting for Level 1 | D1A: 7 |
| **114** | **E-212** | Electrical Lighting Plan - Level 02 | New lighting for Level 2 | D1A: 42, D1B: 14, D2: 10, DF3: 1, DF4: 1, DF5: 1, L1A: 44, L2A: 23, L2B: 5, L3: 1, L5: 7, L6: 2, L-22: 2, X1: 7 |

### Additional Pages with Fixture Labels

| PDF Page | Sheet | Title | Fixture Labels Found | Notes |
|---------|-------|-------|---------------------|-------|
| **29** | **A-401** | Reflected Ceiling Plan - Level 01 | (none extracted) | Architectural RCP; may have fixture symbols but not labeled with type codes |
| **30** | **A-402** | Reflected Ceiling Plan - Level 02 | D1A: 49, D1B: 13, D2: 8, DF1: 1, DF3: 1, DF4: 1, DF5: 1, L1A: 31, L2A: 10, L2B: 4, L5: 4, L6: 1, L-22: 3 | **Very rich in fixture labels!** Architectural RCP duplicates/complements E-212 |

### Key Observations

1. **Level 1 is mostly existing space** - only 7 new D1A downlights in the scope area (the dashed boundary on E-211 outlines the "scope of work" region)

2. **Level 2 is the main work area** - E-212 has 160 fixture label instances across 14 different types

3. **A-402 (Architectural RCP) has DIFFERENT counts than E-212 (Electrical Lighting Plan)**:
   - A-402 has D1A: 49 vs E-212 has D1A: 42
   - A-402 has DF1: 1 but E-212 does NOT show DF1
   - E-212 has L3: 1, X1: 7 but A-402 does not
   - This is because A-402 is the reflected ceiling plan (showing all ceiling elements) while E-212 is the lighting plan (showing circuiting and electrical connections)

4. **Some types from the Excel are NOT found on any page via text extraction**:
   - D1A-EM (emergency variant) - may be indicated by "EM" notation near D1A labels
   - DF1 - found on A-402 but not E-212
   - DF6, DF7 - "NO BID NOT SHOWN ON PLANS"
   - L-7, L-7-EM - "REMOVED PER LATEST PLANS"
   - L-411, L-412 - removed or not shown
   - L500 variants - all removed per latest plans
   - L8, L8EM - only 1 each per Excel; may be too small to detect
   - L-307 - found on E-211 as "(7) L-307" indicating 7 existing fixtures

5. **The "(7) L-307" notation**: The number in parentheses before a fixture type typically indicates the circuit number or a count multiplier, not the fixture type itself. In this case, it appears to reference 7 instances of L-307 (an existing fixture type from the Chase Standards schedule).

---

## 4. Extractability Analysis

### Text-Extractable Content (pdfplumber)

| Page | Sheet | Chars | Words | Tables | Fixture Labels Extractable? |
|------|-------|-------|-------|--------|---------------------------|
| 104 | E-005 | 937 | ~40 | 0 | **NO** - Schedule is rasterized images |
| 113 | E-211 | 7,849 | ~600 | 0 | **YES** - Labels like "D1A" are text |
| 114 | E-212 | 11,728 | ~900 | 0 | **YES** - Labels are text |
| 30 | A-402 | 6,910 | ~500 | 0 | **YES** - Labels are text |
| 100 | E-001 | 14,274 | ~1000 | 0 | **PARTIAL** - Symbol legend has some info |
| 124 | E-701 | 10,456 | ~800 | 0 | **NO** - Panel schedules, not fixture info |

### The E-005 Rasterization Problem

The lighting schedule on E-005 is composed of **4,135 tiny images** assembled into a visual table. This is a Bluebeam/Revit export artifact where the schedule was inserted as a raster graphic rather than vector text. The title block text IS extractable (it's in the standard Bluebeam template), but the schedule body content is image-only.

**Impact**: Fixture type definitions (names, descriptions, manufacturers, catalog numbers) cannot be extracted via text tools. Only LLM vision or OCR can read this content.

---

## 5. Comparison: PDF Extraction vs Excel Ground Truth

### Level 1 Fixtures (from Excel)

| Type | Excel Qty | Found on E-211? | Found on E-001? |
|------|----------|----------------|-----------------|
| D1A | 6 | YES (7 instances) | — |
| L-307 | (existing) | YES - "(7) L-307" | — |
| All others on Level 1 | 0 (REMOVED) | Not found | — |

### Level 2 Fixtures (from Excel)

| Type | Excel Qty | E-212 Count | A-402 Count | Match? |
|------|----------|-------------|-------------|--------|
| D1A | 31 | 42 | 49 | Over-count (includes EM variants + circuiting duplicates) |
| D1A-EM | 24+1 | 0 | 0 | Not separately labeled; likely "EM" annotations near D1A |
| D1B | 13 | 14 | 13 | Close |
| D2 | 8 | 10 | 8 | A-402 matches exactly |
| DF1 | 1 | 0 | 1 | Only on A-402 |
| DF3 | 1 | 1 | 1 | Match |
| DF4 | 1 | 1 | 1 | Match |
| DF5 | 1 | 1 | 1 | Match |
| DF6 | 0 | 0 | 0 | Not shown on plans |
| DF7 | 0 | 0 | 0 | Not shown on plans |
| L1A | 25+3+1+1+1+1=32 | 44 | 31 | A-402 closer; E-212 over-counts (includes circuit annotations) |
| L2A | 10 (various lengths) | 23 | 10 | A-402 matches; E-212 has circuit/annotation duplicates |
| L2B | 3 | 5 | 4 | Over-counted slightly |
| L5 | 4 (6'+8'+9') | 7 | 4 | A-402 matches |
| L6 | 2 (tape light) | 2 | 1 | E-212 matches |
| L8 | 1 | 0 | 0 | Not detected (too small or unlabeled?) |
| L8EM | 1 | 0 | 0 | Same |
| L-22 | 2 | 2 | 3 | E-212 matches exactly |
| X1 (SF) | 6 | 7 (all X1) | 0 | E-212 has X1 but doesn't distinguish SF/SD |
| X1 (SD) | 1 | (included above) | 0 | — |

### Key Insight: A-402 (RCP) vs E-212 (Lighting Plan)

**A-402 counts are generally closer to the Excel ground truth** than E-212 counts. This is because:
- The RCP shows fixtures as architectural elements (one symbol per fixture)
- The Electrical Lighting Plan (E-212) shows fixtures with circuiting annotations, which can cause the same fixture label to appear multiple times (once for the fixture, once for circuit routing)
- However, E-212 has fixture types that A-402 doesn't show (X1 exit signs, L3)

**Best strategy**: Use A-402 as the primary counting source, cross-reference with E-212 for types not shown on the RCP (exit signs, emergency fixtures).

---

## 6. Summary of Critical Pages

For automating the Chase Bank fixture takeoff, these are the essential pages:

### Must-Process Pages

| Priority | PDF Page | Sheet | Purpose |
|----------|---------|-------|---------|
| 1 | **104** | E-005 | Fixture TYPE DEFINITIONS (requires LLM vision - rasterized) |
| 2 | **114** | E-212 | Fixture COUNTING - Level 02 (primary, text-extractable) |
| 3 | **113** | E-211 | Fixture COUNTING - Level 01 (text-extractable) |

### Valuable Cross-Reference Pages

| Priority | PDF Page | Sheet | Purpose |
|----------|---------|-------|---------|
| 4 | **30** | A-402 | RCP Level 02 - more accurate counts for some types |
| 5 | **29** | A-401 | RCP Level 01 |
| 6 | **100** | E-001 | Electrical cover - symbol legend, controls schedule |

### Counting Challenges

1. **EM (Emergency) variants** (D1A-EM, L1A-EM, etc.) are NOT separately labeled on the plans - they're indicated by "EM" annotations or circuit markings near the base fixture label
2. **L2A and L2B** have custom lengths (6' to 92') - the Excel breaks these out separately but the plans just show "L2A" at each location
3. **Some labels appear multiple times** due to circuit annotation arrows pointing to/from fixture symbols
4. **L-307** appears with a "(7)" prefix notation on Level 1 - likely meaning circuit 7 or 7 units
5. **Exit signs (X1)** don't distinguish single-face (SF) vs double-face (SD) in the label text

---

## 7. Recommended Extraction Approach

```
Step 1: Identify fixture types
  - Render E-005 (page 104) to image
  - Use LLM vision to read the luminaire schedule table
  - Extract: Type, Description, Manufacturer, Catalog #, Mounting

Step 2: Count fixtures on Level 1
  - Extract text from E-211 (page 113) via pdfplumber
  - Count occurrences of each fixture type label
  - Cross-reference with A-401 (page 29) if available

Step 3: Count fixtures on Level 2
  - Extract text from E-212 (page 114) via pdfplumber
  - Extract text from A-402 (page 30) for comparison
  - Use spatial analysis to de-duplicate circuit annotation repeats
  - For types where A-402 count matches Excel better, prefer A-402

Step 4: Reconcile & Output
  - Combine Level 1 + Level 2 counts
  - Flag EM variants (may need LLM vision on plan images)
  - Flag removed types (zero quantity)
  - Output CSV: Type, Quantity, Confidence
```
