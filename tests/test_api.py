"""End-to-end tests for the parser service and the HTTP API."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_parser
from app.main import create_app


class TestParserService:
    """Tests for ResumeParserService using the parser_with_fake_llm fixture."""

    def test_end_to_end_with_docx(self, parser_with_fake_llm, sample_docx_bytes: bytes) -> None:
        result = parser_with_fake_llm.parse(sample_docx_bytes, "resume.docx")

        # Regex extraction should have populated these from the raw text
        assert result.personal.email == "tahir.ahmed@example.com"
        assert result.personal.phone is not None

        # LLM (fake) should have filled in the rest
        assert result.personal.full_name == "Tahir Ahmed"
        assert len(result.experience) == 1
        assert result.experience[0].company == "Acme Corp"
        assert result.raw_text_length > 0
        assert result.request_id

    def test_file_too_large(self, parser_with_fake_llm) -> None:
        from app.core.exceptions import FileTooLargeError

        # Settings default max is 10 MB; we send 11 MB of zeros
        huge = b"\x00" * (11 * 1024 * 1024)
        with pytest.raises(FileTooLargeError):
            parser_with_fake_llm.parse(huge, "huge.pdf")


class TestAPI:
    """Tests for HTTP endpoints using FastAPI's TestClient."""

    @pytest.fixture
    def client(self, parser_with_fake_llm):
        app = create_app()
        # Override the parser dependency to use our mocked one
        app.dependency_overrides[get_parser] = lambda: parser_with_fake_llm
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_root(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["service"] == "Resume Parser API"

    def test_parse_endpoint_with_docx(self, client: TestClient, sample_docx_bytes: bytes) -> None:
        response = client.post(
            "/api/v1/parse",
            files={"file": ("resume.docx", io.BytesIO(sample_docx_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["personal"]["email"] == "tahir.ahmed@example.com"
        assert body["personal"]["full_name"] == "Tahir Ahmed"

    def test_parse_rejects_unsupported_type(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/parse",
            files={"file": ("resume.txt", io.BytesIO(b"some text"), "text/plain")},
        )
        assert response.status_code == 400

    def test_parse_rejects_empty_file(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/parse",
            files={"file": ("resume.pdf", io.BytesIO(b""), "application/pdf")},
        )
        assert response.status_code == 400

    def test_openapi_docs_available(self, client: TestClient) -> None:
        response = client.get("/docs")
        assert response.status_code == 200
        response = client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert spec["info"]["title"] == "Resume Parser API"
