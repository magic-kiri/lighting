import os
import tempfile
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.pipeline import run_pipeline

app = FastAPI(
    title="Fixture Extractor",
    description="Extract lighting fixture counts from engineering drawing PDFs",
    version="0.1.0",
)


@app.post("/extract")
async def extract_fixtures(file: UploadFile = File(...)):
    """Upload a PDF and extract fixture counts."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Save uploaded file to temp location
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        result = run_pipeline(tmp_path, output_dir="data/output")
        return JSONResponse(content=result)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/health")
async def health():
    return {"status": "ok"}
