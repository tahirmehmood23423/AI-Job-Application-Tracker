"""Tests for Segmenter."""
from __future__ import annotations

from app.services.segmenter import Segmenter


class TestSegmenter:
    def setup_method(self) -> None:
        self.segmenter = Segmenter()

    def test_segments_standard_resume(self, sample_resume_text: str) -> None:
        result = self.segmenter.segment(sample_resume_text)
        assert result.has("summary")
        assert result.has("experience")
        assert result.has("education")
        assert result.has("skills")
        assert result.has("projects")
        assert result.has("certifications")

    def test_preamble_contains_contact_info(self, sample_resume_text: str) -> None:
        result = self.segmenter.segment(sample_resume_text)
        assert "Tahir Ahmed" in result.preamble
        assert "tahir.ahmed@example.com" in result.preamble

    def test_experience_section_contains_jobs(self, sample_resume_text: str) -> None:
        result = self.segmenter.segment(sample_resume_text)
        assert "Acme Corp" in result.sections["experience"]
        assert "Beta Labs" in result.sections["experience"]

    def test_handles_resume_with_no_headers(self) -> None:
        text = "Just some random text without any section headers"
        result = self.segmenter.segment(text)
        assert result.sections == {}
        assert result.preamble == text

    def test_header_variants_match(self) -> None:
        text = "PROFESSIONAL EXPERIENCE\nSome job"
        result = self.segmenter.segment(text)
        assert result.has("experience")

    def test_case_insensitive_matching(self) -> None:
        text = "skills\nPython, Java"
        result = self.segmenter.segment(text)
        assert result.has("skills")
