"""
Data models for Module 2 — the Job-Résumé Matcher.

The matcher consumes a ParsedResume (Module 1's output) plus a job description
and returns a structured match analysis. Models here mirror that contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field

from app.models.resume import ParsedResume


# ---------- Inputs ----------


class MatchRequest(BaseModel):
    """Caller sends a parsed résumé plus a job description (raw text)."""

    resume: ParsedResume = Field(..., description="The parsed résumé from /api/v1/parse")
    job_description: str = Field(..., min_length=50, description="Full job description text")
    job_title: Optional[str] = Field(None, description="Optional job title for context")
    company: Optional[str] = Field(None, description="Optional company name for context")


# ---------- LLM-extracted requirements ----------


RequirementType = Literal["skill", "experience", "education", "certification", "other"]
RequirementImportance = Literal["required", "preferred", "nice_to_have"]
RequirementMatchStatus = Literal["match", "partial", "missing"]


class Requirement(BaseModel):
    """A single hard requirement extracted from the job description."""

    text: str = Field(..., description="The requirement, as paraphrased from the JD")
    type: RequirementType
    importance: RequirementImportance


class MatchedRequirement(Requirement):
    """A requirement augmented with the matcher's verdict against the résumé."""

    status: RequirementMatchStatus
    evidence: Optional[str] = Field(
        None, description="Quote or paraphrase from the résumé that supports the verdict"
    )


# ---------- Top-level response ----------


class MatchResult(BaseModel):
    """The full match analysis returned to the caller."""

    request_id: str
    matched_at: datetime

    # ----- The headline number -----
    overall_score: int = Field(..., ge=0, le=100, description="0–100 combined match score")
    verdict: Literal["strong", "moderate", "weak"] = Field(
        ..., description="Headline verdict, derived from overall_score"
    )

    # ----- The two passes that fed the score -----
    semantic_similarity: float = Field(
        ..., ge=0.0, le=1.0,
        description="Cosine similarity between résumé and JD embeddings (0–1)",
    )
    requirement_coverage: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of weighted hard requirements that the résumé satisfies",
    )

    # ----- Detail -----
    matched_requirements: list[MatchedRequirement] = Field(
        ..., description="Every requirement with its match status"
    )
    matched_skills: list[str] = Field(
        ..., description="Skills from the résumé that align with the JD"
    )
    missing_skills: list[str] = Field(
        ..., description="Skills the JD wants that don't appear on the résumé"
    )

    # ----- Narrative -----
    summary: str = Field(..., description="2–3 sentence human-readable summary")

    # ----- Metadata -----
    job_title: Optional[str] = None
    company: Optional[str] = None
