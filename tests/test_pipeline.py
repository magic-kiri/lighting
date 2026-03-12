import pytest
import os
from app.pipeline import run_pipeline

CHASE_PDF = "20251119_JPMFC_Jamboree_SB_Revision to Permit_IFC_All Trades.pdf"


def test_pipeline_chase_bank():
    result = run_pipeline(CHASE_PDF, output_dir="data/output")
    assert result["status"] == "success"
    assert len(result["fixture_counts"]) > 0
    assert os.path.exists(result["csv_path"])
    # Check that at least some known types are present
    types_found = [fc["type"] for fc in result["fixture_counts"]]
    assert any(t in types_found for t in ["D1A", "L1A", "X1"])
