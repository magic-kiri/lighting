import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
