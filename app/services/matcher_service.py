"""
Matcher service — orchestrates Module 2.

Combines two signals into one match score:
  1. Semantic similarity (embedding cosine, 0–1) — fast, captures overall fit
  2. Requirement coverage (weighted match rate, 0–1) — captures specific gaps

Scoring formula (designed, not arbitrary):
  - 40% semantic similarity
  - 60% requirement coverage
Coverage is weighted by importance: required=1.0, preferred=0.5, nice_to_have=0.2.
A "match" earns full weight, "partial" half, "missing" zero.

Verdict thresholds:
  - 75+ → strong
  - 50–74 → moderate
  - <50 → weak

These are tuned for résumés vs. job descriptions specifically. The thresholds
are intentionally generous on the low end — semantic similarity rarely exceeds
~0.7 even for great matches, so the formula compresses upward.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.core.exceptions import LLMConfigurationError
from app.models.match import (
    MatchedRequirement,
    MatchRequest,
    MatchResult,
    Requirement,
)
from app.models.resume import ParsedResume, Skills
from app.services.embedding_service import (
    EmbeddingService,
    TASK_DOCUMENT,
    TASK_QUERY,
    cosine_similarity,
    resume_to_text,
)
from app.services.requirement_extractor import RequirementExtractor
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------- Scoring constants ----------

_W_SEMANTIC = 0.40
_W_REQUIREMENT = 0.60

_IMPORTANCE_WEIGHTS = {
    "required": 1.0,
    "preferred": 0.5,
    "nice_to_have": 0.2,
}

_STATUS_CREDIT = {
    "match": 1.0,
    "partial": 0.5,
    "missing": 0.0,
}


# ---------- Service ----------


class MatcherService:
    """Top-level orchestrator for Module 2."""

    def __init__(
        self,
        settings: Settings | None = None,
        embedding_service: EmbeddingService | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ):
        self.settings = settings or get_settings()
        self.embedder = embedding_service or EmbeddingService(self.settings)
        self.req_extractor = requirement_extractor or RequirementExtractor(
            settings=self.settings
        )

    def match(self, request: MatchRequest) -> MatchResult:
        """Run the full matching pipeline."""
        request_id = str(uuid.uuid4())
        logger.info(
            "Running match",
            extra={"request_id": request_id, "jd_length": len(request.job_description)},
        )

        # --- Pass 1: semantic similarity ---
        resume_text = resume_to_text(request.resume)
        resume_vec = self.embedder.embed(resume_text, task=TASK_DOCUMENT)
        jd_vec = self.embedder.embed(request.job_description, task=TASK_QUERY)
        semantic = cosine_similarity(resume_vec, jd_vec)
        # Cosine for text embeddings rarely exceeds ~0.85 even for great
        # matches. Normalise it slightly so the headline score doesn't feel
        # crushed. We clamp into [0, 1] regardless.
        normalized_semantic = max(0.0, min(1.0, semantic))

        logger.info(
            "Semantic similarity computed",
            extra={"request_id": request_id, "cosine": round(semantic, 4)},
        )

        # --- Pass 2: requirement extraction + matching ---
        requirements = self.req_extractor.extract_requirements(request.job_description)
        logger.info(
            "Requirements extracted",
            extra={"request_id": request_id, "count": len(requirements)},
        )

        matched = self.req_extractor.match_requirements(
            requirements, request.resume
        )
        coverage = self._compute_coverage(matched)

        # --- Combine into headline score ---
        overall = int(round(
            100 * (_W_SEMANTIC * normalized_semantic + _W_REQUIREMENT * coverage)
        ))

        # --- Skill diffing (for UI surface) ---
        resume_skill_set = self._all_skills_lower(request.resume.skills)
        matched_skills, missing_skills = self._diff_skills(
            matched, resume_skill_set
        )

        # --- Verdict ---
        verdict: str
        if overall >= 75:
            verdict = "strong"
        elif overall >= 50:
            verdict = "moderate"
        else:
            verdict = "weak"

        summary = self._compose_summary(
            overall, verdict, normalized_semantic, coverage, matched
        )

        return MatchResult(
            request_id=request_id,
            matched_at=datetime.now(timezone.utc),
            overall_score=overall,
            verdict=verdict,  # type: ignore[arg-type]
            semantic_similarity=round(normalized_semantic, 4),
            requirement_coverage=round(coverage, 4),
            matched_requirements=matched,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            summary=summary,
            job_title=request.job_title,
            company=request.company,
        )

    # ---------- helpers ----------

    @staticmethod
    def _compute_coverage(matched: list[MatchedRequirement]) -> float:
        """Weighted average: importance × status credit."""
        if not matched:
            return 0.0
        numerator = 0.0
        denominator = 0.0
        for m in matched:
            weight = _IMPORTANCE_WEIGHTS.get(m.importance, 0.2)
            credit = _STATUS_CREDIT.get(m.status, 0.0)
            numerator += weight * credit
            denominator += weight
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _all_skills_lower(skills: Skills) -> set[str]:
        return {
            s.lower().strip()
            for bucket in (skills.technical, skills.tools, skills.soft, skills.languages)
            for s in bucket
        }

    def _diff_skills(
        self,
        matched: list[MatchedRequirement],
        resume_skills: set[str],
    ) -> tuple[list[str], list[str]]:
        """Pull skill-type requirements and split into matched/missing.

        Returns (matched_skills, missing_skills). Both are lists of strings
        suitable for direct UI display.
        """
        matched_out: list[str] = []
        missing_out: list[str] = []
        seen_missing: set[str] = set()

        for req in matched:
            if req.type != "skill":
                continue
            label = req.text.strip()
            if req.status == "match":
                matched_out.append(label)
            elif req.status == "missing":
                # Avoid surfacing duplicates if the JD mentions Python twice
                key = label.lower()
                if key not in seen_missing:
                    missing_out.append(label)
                    seen_missing.add(key)
        return matched_out, missing_out

    @staticmethod
    def _compose_summary(
        score: int,
        verdict: str,
        semantic: float,
        coverage: float,
        matched: list[MatchedRequirement],
    ) -> str:
        """Short human-readable summary, 2–3 sentences.

        Composed deterministically rather than via another LLM call. Saves
        time, cost, and one more thing that can go wrong.
        """
        n_total = len(matched)
        n_match = sum(1 for m in matched if m.status == "match")
        n_partial = sum(1 for m in matched if m.status == "partial")
        n_missing = sum(1 for m in matched if m.status == "missing")
        n_required_missing = sum(
            1 for m in matched if m.status == "missing" and m.importance == "required"
        )

        head = {
            "strong": "Strong match.",
            "moderate": "Moderate match.",
            "weak": "Weak match.",
        }[verdict]

        if n_total == 0:
            return (
                f"{head} Score {score}/100. The job description didn't yield "
                f"specific requirements to compare against; the score reflects "
                f"semantic similarity only."
            )

        body = (
            f" The résumé satisfies {n_match} of {n_total} extracted requirements, "
            f"partially covers {n_partial}, and is missing {n_missing}."
        )

        tail = ""
        if n_required_missing > 0:
            tail = f" {n_required_missing} of the missing requirements are marked 'required' in the job description."

        return head + body + tail
