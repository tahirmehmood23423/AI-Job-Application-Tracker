"""Tests for RegexExtractor."""
from __future__ import annotations

from app.services.regex_extractor import RegexExtractor


class TestRegexExtractor:
    def setup_method(self) -> None:
        self.extractor = RegexExtractor()

    def test_extracts_email(self) -> None:
        result = self.extractor.extract("Contact: tahir.ahmed@example.com for details.")
        assert result.email == "tahir.ahmed@example.com"

    def test_normalizes_email_to_lowercase(self) -> None:
        result = self.extractor.extract("Email: Tahir.Ahmed@Example.COM")
        assert result.email == "tahir.ahmed@example.com"

    def test_extracts_international_phone(self) -> None:
        result = self.extractor.extract("Call me at +92-300-1234567 anytime.")
        assert result.phone is not None
        # The exact format may vary, but it should contain the right digits
        digits = "".join(c for c in result.phone if c.isdigit())
        assert "923001234567" in digits

    def test_extracts_us_phone(self) -> None:
        result = self.extractor.extract("Phone: (555) 123-4567")
        assert result.phone is not None
        digits = "".join(c for c in result.phone if c.isdigit())
        assert "5551234567" in digits

    def test_extracts_linkedin(self) -> None:
        result = self.extractor.extract("LinkedIn: linkedin.com/in/tahirahmed")
        assert result.linkedin_url == "https://linkedin.com/in/tahirahmed"

    def test_extracts_github(self) -> None:
        result = self.extractor.extract("GitHub: https://github.com/tahirahmed")
        assert result.github_url is not None
        assert "github.com/tahirahmed" in result.github_url

    def test_portfolio_excludes_known_profile_domains(self) -> None:
        text = "linkedin.com/in/me github.com/me https://myportfolio.dev"
        result = self.extractor.extract(text)
        assert result.portfolio_url is not None
        assert "myportfolio.dev" in result.portfolio_url

    def test_no_phone_when_too_few_digits(self) -> None:
        result = self.extractor.extract("Apt 42, building 7")
        # Should not extract "42, building 7" as a phone
        if result.phone is not None:
            digits = "".join(c for c in result.phone if c.isdigit())
            assert len(digits) >= 7

    def test_empty_text_returns_nothing(self) -> None:
        result = self.extractor.extract("")
        assert result.email is None
        assert result.phone is None
        assert result.linkedin_url is None
        assert result.github_url is None
        assert result.portfolio_url is None

    def test_full_sample_text(self, sample_resume_text: str) -> None:
        result = self.extractor.extract(sample_resume_text)
        assert result.email == "tahir.ahmed@example.com"
        assert result.phone is not None
        assert "linkedin.com/in/tahirahmed" in (result.linkedin_url or "")
        assert "github.com/tahirahmed" in (result.github_url or "")
