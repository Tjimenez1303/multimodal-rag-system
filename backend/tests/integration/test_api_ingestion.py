from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag import bootstrap

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def client(
    engine: AsyncEngine,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path))
    monkeypatch.setenv("LOG_FORMAT", "console")
    return TestClient(bootstrap.create_api_app())


def test_upload_is_stored_registered_and_queued(
    client: TestClient, tmp_path: Path
) -> None:
    pdf = (FIXTURES / "split_table.pdf").read_bytes()

    with client:
        first = client.post(
            "/api/v1/documents", files={"file": ("torque.pdf", pdf, "application/pdf")}
        )
        again = client.post(
            "/api/v1/documents", files={"file": ("copy.pdf", pdf, "application/pdf")}
        )
        job = client.get(first.headers["location"])

    assert first.status_code == 202
    assert again.status_code == 202
    assert again.json() == first.json()
    assert job.json()["status"] == "pending"
    assert job.json()["max_attempts"] == 3
    [stored] = (tmp_path / "documents").iterdir()
    assert stored.read_bytes() == pdf
    assert not any((tmp_path / "uploads").iterdir())


def test_text_renamed_to_pdf_is_rejected(client: TestClient) -> None:
    with client:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("x.pdf", (FIXTURES / "not_a_pdf.pdf").read_bytes())},
        )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"
