"""Tests for the Module 2 matcher pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.match import MatchedRequirement, Requirement
from app.models.resume import ParsedResume
from app.services.embedding_service import cosine_similarity, resume_to_text
from app.services.matcher_service import MatcherService


@pytest.fixture
def parsed_resume(fake_llm_result):
    """A ParsedResume built from the LLMExtractionResult fixture."""
    return ParsedResume(
        request_id="test-uuid",
        parsed_at=datetime.now(timezone.utc),
        personal=fake_llm_result.personal,
        summary=fake_llm_result.summary,
        skills=fake_llm_result.skills,
        experience=fake_llm_result.experience,
        education=fake_llm_result.education,
        projects=fake_llm_result.projects,
        certifications=fake_llm_result.certifications,
        raw_text_length=2000,
        extraction_warnings=[],
    )


# ---------- Pure math ----------


class TestCosineSimilarity:
    def test_identical_vectors_return_one(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors_return_zero(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors_return_negative_one(self):
        a = [1.0, 2.0]
        b = [-1.0, -2.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-6)

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


# ---------- resume_to_text helper ----------


class TestResumeToText:
    def test_flattens_resume_with_skills_and_experience(self, parsed_resume, fake_llm_result):
        # fake_llm_result is a fixture from conftest.py; it has skills and
        # one experience entry.
        text = resume_to_text(fake_llm_result)
        assert "Technical skills" in text
        assert "Python" in text
        assert "Acme Corp" in text
        assert "Senior ML Engineer" in text

    def test_handles_empty_resume(self, parsed_resume, fake_llm_result):
        # Build a barely-populated résumé
        fake_llm_result.summary = None
        fake_llm_result.skills.technical = []
        fake_llm_result.skills.tools = []
        fake_llm_result.skills.languages = []
        fake_llm_result.skills.soft = []
        fake_llm_result.experience = []
        fake_llm_result.projects = []
        fake_llm_result.education = []
        fake_llm_result.certifications = []
        text = resume_to_text(fake_llm_result)
        # Should not crash, may be empty string
        assert isinstance(text, str)


# ---------- MatcherService scoring math ----------


class TestCoverageScoring:
    def _matched(self, importance: str, status: str) -> MatchedRequirement:
        return MatchedRequirement(
            text="x",
            type="skill",
            importance=importance,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            evidence=None,
        )

    def test_no_requirements_yields_zero(self):
        assert MatcherService._compute_coverage([]) == 0.0

    def test_all_required_matched_yields_one(self):
        ms = [self._matched("required", "match") for _ in range(3)]
        assert MatcherService._compute_coverage(ms) == pytest.approx(1.0)

    def test_all_required_missing_yields_zero(self):
        ms = [self._matched("required", "missing") for _ in range(3)]
        assert MatcherService._compute_coverage(ms) == pytest.approx(0.0)

    def test_partial_yields_half_credit(self):
        ms = [self._matched("required", "partial")]
        assert MatcherService._compute_coverage(ms) == pytest.approx(0.5)

    def test_importance_weights_factor_correctly(self):
        # one required+match, one nice_to_have+missing
        # required weight=1.0, credit=1.0
        # nice_to_have weight=0.2, credit=0.0
        # coverage = (1.0*1.0 + 0.2*0.0) / (1.0 + 0.2) = 0.833...
        ms = [
            self._matched("required", "match"),
            self._matched("nice_to_have", "missing"),
        ]
        assert MatcherService._compute_coverage(ms) == pytest.approx(1.0 / 1.2, abs=1e-3)


# ---------- Full pipeline (mocked) ----------


class TestMatcherServicePipeline:
    def test_end_to_end_with_mocked_dependencies(self, parsed_resume, fake_llm_result, test_settings):
        """The full match() flow with embedder and req_extractor mocked.

        We're testing the orchestration logic, not the LLM calls.
        """
        from app.models.match import MatchRequest

        # Mock embedding service: identical vectors → similarity 1.0
        embedder = MagicMock()
        embedder.embed.return_value = [1.0, 0.0, 0.0]

        # Mock requirement extractor: returns two requirements, both matched
        req_extractor = MagicMock()
        req_extractor.extract_requirements.return_value = [
            Requirement(text="Python", type="skill", importance="required"),
            Requirement(text="FastAPI", type="skill", importance="preferred"),
        ]
        req_extractor.match_requirements.return_value = [
            MatchedRequirement(
                text="Python", type="skill", importance="required",
                status="match", evidence="Python in skills",
            ),
            MatchedRequirement(
                text="FastAPI", type="skill", importance="preferred",
                status="match", evidence="FastAPI in tools",
            ),
        ]

        service = MatcherService(
            settings=test_settings,
            embedding_service=embedder,
            requirement_extractor=req_extractor,
        )

        request = MatchRequest(
            resume=parsed_resume,
            job_description="We need a senior engineer with Python and FastAPI experience. "
            "Must have built REST APIs. Comfortable with Docker.",
            job_title="Senior Engineer",
            company="Acme",
        )

        result = service.match(request)

        # Identical embeddings + full requirement match → score should be 100
        assert result.overall_score == 100
        assert result.verdict == "strong"
        assert result.semantic_similarity == pytest.approx(1.0)
        assert result.requirement_coverage == pytest.approx(1.0)
        assert "Python" in result.matched_skills
        assert "FastAPI" in result.matched_skills
        assert result.missing_skills == []
        assert result.job_title == "Senior Engineer"
        assert result.company == "Acme"
        assert "Strong match" in result.summary

    def test_weak_match_when_everything_missing(self, parsed_resume, fake_llm_result, test_settings):
        from app.models.match import MatchRequest

        embedder = MagicMock()
        embedder.embed.return_value = [1.0, 0.0]

        req_extractor = MagicMock()
        req_extractor.extract_requirements.return_value = [
            Requirement(text="Rust", type="skill", importance="required"),
            Requirement(text="Kubernetes", type="skill", importance="required"),
        ]
        req_extractor.match_requirements.return_value = [
            MatchedRequirement(
                text="Rust", type="skill", importance="required",
                status="missing", evidence=None,
            ),
            MatchedRequirement(
                text="Kubernetes", type="skill", importance="required",
                status="missing", evidence=None,
            ),
        ]

        service = MatcherService(
            settings=test_settings,
            embedding_service=embedder,
            requirement_extractor=req_extractor,
        )

        request = MatchRequest(
            resume=parsed_resume,
            job_description="We need a Rust engineer with deep Kubernetes operational experience. "
            "Must have managed clusters in production at scale.",
        )

        result = service.match(request)
        # All requirements missing → coverage = 0, similarity = 1 (orthogonal mocked)
        # score = 100 * (0.4 * 1.0 + 0.6 * 0.0) = 40
        assert result.requirement_coverage == 0.0
        assert result.verdict == "weak"
        assert "Rust" in result.missing_skills
        assert "Kubernetes" in result.missing_skills
        assert result.matched_skills == []
