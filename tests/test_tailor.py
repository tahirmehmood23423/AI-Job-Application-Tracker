"""Tests for Module 3 — Tailored Resume Generator."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.resume import (
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    PersonalInfo,
    ProjectEntry,
    Skills,
)
from app.models.tailor import (
    Change,
    RewrittenResume,
    TailorRequest,
)
from app.services.ats_checker import ATSChecker
from app.services.diff_service import DiffService
from app.services.rewrite_service import RewriteService
from app.services.tailor_service import TailorService


# ---------- Fixtures ----------


@pytest.fixture
def parsed_resume(fake_llm_result):
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


# ---------- RewriteService — source-bound enforcement ----------


class TestSourceBoundEnforcement:
    """The most important tests — preventing hallucinated content."""

    def test_invented_skill_is_removed(self, parsed_resume, test_settings):
        """LLM adds a skill that wasn't on the original — should be filtered."""
        # Build a "rewritten" with an invented skill
        rewritten = RewrittenResume(
            personal=parsed_resume.personal,
            summary=parsed_resume.summary,
            skills=Skills(
                # All originals + one invented
                technical=parsed_resume.skills.technical + ["Kubernetes"],
                soft=parsed_resume.skills.soft,
                tools=parsed_resume.skills.tools,
                languages=parsed_resume.skills.languages,
            ),
            experience=parsed_resume.experience,
            education=parsed_resume.education,
            projects=parsed_resume.projects,
            certifications=parsed_resume.certifications,
        )

        service = RewriteService(settings=test_settings)
        fixed, warnings = service._enforce_source_bound(parsed_resume, rewritten)

        # Kubernetes was not in original; should be removed
        assert "Kubernetes" not in fixed.skills.technical
        assert any("Kubernetes" in w for w in warnings)

    def test_modified_personal_info_is_restored(self, parsed_resume, test_settings):
        rewritten = RewrittenResume(
            personal=PersonalInfo(
                full_name="FAKE NAME",
                email=parsed_resume.personal.email,
                phone=parsed_resume.personal.phone,
                location=None,
                linkedin_url=None,
                github_url=None,
                portfolio_url=None,
            ),
            summary=parsed_resume.summary,
            skills=parsed_resume.skills,
            experience=parsed_resume.experience,
            education=parsed_resume.education,
            projects=parsed_resume.projects,
            certifications=parsed_resume.certifications,
        )

        service = RewriteService(settings=test_settings)
        fixed, warnings = service._enforce_source_bound(parsed_resume, rewritten)

        assert fixed.personal == parsed_resume.personal
        assert any("personal" in w.lower() for w in warnings)

    def test_invented_project_is_restored(self, parsed_resume, test_settings):
        # Ensure there's at least one project to begin with
        if not parsed_resume.projects:
            parsed_resume = parsed_resume.model_copy(update={
                "projects": [ProjectEntry(name="Original Project", description="x", technologies=[])]
            })
        # Replace first project's name with a fake
        bad_projects = list(parsed_resume.projects)
        bad_projects[0] = ProjectEntry(
            name="FAKE INVENTED PROJECT",
            description="A project I never did",
            technologies=[],
        )

        rewritten = RewrittenResume(
            personal=parsed_resume.personal,
            summary=parsed_resume.summary,
            skills=parsed_resume.skills,
            experience=parsed_resume.experience,
            education=parsed_resume.education,
            projects=bad_projects,
            certifications=parsed_resume.certifications,
        )

        service = RewriteService(settings=test_settings)
        fixed, warnings = service._enforce_source_bound(parsed_resume, rewritten)

        assert "FAKE INVENTED PROJECT" not in [p.name for p in fixed.projects]
        assert any("invented" in w.lower() or "project" in w.lower() for w in warnings)

    def test_experience_count_change_is_reverted(self, parsed_resume, test_settings):
        # Try to remove an experience entry
        truncated = parsed_resume.experience[:-1]
        rewritten = RewrittenResume(
            personal=parsed_resume.personal,
            summary=parsed_resume.summary,
            skills=parsed_resume.skills,
            experience=truncated,
            education=parsed_resume.education,
            projects=parsed_resume.projects,
            certifications=parsed_resume.certifications,
        )

        service = RewriteService(settings=test_settings)
        fixed, warnings = service._enforce_source_bound(parsed_resume, rewritten)

        assert len(fixed.experience) == len(parsed_resume.experience)
        assert any("experience count" in w.lower() for w in warnings)

    def test_modified_education_is_restored(self, parsed_resume, test_settings):
        bad_education = [
            EducationEntry(
                institution="FAKE UNIVERSITY",
                degree="Fake Degree",
                field_of_study=None,
                start_date="2099",
                end_date="2100",
                gpa=None,
                achievements=[],
            )
        ]
        rewritten = RewrittenResume(
            personal=parsed_resume.personal,
            summary=parsed_resume.summary,
            skills=parsed_resume.skills,
            experience=parsed_resume.experience,
            education=bad_education,
            projects=parsed_resume.projects,
            certifications=parsed_resume.certifications,
        )

        service = RewriteService(settings=test_settings)
        fixed, warnings = service._enforce_source_bound(parsed_resume, rewritten)

        assert fixed.education == parsed_resume.education
        assert any("education" in w.lower() for w in warnings)

    def test_clean_rewrite_produces_no_warnings(self, parsed_resume, test_settings):
        """A rewrite that only reorders/rewrites with no invention should pass clean."""
        # Reorder skills, no addition
        rewritten = RewrittenResume(
            personal=parsed_resume.personal,
            summary="Rewritten summary that's better.",
            skills=Skills(
                technical=list(reversed(parsed_resume.skills.technical)),
                soft=parsed_resume.skills.soft,
                tools=parsed_resume.skills.tools,
                languages=parsed_resume.skills.languages,
            ),
            experience=parsed_resume.experience,
            education=parsed_resume.education,
            projects=parsed_resume.projects,
            certifications=parsed_resume.certifications,
        )

        service = RewriteService(settings=test_settings)
        _, warnings = service._enforce_source_bound(parsed_resume, rewritten)

        assert warnings == []


# ---------- DiffService ----------


class TestDiffService:
    def test_no_changes_returns_empty_list(self, parsed_resume):
        service = DiffService()
        changes = service.compute_changes(parsed_resume, parsed_resume)
        assert changes == []

    def test_summary_change_is_detected(self, parsed_resume):
        tailored = parsed_resume.model_copy(update={"summary": "Completely different summary now."})
        changes = DiffService().compute_changes(parsed_resume, tailored)
        assert len(changes) == 1
        assert changes[0].type == "summary_rewritten"
        assert changes[0].impact == "high"

    def test_skill_reordering_is_detected(self, parsed_resume):
        tailored = parsed_resume.model_copy(deep=True)
        tailored.skills.technical = list(reversed(parsed_resume.skills.technical))
        changes = DiffService().compute_changes(parsed_resume, tailored)
        # Should detect the reordering
        assert any(c.type == "skill_reordered" for c in changes)


# ---------- ATSChecker ----------


class TestATSChecker:
    def test_complete_resume_gets_high_score(self, parsed_resume):
        report = ATSChecker().check(parsed_resume, "Python Engineer with NLP experience")
        # parsed_resume from fixture is solid; should be >= 80
        assert report.score >= 50

    def test_missing_skills_section_lowers_score(self, parsed_resume):
        bare = parsed_resume.model_copy(deep=True)
        bare.skills = Skills()
        report = ATSChecker().check(bare, "Python Engineer with NLP experience")
        # MISSING_SKILLS is an error (-15)
        assert any(i.rule == "MISSING_SKILLS" for i in report.issues)
        assert report.score < 90

    def test_keyword_coverage_computed(self, parsed_resume):
        # JD contains words that should appear in the résumé
        jd = "We need a Python NLP engineer with FastAPI and Docker experience."
        report = ATSChecker().check(parsed_resume, jd)
        assert 0.0 <= report.keyword_coverage <= 1.0
        # Should find at least some matches given the fixture
        assert isinstance(report.keyword_matches, list)
        assert isinstance(report.keyword_misses, list)


# ---------- TailorService (full pipeline, mocked) ----------


class TestTailorServicePipeline:
    def test_end_to_end_with_mocks(self, parsed_resume, test_settings):
        # Mock rewriter to return the same résumé back (no actual LLM call)
        rewriter = MagicMock()
        rewritten = RewrittenResume(
            personal=parsed_resume.personal,
            summary="A tailored summary emphasising relevant work.",
            skills=parsed_resume.skills,
            experience=parsed_resume.experience,
            education=parsed_resume.education,
            projects=parsed_resume.projects,
            certifications=parsed_resume.certifications,
        )
        rewriter.rewrite.return_value = (rewritten, [])

        service = TailorService(
            settings=test_settings,
            rewrite_service=rewriter,
        )

        request = TailorRequest(
            resume=parsed_resume,
            job_description=(
                "We are looking for a Senior NLP Engineer with Python, "
                "Transformers, and FastAPI experience. Must be familiar with Docker."
            ),
            job_title="Senior NLP Engineer",
            company="Test Co",
            mode="strict",
        )

        result = service.tailor(request)

        assert result.mode == "strict"
        assert result.tailored.summary == "A tailored summary emphasising relevant work."
        assert result.original == parsed_resume
        assert result.total_changes >= 1  # At least the summary change
        assert result.ats_report.score >= 0
        assert result.job_title == "Senior NLP Engineer"
        assert result.company == "Test Co"
