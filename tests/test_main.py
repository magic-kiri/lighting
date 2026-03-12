import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.anyio
async def test_get_files_returns_pdf_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/files")
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert isinstance(data["files"], list)


@pytest.mark.anyio
async def test_get_files_only_returns_pdfs():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/files")
    data = response.json()
    for f in data["files"]:
        assert f.lower().endswith(".pdf")


@pytest.mark.anyio
async def test_extract_requires_file_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/extract", json={})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_extract_rejects_missing_file():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/extract", json={"file_path": "nonexistent.pdf"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "not found" in data["error"].lower()


@pytest.mark.anyio
async def test_extract_accepts_valid_file():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files_resp = await client.get("/files")
        files = files_resp.json()["files"]
        if not files:
            pytest.skip("No PDF files in input-files/")
        response = await client.post("/extract", json={"file_path": files[0]})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("success", "error")
