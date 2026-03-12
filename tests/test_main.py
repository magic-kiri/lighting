import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.anyio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_get_files_returns_pdf_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/files")
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert isinstance(data["files"], list)
    for f in data["files"]:
        assert f.lower().endswith(".pdf")


@pytest.mark.anyio
async def test_extract_rejects_missing_file():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/extract", json={"file_path": "nonexistent.pdf"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert "not found" in data["error"].lower()


@pytest.mark.anyio
async def test_extract_requires_file_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/extract", json={})
    assert response.status_code == 422
