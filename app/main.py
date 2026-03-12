import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Commercial Lighting - Fixture Takeoff")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "input-files")


@app.get("/files")
async def list_files():
    """List all PDF files available in the input-files directory."""
    files = []
    if os.path.isdir(INPUT_DIR):
        files = sorted(
            f for f in os.listdir(INPUT_DIR)
            if f.lower().endswith(".pdf")
        )
    return {"files": files}


class ExtractRequest(BaseModel):
    file_path: str


@app.post("/extract")
async def extract_counts(request: ExtractRequest):
    """Extract fixture counts from a PDF file.
    Currently a stub — returns mock data structure.
    The backend agent will implement the real pipeline.
    """
    full_path = os.path.join(INPUT_DIR, request.file_path)

    if not os.path.isfile(full_path):
        return {
            "status": "error",
            "error": f"File not found: {request.file_path}",
            "fixture_counts": [],
            "csv_path": None,
        }

    # Stub response — backend agent will replace with real pipeline
    return {
        "status": "success",
        "project_name": os.path.splitext(request.file_path)[0],
        "pattern": "direct_counting",
        "fixture_counts": [],
        "csv_path": None,
        "pages_analyzed": {
            "lighting_plans": [],
            "fixture_schedule": [],
            "unit_plans": [],
        },
        "schedule_types_found": 0,
        "errors": [],
    }
