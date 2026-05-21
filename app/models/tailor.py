"""
Data models for Module 3 — Tailored Resume Generator.

The tailorer takes a ParsedResume (Module 1 output) + a job description, and
returns a tailored version of the resume PLUS a structured diff showing exactly
what changed PLUS an ATS compatibility report.

Two strictness modes:
  - "strict": every change must be reviewed; user opts in change-by-change
  - "auto": the AI's output is the result; user sees the diff after the fact

Both modes use the same source-bound prompting — the LLM is never allowed to
invent new content. Only rewriting, reordering, and emphasising existing
information is permitted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.resume import (
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    PersonalInfo,
    ProjectEntry,
    Skills,
)


# ---------- Inputs ----------


TailorMode = Literal["strict", "auto"]


class TailorRequest(BaseModel):
    """What the client sends to /api/v1/tailor."""

    resume: ParsedResume = Field(..., description="Parsed résumé from /parse")
    job_description: str = Field(..., min_length=50, description="The job to tailor for")
    job_title: Optional[str] = Field(None, description="Optional job title for context")
    company: Optional[str] = Field(None, description="Optional company name for context")
    mode: TailorMode = Field(
        "strict",
        description=(
            "'strict' means user reviews each change. 'auto' applies all changes; "
            "diff is shown after."
        ),
    )


# ---------- Diff models ----------


ChangeType = Literal[
    "summary_rewritten",
    "skill_reordered",
    "skill_emphasised",
    "experience_bullet_rewritten",
    "experience_bullets_reordered",
    "project_description_rewritten",
    "projects_reordered",
]

ChangeImpact = Literal["high", "medium", "low"]


class Change(BaseModel):
    """A single atomic change between the original and tailored résumé.

    Each change is structured so the UI can render a clean side-by-side diff.
    The user (in strict mode) accepts or rejects each one individually.
    """

    id: str = Field(..., description="Stable identifier for this change")
    type: ChangeType
    impact: ChangeImpact = Field(
        ..., description="How significant this change is for the target job"
    )
    section: str = Field(..., description="Which section: summary / skills / experience-0 / etc.")
    rationale: str = Field(
        ..., description="One-sentence explanation of why this change improves the match"
    )
    before: Optional[str] = Field(None, description="Original text (None for reorderings)")
    after: Optional[str] = Field(None, description="New text (None for reorderings)")
    before_list: Optional[list[str]] = Field(
        None, description="Original ordering (for reorder changes)"
    )
    after_list: Optional[list[str]] = Field(
        None, description="New ordering (for reorder changes)"
    )


# ---------- ATS report ----------


ATSSeverity = Literal["error", "warning", "info"]


class ATSIssue(BaseModel):
    """A single ATS-compatibility issue found in the tailored résumé."""

    severity: ATSSeverity
    rule: str = Field(..., description="Machine-readable rule code")
    message: str = Field(..., description="Human-readable description")
    where: Optional[str] = Field(None, description="Section or field where the issue was found")


class ATSReport(BaseModel):
    """Summary of ATS-friendliness checks."""

    score: int = Field(..., ge=0, le=100, description="0–100, higher is better")
    issues: list[ATSIssue] = Field(default_factory=list)
    keyword_coverage: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of JD keywords that appear in the tailored résumé",
    )
    keyword_matches: list[str] = Field(default_factory=list)
    keyword_misses: list[str] = Field(default_factory=list)


# ---------- LLM-only intermediate model ----------


class RewrittenResume(BaseModel):
    """What the LLM returns. Mirrors ParsedResume but without metadata fields.

    The orchestrator merges this with the original to produce the final
    TailorResult.
    """

    personal: PersonalInfo
    summary: Optional[str] = None
    skills: Skills = Field(default_factory=Skills)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)


# ---------- Top-level response ----------


class TailorResult(BaseModel):
    """The full tailoring output returned by /api/v1/tailor."""

    request_id: str
    tailored_at: datetime
    mode: TailorMode

    original: ParsedResume = Field(..., description="Echo of the input résumé")
    tailored: ParsedResume = Field(
        ..., description="Rewritten résumé (same schema as input)"
    )

    changes: list[Change] = Field(..., description="Structured diff")
    ats_report: ATSReport

    job_title: Optional[str] = None
    company: Optional[str] = None

    # Summary metadata for the UI
    total_changes: int
    high_impact_changes: int
