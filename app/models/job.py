"""
Module 5 — Job Discovery
Pydantic schemas for job listings, search requests, and results.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class JobSource(str, Enum):
    linkedin = "linkedin"
    indeed = "indeed"
    remotive = "remotive"


class JobType(str, Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    remote = "remote"
    internship = "internship"
    unknown = "unknown"


class JobListing(BaseModel):
    """A single job listing from any source."""
    id: str = Field(description="Unique ID — source:hash of URL")
    title: str
    company: str
    location: str
    salary: Optional[str] = None
    job_type: JobType = JobType.unknown
    description_snippet: str = Field(description="First 300 chars of description")
    url: str
    posted_at: Optional[str] = None
    source: JobSource
    match_score: Optional[float] = Field(
        default=None,
        description="0-100 match score against user résumé (populated by job_discovery_service)"
    )
    match_verdict: Optional[str] = Field(
        default=None,
        description="strong / moderate / weak"
    )


class JobSearchRequest(BaseModel):
    """Input to POST /api/v1/jobs/discover"""
    resume: dict = Field(description="Parsed résumé JSON from Module 1")
    keywords: Optional[list[str]] = Field(
        default=None,
        description="Override keywords. If None, auto-extracted from résumé skills."
    )
    location: Optional[str] = Field(
        default=None,
        description="Location filter e.g. 'Pakistan', 'Remote', 'London'"
    )
    sources: list[JobSource] = Field(
        default=[JobSource.linkedin, JobSource.remotive],
        description="Which sources to query"
    )
    max_results_per_source: int = Field(default=10, ge=1, le=25)
    auto_match: bool = Field(
        default=True,
        description="Auto-score each job against the résumé using semantic similarity"
    )


class JobSearchResult(BaseModel):
    """Full response from POST /api/v1/jobs/discover"""
    jobs: list[JobListing]
    total_found: int
    keywords_used: list[str]
    location_used: Optional[str]
    sources_queried: list[JobSource]
    auto_matched: bool


class SavedJob(BaseModel):
    """A job the user saved — stored client-side in localStorage."""
    job: JobListing
    saved_at: str
    notes: Optional[str] = None
    status: str = Field(
        default="saved",
        description="saved / applied / interviewing / rejected / offer"
    )
