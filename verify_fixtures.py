#!/usr/bin/env python3
"""Verify fixture type discovery against ground-truth CSVs.

Usage:
    python verify_fixtures.py [--url http://localhost:8000]
"""
import csv
import json
import re
import sys
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

# --- Ground truth ---
CHASE_CSV = "chase-bank-newport-beach-counts.csv"
CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"
CHASE_EXPECTED = [
    "D1A", "D1A-EM", "D1B", "D2",
    "DF1", "DF3", "DF4", "DF5", "DF6", "DF7",
    "L-2", "L-2-EM", "L-7", "L-7-EM", "L-22", "L-411", "L-412",
    "L1A", "L1A-EM",
    "L2A", "L2B", "L3", "L4", "L5", "L6",
    "L500", "L500-EM",
    "L8", "L8EM",
    "X1",
]

AMLI_CSV = "amli-brea-counts.csv"
AMLI_PDF = "04_Electrical_1-16-2026.pdf"
AMLI_EXPECTED = [
    "AL1",
    "AS1", "AS1/AS2", "AS2",
    "B1", "B1.8'", "B1.12'", "B2", "B3", "B4",
    "BH1", "BH2",
    "BX(D)", "BX(S)",
    "DF1", "DF1A", "DF4",
    "DP3", "DW1",
    "FS1", "FS2", "FS3", "FS4",
    "GA", "GA1",
    "GH2", "GH2A", "GH3", "GH4",
    "GL2",
    "LP1", "LP1 EM", "LP2", "LP2 EM", "LP3", "LP3A", "LP3B",
    "LR1", "LR3", "LR3 EM", "LR5",
    "LS2", "LS2A", "LS3",
    "LT-101", "LT-102", "LT-103", "LT-104", "LT-104.1", "LT-104.2", "LT-105",
    "LT106", "LT106.1", "LT-106.2", "LT-106.3", "LT-106.4", "LT-106.5",
    "LT-107", "LT-108", "LT-109", "LT-110", "LT-112", "LT-113", "LT-115", "LT-116", "LT-117", "LT-118",
    "PH1", "PH2", "PH3", "PH3-POLE",
    "RA1", "RA1A", "RA2", "RA3", "RA4", "RA5",
    "RD2", "RD3", "RD4", "RD6A", "RD7", "RD8",
    "RW1", "RW3",
    "SC1", "SC1/SC3", "SC2", "SC3",
    "SR1", "SR2",
    "SS3", "SS6", "SS6A", "SS7", "SS9",
    "U1", "U1A", "U2", "U3", "U4", "U5", "U8", "U9",
    "WR1", "WR2", "WS1", "WS3", "WS4",
    "XA", "XK",
]


def normalize(code: str) -> str:
    """Normalize a type code for comparison.

    Strip parenthesized suffixes, size suffixes like 4'8",
    then remove dashes, spaces, underscores, quotes (but keep dots and slashes).
    """
    code = code.strip()
    # Strip parenthesized suffixes: L1A (4') -> L1A
    code = re.sub(r'\s*\([^)]*\)\s*$', '', code)
    # Strip trailing size like 4'8", 7'6" (space-separated)
    code = re.sub(r"""\s+\d+'[\d"]*$""", '', code)
    # Normalize: remove dashes, spaces, underscores, quotes
    normalized = ""
    for ch in code:
        if ch in ('-', ' ', '_', '"', "'", '`'):
            continue
        normalized += ch
    return normalized.upper()


def call_api(file_path: str) -> list[str]:
    """Call POST /fixtures and return list of type codes."""
    url = f"{BASE_URL}/fixtures"
    data = json.dumps({"file_path": file_path}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        print(f"  ERROR calling API: {e}")
        return []

    if result.get("status") != "success":
        print(f"  API error: {result.get('errors', [])}")
        return []

    return result.get("fixture_types", [])


def verify(name: str, pdf_file: str, expected_types: list[str]):
    """Run verification for a single dataset."""
    print(f"\n{'='*60}")
    print(f"Dataset: {name}")
    print(f"{'='*60}")

    print(f"Calling API for {pdf_file}...")
    returned = call_api(pdf_file)
    print(f"API returned {len(returned)} types")

    # Normalize both sides
    expected_norm = {normalize(t): t for t in expected_types}
    returned_norm = {normalize(t): t for t in returned}

    # Compute matches
    matched_expected = set()
    matched_returned = set()
    for en, eo in expected_norm.items():
        if en in returned_norm:
            matched_expected.add(en)
            matched_returned.add(en)

    missing_norm = set(expected_norm.keys()) - matched_expected
    false_pos_norm = set(returned_norm.keys()) - matched_returned

    missing = sorted([expected_norm[n] for n in missing_norm])
    false_positives = sorted([returned_norm[n] for n in false_pos_norm])

    total_expected = len(expected_types)
    total_returned = len(returned)
    matched = len(matched_expected)

    recall = matched / total_expected * 100 if total_expected else 0
    precision = matched / total_returned * 100 if total_returned else 0

    print(f"\nTotal expected:   {total_expected}")
    print(f"Total returned:   {total_returned}")
    print(f"Matched:          {matched}")
    print(f"Missing:          {len(missing)}  {missing}")
    print(f"False positives:  {len(false_positives)}  {false_positives}")
    print(f"Recall:           {recall:.1f}%")
    print(f"Precision:        {precision:.1f}%")

    if returned:
        print(f"\nAll returned types: {sorted(returned)}")

    return recall, precision, missing, false_positives


if __name__ == "__main__":
    print("Fixture Type Verification")
    print("=" * 60)

    r1, p1, m1, fp1 = verify("Chase Bank", CHASE_PDF, CHASE_EXPECTED)
    r2, p2, m2, fp2 = verify("AMLI BREA", AMLI_PDF, AMLI_EXPECTED)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Chase Bank:  Recall={r1:.1f}%  Precision={p1:.1f}%  Missing={len(m1)}  FP={len(fp1)}")
    print(f"AMLI BREA:   Recall={r2:.1f}%  Precision={p2:.1f}%  Missing={len(m2)}  FP={len(fp2)}")
