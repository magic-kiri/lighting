import logging
import os
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from app.pipeline import run_pipeline, run_fixture_discovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fixture Extractor",
    description="Extract lighting fixture counts from engineering drawing PDFs",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "input-files")
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/")
async def serve_frontend():
    """Serve the frontend single-page app."""
    return FileResponse(
        os.path.join(FRONTEND_DIR, "index.html"),
        media_type="text/html",
    )


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
    """Extract fixture counts from a PDF file in input-files/."""
    logger.info("POST /extract — file_path=%s", request.file_path)
    full_path = os.path.normpath(os.path.join(INPUT_DIR, request.file_path))

    if not os.path.isfile(full_path):
        logger.warning("File not found: %s", full_path)
        return JSONResponse(content={
            "status": "error",
            "error": f"File not found: {request.file_path}",
            "fixture_counts": [],
            "csv_path": None,
        })

    t0 = time.time()
    result = run_pipeline(full_path, output_dir="data/output")
    logger.info("POST /extract complete — status=%s, %.1fs", result.get("status"), time.time() - t0)
    return JSONResponse(content=result)


@app.post("/fixtures")
async def discover_fixtures(request: ExtractRequest):
    """Discover fixture types from a PDF (stages 1-3 only, no counting)."""
    logger.info("POST /fixtures — file_path=%s", request.file_path)
    full_path = os.path.normpath(os.path.join(INPUT_DIR, request.file_path))

    if not os.path.isfile(full_path):
        logger.warning("File not found: %s", full_path)
        return JSONResponse(content={
            "status": "error",
            "error": f"File not found: {request.file_path}",
            "fixture_types": [],
        })

    t0 = time.time()
    result = run_fixture_discovery(full_path)
    logger.info("POST /fixtures complete — status=%s, %.1fs", result.get("status"), time.time() - t0)
    return JSONResponse(content=result)


@app.get("/health")
async def health():
    return {"status": "ok"}
