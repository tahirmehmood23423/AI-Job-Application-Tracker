"""
Module 6 — Dashboard
Database models using SQLAlchemy + SQLite (dev) / PostgreSQL (prod).
"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON,
    ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import uuid

Base = declarative_base()


def generate_id() -> str:
    return str(uuid.uuid4())


# ── Tables ────────────────────────────────────────────────────────────────────

class User(Base):
    """Represents an application user."""
    __tablename__ = "users"

    id         = Column(String, primary_key=True, default=generate_id)
    email      = Column(String, unique=True, nullable=False, index=True)
    name       = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resumes      = relationship("Resume",      back_populates="user", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")


class Resume(Base):
    """A parsed resume uploaded by a user (Module 1 output)."""
    __tablename__ = "resumes"

    id               = Column(String,  primary_key=True, default=generate_id)
    user_id          = Column(String,  ForeignKey("users.id"), nullable=False, index=True)
    filename         = Column(String,  nullable=False)
    parsed_data      = Column(JSON,    nullable=False)   # full Module 1 output
    skills           = Column(JSON,    default=list)     # extracted skills list
    experience_years = Column(Float,   default=0.0)
    uploaded_at      = Column(DateTime, default=datetime.utcnow)

    user         = relationship("User",        back_populates="resumes")
    applications = relationship("Application", back_populates="resume")


class Application(Base):
    """
    One job application.
    Created when user clicks Save on the job-match page.
    Links a resume to a job and stores all downstream outputs.

    Status flow:
        saved -> applied -> screening -> interview -> offer -> rejected
                                                           -> withdrawn
    """
    __tablename__ = "applications"

    id              = Column(String, primary_key=True, default=generate_id)
    user_id         = Column(String, ForeignKey("users.id"),   nullable=False, index=True)
    resume_id       = Column(String, ForeignKey("resumes.id"), nullable=False)

    # Job metadata
    job_title       = Column(String, nullable=False)
    company         = Column(String, nullable=False)
    job_url         = Column(String, nullable=True)
    job_description = Column(Text,   nullable=False)
    location        = Column(String, nullable=True)
    salary_range    = Column(String, nullable=True)

    # Module 2 — Match score
    match_score   = Column(Float, nullable=True)   # 0-100
    match_details = Column(JSON,  nullable=True)   # full Module 2 response

    # Module 3 — Tailored resume
    tailored_resume = Column(JSON,  nullable=True)
    ats_score       = Column(Float, nullable=True)

    # Module 4 — Cover letter
    cover_letter = Column(Text, nullable=True)

    # Status & notes
    status     = Column(String, default="saved")
    notes      = Column(Text,   nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user   = relationship("User",        back_populates="applications")
    resume = relationship("Resume",      back_populates="applications")
    events = relationship("StatusEvent", back_populates="application", cascade="all, delete-orphan")


class StatusEvent(Base):
    """
    Audit log of every status change on an application.
    Powers the timeline view in the dashboard.
    """
    __tablename__ = "status_events"

    id             = Column(String,  primary_key=True, default=generate_id)
    application_id = Column(String,  ForeignKey("applications.id"), nullable=False, index=True)
    from_status    = Column(String,  nullable=True)
    to_status      = Column(String,  nullable=False)
    note           = Column(Text,    nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    application = relationship("Application", back_populates="events")


# ── DB helpers ────────────────────────────────────────────────────────────────

def create_db(db_url: str = "sqlite:////tmp/dashboard.db"):
    """Create engine + all tables. Call once at startup."""
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {}
    )
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()
