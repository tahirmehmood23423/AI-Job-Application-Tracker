"""Tests for TextExtractor."""
from __future__ import annotations

import pytest

from app.core.exceptions import (
    EmptyFileError,
    TextExtractionError,
    UnsupportedFileTypeError,
)
from app.services.text_extractor import TextExtractor


class TestTextExtractor:
    def setup_method(self) -> None:
        self.extractor = TextExtractor()

    def test_extracts_text_from_docx(self, sample_docx_bytes: bytes) -> None:
        text = self.extractor.extract(sample_docx_bytes, "resume.docx")
        assert "Tahir Ahmed" in text
        assert "tahir.ahmed@example.com" in text
        assert "NUST Islamabad" in text

    def test_rejects_unsupported_extension(self) -> None:
        with pytest.raises(UnsupportedFileTypeError):
            self.extractor.extract(b"random bytes", "resume.txt")

    def test_rejects_empty_file(self) -> None:
        # An empty DOCX produces no text
        import io
        from docx import Document

        doc = Document()
        buf = io.BytesIO()
        doc.save(buf)
        with pytest.raises(EmptyFileError):
            self.extractor.extract(buf.getvalue(), "empty.docx")

    def test_invalid_docx_raises_extraction_error(self) -> None:
        with pytest.raises(TextExtractionError):
            self.extractor.extract(b"not a real docx file", "resume.docx")

    def test_cleaning_removes_page_numbers(self) -> None:
        # We test the private method directly because asserting it via the
        # public interface would need a multipage PDF fixture.
        dirty = "Some content\nPage 1 of 3\nMore content\n"
        cleaned = self.extractor._clean(dirty)
        assert "Page 1 of 3" not in cleaned
        assert "Some content" in cleaned
        assert "More content" in cleaned
