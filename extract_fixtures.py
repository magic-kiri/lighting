#!/usr/bin/env python3
"""
Lighting Fixture Type Extractor
=================================
Extracts unique lighting fixture types from engineering drawing PDFs.

Strategy:
  1. Find electrical section pages (E-xxx sheet numbers, or entire PDF if electrical-only)
  2. Classify pages: schedule vs lighting plan vs other
  3. Schedule pages: multi-crop high-DPI LLM vision with dual-model extraction
  4. Lighting plan pages: text extraction → LLM filtering + vision supplement
  5. Combine, normalize, deduplicate

Usage:
    python extract_fixtures.py <pdf_path> [--output csv] [--expected csv]
"""

import os, sys, re, csv, json, time, argparse, io, base64
from pathlib import Path

import pdfplumber
import fitz  # PyMuPDF
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def load_env(env_path=".env"):
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ---------------------------------------------------------------------------
# LLM Clients
# ---------------------------------------------------------------------------

class GeminiClient:
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self.model = genai.GenerativeModel(os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"))
        self.name = "Gemini"

    def call(self, contents, retries=3):
        for attempt in range(retries):
            try:
                resp = self.model.generate_content(contents)
                return resp.text
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    time.sleep(2 ** (attempt + 2)); continue
                raise
        raise RuntimeError("Gemini failed")


class OpenAIClient:
    def __init__(self):
        import openai
        self.client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4.1")
        self.name = "OpenAI"

    def call(self, contents, retries=3):
        # Convert Gemini-style contents to OpenAI format
        msgs = []
        user_content = []
        for item in (contents if isinstance(contents, list) else [contents]):
            if isinstance(item, str):
                user_content.append({"type": "text", "text": item})
            elif isinstance(item, dict) and "data" in item:
                b64 = base64.b64encode(item["data"]).decode()
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"}
                })
        for attempt in range(retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": user_content}],
                    max_tokens=4096,
                )
                return resp.choices[0].message.content
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower():
                    time.sleep(2 ** (attempt + 2)); continue
                raise
        raise RuntimeError("OpenAI failed")


# ---------------------------------------------------------------------------
# PDF Rendering
# ---------------------------------------------------------------------------

def render_crops(pdf_path, page_num, grid=(3, 2), dpi=300, max_dim=3000):
    """Render page as grid of overlapping crops."""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    doc.close()

    W, H = img.size
    cols, rows = grid
    overlap = 0.08

    crops = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * W / cols - overlap * W))
            y0 = max(0, int(r * H / rows - overlap * H))
            x1 = min(W, int((c + 1) * W / cols + overlap * W))
            y1 = min(H, int((r + 1) * H / rows + overlap * H))
            crop = img.crop((x0, y0, x1, y1))
            cw, ch = crop.size
            if max(cw, ch) > max_dim:
                s = max_dim / max(cw, ch)
                crop = crop.resize((int(cw * s), int(ch * s)), Image.LANCZOS)
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            crops.append(buf.getvalue())
    return crops


def render_page(pdf_path, page_num, dpi=200, max_dim=4096):
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    doc.close()
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Phase 1: Find electrical section
# ---------------------------------------------------------------------------

def find_electrical_pages(pdf_path):
    """Find pages belonging to the electrical section."""
    print("Phase 1: Finding electrical pages...")
    pdf = pdfplumber.open(pdf_path)
    total = len(pdf.pages)
    page_data = {}
    e_sheet_pages = []

    for i, p in enumerate(pdf.pages):
        text = p.extract_text() or ""
        page_data[i] = text
        # E-xxx sheet numbers in title block (1-3 occurrences = own page)
        sheets = re.findall(r'\bE-\d{3}\b', text)
        if 1 <= len(sheets) <= 5:
            e_sheet_pages.append(i)

    pdf.close()

    if e_sheet_pages:
        # Include continuous range from first to last E-page
        first, last = min(e_sheet_pages), max(e_sheet_pages)
        e_pages = list(range(first, last + 1))
        print(f"  Found E-series sheets: pages {first}-{last} ({len(e_pages)} pages)")
    else:
        # Check if entire PDF is electrical
        elec = sum(1 for t in page_data.values()
                   if "ELECTRICAL" in t.upper() or "LIGHTING" in t.upper() or "FIXTURE" in t.upper())
        if elec > total * 0.2:
            e_pages = list(range(total))
            print(f"  Electrical-only PDF: all {total} pages")
        else:
            # Fallback: pages with lighting/fixture keywords
            e_pages = [i for i, t in page_data.items()
                       if any(kw in t.upper() for kw in ["LIGHTING", "FIXTURE", "LUMINAIRE"])]
            print(f"  Fallback: {len(e_pages)} pages with lighting keywords")

    print(f"  Total pages: {total}, Electrical: {len(e_pages)}")
    return page_data, e_pages


# ---------------------------------------------------------------------------
# Phase 2: Classify pages
# ---------------------------------------------------------------------------

def classify_pages(page_data, e_pages):
    """Classify electrical pages into schedule/plan/other."""
    print("\nPhase 2: Classifying pages...")
    schedule, plan, other = [], [], []

    for i in e_pages:
        text = page_data.get(i, "")
        upper = text.upper()
        text_len = len(text)

        # Schedule pages: have "SCHEDULE" keyword BUT are NOT heavy-text pages.
        # Real schedule pages have minimal extractable text (schedule is graphical)
        # while general notes pages have lots of text and just mention "schedule".
        is_schedule = False
        if any(kw in upper for kw in [
            "LIGHTING SCHEDULE", "LUMINAIRE SCHEDULE", "FIXTURE SCHEDULE"
        ]):
            # True schedule pages typically have < 2000 chars of extractable text
            # (only title block text extracts, not the table itself)
            # General notes pages have 10000+ chars
            if text_len < 5000:
                is_schedule = True
            else:
                # Heavy text page — check if "SCHEDULE" appears in the title block
                # (last few lines) rather than body text
                last_500 = text[-500:].upper() if len(text) > 500 else upper
                if any(kw in last_500 for kw in [
                    "LIGHTING SCHEDULE", "LUMINAIRE SCHEDULE", "FIXTURE SCHEDULE"
                ]):
                    is_schedule = True

        if is_schedule:
            schedule.append(i)
        elif text_len > 500:
            # Any electrical page with substantial text might have fixture labels.
            # The LLM filtering in Phase 4 will separate real types from noise.
            plan.append(i)
        else:
            other.append(i)

    print(f"  Schedule: {schedule}, Plans: {plan}, Other: {len(other)}")
    return schedule, plan, other


# ---------------------------------------------------------------------------
# Phase 3: Schedule extraction (dual-model, multi-crop)
# ---------------------------------------------------------------------------

SCHEDULE_PROMPT = """This is a cropped section from a LIGHTING FIXTURE SCHEDULE in engineering drawings.

Extract EVERY fixture TYPE CODE visible in this table section.

Type codes appear in the TYPE column (leftmost). Examples:
  D1A, D1A-EM, D1B, D2, DF1, DF3, DF6, L-2, L-2-EM, L-7, L-411, L1A, L500, L8, X1

RULES:
- Read EVERY table row — don't skip any
- Include -EM (emergency) variants
- Include size qualifiers: L1A (4'), L500 (6'), X1 (SF), X1 (SD)
- Do NOT invent types — only report what you can actually read
- Do NOT confuse row numbers with type codes
- Ignore descriptions, catalog numbers, voltages — just the TYPE code

Return a JSON array of strings. If no table: []"""


def extract_from_schedules(clients, pdf_path, schedule_pages):
    """Extract fixture types from schedule pages using dual-model multi-crop."""
    print("\nPhase 3: Schedule extraction (multi-crop, dual-model)...")
    all_types = set()

    if not schedule_pages:
        print("  No schedule pages")
        return all_types

    for page_num in schedule_pages:
        print(f"  Page {page_num}:")
        crops = render_crops(pdf_path, page_num, grid=(3, 2), dpi=350, max_dim=3500)

        for idx, crop in enumerate(crops):
            for client in clients:
                try:
                    resp = client.call([
                        {"mime_type": "image/png", "data": crop},
                        SCHEDULE_PROMPT,
                    ])
                    types = parse_json_array(resp)
                    types = filter_hallucinations(types)
                    if types:
                        print(f"    Crop {idx+1} ({client.name}): {types}")
                        all_types.update(types)
                except Exception as e:
                    print(f"    Crop {idx+1} ({client.name}): ERROR {e}")
            time.sleep(0.5)

    # Check adjacent pages
    for sp in list(schedule_pages):
        for adj in [sp - 1, sp + 1]:
            if adj >= 0 and adj not in schedule_pages:
                img = render_page(pdf_path, adj, dpi=200)
                for client in clients:
                    try:
                        resp = client.call([
                            {"mime_type": "image/png", "data": img},
                            "Is this a lighting fixture schedule? If yes, extract all type codes as JSON array. If no: []"
                        ])
                        types = parse_json_array(resp)
                        types = filter_hallucinations(types)
                        if types:
                            print(f"    Adjacent page {adj} ({client.name}): {types}")
                            all_types.update(types)
                    except:
                        pass

    print(f"  Schedule total: {len(all_types)} types")
    return all_types


# ---------------------------------------------------------------------------
# Phase 4: Plan extraction (text→LLM + vision)
# ---------------------------------------------------------------------------

PLAN_TEXT_PROMPT = """Below is text from electrical engineering LIGHTING PLAN pages.

Identify ALL unique lighting fixture TYPE CODES.

Fixture type codes are short alphanumeric codes (1-10 chars) identifying specific light fixtures.
Common patterns include:
  - Letter(s) + number(s): D1A, DF3, L-2, L1A, X1, AL1, B1, GH2, RD2, SC1, SR1, SS9
  - With size: L500 (4'), L5 (6'), WS1 4'8"
  - With EM suffix: D1A-EM, LP1 EM, L-7-EM
  - Combined: AS1/AS2, SC1/SC3

NOT fixture types (ignore these):
  - Room/area numbers: 100, 201, ROOM 220, AREA 101
  - Panel references: PP1, PP3:23, PANEL A
  - Sheet references: E-211, A-950, SHEET 5
  - Dimensions: 66", 8'-0", 12'-6"
  - Circuit/branch IDs with long suffixes
  - General words: EXISTING, NEW, VERIFY, TYP, NIC

TEXT:
{text}

Return a JSON array of unique fixture type codes only."""


def extract_from_plans(client, pdf_path, page_data, plan_pages):
    """Extract from lighting plan pages via text + LLM, plus vision supplement."""
    print("\nPhase 4: Plan extraction...")
    all_types = set()

    if not plan_pages:
        return all_types

    # Text-based extraction
    combined = ""
    for pn in plan_pages:
        text = page_data.get(pn, "")
        if len(text) > 200:
            combined += f"\n--- PAGE {pn} ---\n{text}\n"

    if combined:
        print(f"  Text analysis of {len(plan_pages)} plan pages...")
        for start in range(0, len(combined), 60000):
            chunk = combined[start:start+60000]
            resp = client.call(PLAN_TEXT_PROMPT.format(text=chunk))
            types = parse_json_array(resp)
            for t in types:
                t = str(t).strip()
                if not t or len(t) > 25:
                    continue
                # Filter common non-fixture prefixes
                if re.match(r'^(PP\d|Z#|FEC|CEF)', t):
                    continue
                all_types.add(t)
        print(f"    Text found: {sorted(all_types)}")

    # Vision supplement on sample of plan pages
    sample = plan_pages[:10]
    print(f"  Vision on {len(sample)} plan pages...")
    for pn in sample:
        img = render_page(pdf_path, pn, dpi=180)
        try:
            resp = client.call([
                {"mime_type": "image/png", "data": img},
                """This is a LIGHTING PLAN page. Extract unique fixture type LABELS visible near lighting symbols.
Types look like: D1A, L-2, L1A, DF3, X1, L500, L8, etc.
NOT: room numbers, panel names (PP1-PP4), dimensions, sheet refs.
Return JSON array. If none: []"""
            ])
            types = parse_json_array(resp)
            for t in types:
                t = str(t).strip()
                if t and len(t) < 20 and re.match(r'^[A-Z]', t):
                    if not re.match(r'^(PP\d|Z#|FEC)', t):
                        all_types.add(t)
        except:
            pass

    print(f"  Plan total: {len(all_types)} types")
    return all_types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_json_array(text):
    try:
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except:
        pass
    return []


def filter_hallucinations(types):
    """Filter obviously wrong entries."""
    out = []
    for t in types:
        t = str(t).strip()
        if not t or len(t) > 30:
            continue
        # Known non-fixture tokens
        if t.upper() in ("EM", "ED", "EX", "RC", "RM", "NO_SCHEDULE", "NONE",
                         "N/A", "TYPE", "QTY", "DESCRIPTION", "MANUFACTURER",
                         "CATALOG", "VOLTAGE", "WATTAGE", "LAMP", "NOTES"):
            continue
        # Pure numbers
        if re.match(r'^\d+$', t):
            continue
        # Contains special chars that real fixture types don't have
        # (but allow / for types like AS1/AS2, SC1/SC3)
        if any(c in t for c in ['\\', '@', '#', '$']):
            continue
        # Reject sequential hallucination patterns (e.g., D1, D2, ..., D100)
        if re.match(r'^(SPN\d|RF-\d|EZ-\d|EF-\d)', t.upper()):
            continue
        out.append(t)
    return out


def normalize(code):
    """Normalize a fixture type code for dedup/comparison.

    Strategy: STRIP separators between letter prefix and numbers so that
    L-2, L 2, L2 all become L2. Both found and expected go through this,
    so comparison works regardless of which form the LLM returns.
    """
    code = str(code).strip().upper()
    if not code:
        return ""
    code = code.replace('"', "'").replace('\u201c', "'").replace('\u201d', "'")
    code = re.sub(r'\(ALT\)', '', code).strip()

    # Normalize EM suffix: "L1A EM" → "L1A-EM"
    code = re.sub(r'\s+EM$', '-EM', code)
    code = re.sub(r'\s+EM\b', '-EM', code)
    # "L8EM" → "L8-EM" (no space or hyphen before EM)
    code = re.sub(r'(\d)EM\b', r'\1-EM', code)

    # Normalize foot marks: "6ft" → "6'"
    code = re.sub(r'(\d+)\s*(?:FT|FOOT)\b', r"\1'", code, flags=re.IGNORECASE)

    # Remove leading zeros: DF03 → DF3
    m = re.match(r'^([A-Z]+)0+(\d+.*)$', code)
    if m:
        code = m.group(1) + m.group(2)

    # Strip hyphens/spaces between letter prefix and number part
    # L-2 → L2, LT-106 → LT106, L 7 → L7
    # This preserves -EM suffix and (size) qualifiers naturally
    m = re.match(r'^([A-Z]+)[\s-]+(\d.*)$', code)
    if m:
        code = m.group(1) + m.group(2)

    code = re.sub(r'\s+', ' ', code)
    return code


def deduplicate(types):
    seen = {}
    for t in types:
        n = normalize(t)
        if n and len(n) >= 2:
            if n not in seen:
                seen[n] = t
    return sorted(seen.keys())


def compare(found, expected_csv):
    if not os.path.exists(expected_csv):
        return
    with open(expected_csv) as f:
        expected = {normalize(r.get("Type", "")) for r in csv.DictReader(f) if r.get("Type", "").strip()}
    found_n = {normalize(t) for t in found}
    matched = found_n & expected
    missed = expected - found_n
    extra = found_n - expected
    print(f"\n{'='*60}")
    print(f"COMPARISON ({Path(expected_csv).name})")
    print(f"{'='*60}")
    print(f"Expected: {len(expected)}, Found: {len(found_n)}, Matched: {len(matched)}")
    print(f"Recall: {len(matched)/max(len(expected),1)*100:.1f}%, Precision: {len(matched)/max(len(found_n),1)*100:.1f}%")
    if missed:
        print(f"\nMISSED ({len(missed)}):")
        for t in sorted(missed): print(f"  - {t}")
    if extra:
        print(f"\nEXTRA ({len(extra)}):")
        for t in sorted(extra): print(f"  + {t}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def extract_fixture_types(pdf_path):
    load_env()

    # Initialize both LLM clients
    clients = []
    if os.getenv("GOOGLE_API_KEY"):
        try:
            clients.append(GeminiClient())
        except Exception as e:
            print(f"Gemini init failed: {e}")
    if os.getenv("OPENAI_API_KEY"):
        try:
            clients.append(OpenAIClient())
        except Exception as e:
            print(f"OpenAI init failed: {e}")

    if not clients:
        print("ERROR: No LLM API keys available")
        sys.exit(1)

    primary = clients[0]
    print(f"Processing: {pdf_path}")
    print(f"LLM clients: {[c.name for c in clients]}\n")

    # Phase 1-2
    page_data, e_pages = find_electrical_pages(pdf_path)
    schedule, plan, other = classify_pages(page_data, e_pages)

    # Phase 3: Schedule extraction with all available clients
    schedule_types = extract_from_schedules(clients, pdf_path, schedule)

    # Phase 4: Plan extraction with primary client
    plan_types = extract_from_plans(primary, pdf_path, page_data, plan)

    # Phase 4b: Check other electrical pages with any text content
    extra_plan_pages = [p for p in other if len(page_data.get(p, "")) > 200]
    if extra_plan_pages:
        extra_types = extract_from_plans(primary, pdf_path, page_data, extra_plan_pages)
        plan_types.update(extra_types)

    # Combine
    all_types = set()
    all_types.update(schedule_types)
    all_types.update(plan_types)

    result = deduplicate(all_types)

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(result)} unique fixture types")
    print(f"{'='*60}")
    for t in result:
        print(f"  {t}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path")
    parser.add_argument("--output", "-o")
    parser.add_argument("--expected", "-e")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"ERROR: {args.pdf_path} not found"); sys.exit(1)

    types = extract_fixture_types(args.pdf_path)

    if args.output:
        with open(args.output, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["Type"])
            for t in types: w.writerow([t])
        print(f"\nSaved: {args.output}")

    if args.expected:
        compare(types, args.expected)


if __name__ == "__main__":
    main()
