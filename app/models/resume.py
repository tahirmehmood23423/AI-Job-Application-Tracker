"""
Pydantic data models for the parsed resume.

These models serve THREE purposes:

1. They define the public API response schema (FastAPI auto-generates OpenAPI
   docs from them).
2. They validate the LLM's JSON output, catching hallucinations like
   malformed dates or missing required fields.
3. They are reused downstream by the matcher and tailoring modules, so the
   shape is stable across the whole product.

Keep the schema CONSERVATIVE: every field is Optional unless we are sure it
must exist on every resume. A senior engineer's resume is structurally
different from a new grad's, and the schema has to fit both.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator


# ---------- Sub-models ----------


class PersonalInfo(BaseModel):
    """Top-of-resume contact details. All optional — many resumes omit some."""

    full_name: Optional[str] = Field(None, description="Candidate's full name")
    email: Optional[str] = Field(None, description="Primary email address")
    phone: Optional[str] = Field(None, description="Phone in any format")
    location: Optional[str] = Field(None, description="City, country, or region")
    linkedin_url: Optional[str] = Field(None, description="LinkedIn profile URL")
    github_url: Optional[str] = Field(None, description="GitHub profile URL")
    portfolio_url: Optional[str] = Field(None, description="Personal website / portfolio")

    @field_validator("email")
    @classmethod
    def _strip_email(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().lower() if v else None


class Skills(BaseModel):
    """
    Skills bucketed by type so downstream matching can weight them differently.
    The LLM is instructed to put each skill in exactly one bucket.
    """

    technical: list[str] = Field(default_factory=list, description="Programming languages, frameworks, libraries")
    soft: list[str] = Field(default_factory=list, description="Communication, leadership, etc.")
    tools: list[str] = Field(default_factory=list, description="Software, platforms (Docker, AWS, Figma)")
    languages: list[str] = Field(default_factory=list, description="Spoken/written human languages")


class ExperienceEntry(BaseModel):
    """A single job. Dates are strings (not datetime) because resumes use
    wildly inconsistent date formats: 'Jan 2023', '01/2023', 'Present', etc.
    We keep them as the LLM extracted them, plus a normalized form."""

    company: str
    title: str
    location: Optional[str] = None
    start_date: Optional[str] = Field(None, description="Format: YYYY-MM if possible")
    end_date: Optional[str] = Field(None, description="Format: YYYY-MM or 'Present'")
    is_current: bool = False
    responsibilities: list[str] = Field(default_factory=list, description="Bullet points")
    technologies: list[str] = Field(default_factory=list, description="Tech used in this role")


class EducationEntry(BaseModel):
    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    achievements: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str
    description: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    role: Optional[str] = None


class CertificationEntry(BaseModel):
    name: str
    issuer: Optional[str] = None
    date_obtained: Optional[str] = None
    credential_url: Optional[str] = None


# ---------- Top-level response ----------


class ParsedResume(BaseModel):
    """The complete structured resume — this is what the API returns."""

    request_id: str = Field(..., description="UUID assigned when the request was received")
    parsed_at: datetime = Field(..., description="UTC timestamp")

    personal: PersonalInfo
    summary: Optional[str] = Field(None, description="Career objective / summary section")
    skills: Skills = Field(default_factory=Skills)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)

    # Diagnostic metadata — useful for debugging and for downstream modules
    raw_text_length: int = Field(..., description="Length of extracted text in characters")
    extraction_warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues encountered during parsing (e.g. low text yield)",
    )


# ---------- LLM-only model (no metadata, used as the LLM's JSON schema) ----------


class LLMExtractionResult(BaseModel):
    """
    What we ask the LLM to produce. This is ParsedResume MINUS the metadata
    (request_id, parsed_at, raw_text_length) that the server fills in itself.
    """

    personal: PersonalInfo
    summary: Optional[str] = None
    skills: Skills = Field(default_factory=Skills)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
