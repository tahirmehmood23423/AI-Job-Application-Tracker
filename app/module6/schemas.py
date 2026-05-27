"""
Module 6 — Dashboard
Pydantic schemas for request/response validation.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr


# ── Resume ────────────────────────────────────────────────────────────────────

class ResumeOut(BaseModel):
    id: str
    filename: str
    skills: List[str]
    experience_years: float
    uploaded_at: datetime

    class Config:
        from_attributes = True


# ── Status Events ─────────────────────────────────────────────────────────────

class StatusEventOut(BaseModel):
    id: str
    from_status: Optional[str]
    to_status: str
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Application ───────────────────────────────────────────────────────────────

class ApplicationCreate(BaseModel):
    resume_id: str
    job_title: str
    company: str
    job_description: str
    job_url: Optional[str] = None
    location: Optional[str] = None
    salary_range: Optional[str] = None
    match_score: Optional[float] = None
    match_details: Optional[Dict[str, Any]] = None
    tailored_resume: Optional[Dict[str, Any]] = None
    ats_score: Optional[float] = None
    cover_letter: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    applied_at: Optional[datetime] = None
    cover_letter: Optional[str] = None
    tailored_resume: Optional[Dict[str, Any]] = None
    ats_score: Optional[float] = None


class ApplicationOut(BaseModel):
    id: str
    resume_id: str
    job_title: str
    company: str
    job_url: Optional[str]
    location: Optional[str]
    salary_range: Optional[str]
    match_score: Optional[float]
    ats_score: Optional[float]
    status: str
    notes: Optional[str]
    applied_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    events: List[StatusEventOut] = []

    class Config:
        from_attributes = True


# ── Dashboard Stats ───────────────────────────────────────────────────────────

class StatusCount(BaseModel):
    status: str
    count: int


class DashboardStats(BaseModel):
    total_applications: int
    avg_match_score: Optional[float]
    avg_ats_score: Optional[float]
    status_breakdown: List[StatusCount]
    top_companies: List[str]
    applications_this_week: int


# ── User ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    name: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True
