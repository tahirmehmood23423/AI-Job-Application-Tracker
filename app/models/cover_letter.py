"""
Module 4 — Cover Letter Generator
Pydantic schemas for request/response contracts.
Mirrors the pattern from app/models/match.py and app/models/resume.py.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TonePreference(str, Enum):
    professional = "professional"
    conversational = "conversational"
    confident = "confident"
    enthusiastic = "enthusiastic"


class TalkingPoints(BaseModel):
    """
    Intermediate output from Pass 1 (TalkingPointExtractor).
    The LLM extracts these from résumé + match result + JD.
    """
    strongest_experiences: list[str] = Field(
        description="2-3 résumé bullet points most relevant to this specific job"
    )
    matched_skills: list[str] = Field(
        description="Skills the résumé has that the JD explicitly requires"
    )
    standout_achievement: str = Field(
        description="Single most impressive, quantified achievement from the résumé"
    )
    why_this_company: str = Field(
        description="Inferred reason the candidate might want this role (from JD context)"
    )
    gap_to_address: Optional[str] = Field(
        default=None,
        description="A key missing requirement from the match result to briefly acknowledge or reframe"
    )


class CoverLetterRequest(BaseModel):
    """
    Input to POST /api/v1/cover-letter.
    All four inputs the user selected.
    """
    resume: dict = Field(
        description="Parsed résumé JSON from Module 1 /api/v1/parse"
    )
    match_result: Optional[dict] = Field(
        default=None,
        description="Match result JSON from Module 2 /api/v1/match (optional but recommended)"
    )
    job_description: str = Field(
        min_length=50,
        description="Raw job description text (same as used in Module 2)"
    )
    tone: TonePreference = Field(
        default=TonePreference.professional,
        description="Tone preference for the generated letter"
    )
    job_title: Optional[str] = Field(
        default=None,
        description="Job title, used in salutation and opening"
    )
    company_name: Optional[str] = Field(
        default=None,
        description="Company name, used in salutation and body"
    )


class CoverLetterResult(BaseModel):
    """
    Full output from POST /api/v1/cover-letter.
    """
    cover_letter: str = Field(
        description="The complete generated cover letter, ready to copy-paste"
    )
    talking_points: TalkingPoints = Field(
        description="The extracted talking points used to generate the letter (Pass 1 output)"
    )
    word_count: int = Field(
        description="Word count of the generated cover letter"
    )
    tone_applied: TonePreference = Field(
        description="The tone that was applied"
    )
    match_score_used: Optional[float] = Field(
        default=None,
        description="The match score from Module 2 if a match result was provided"
    )
