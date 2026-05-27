"""
Module 6 — Dashboard
CRUD service layer — all database operations live here.
The FastAPI routes call these functions; they never touch SQLAlchemy directly.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import Application, Resume, StatusEvent, User
from .schemas import (
    ApplicationCreate, ApplicationUpdate,
    DashboardStats, StatusCount, UserCreate,
)


# ── Users ─────────────────────────────────────────────────────────────────────

def get_or_create_user(db: Session, data: UserCreate) -> User:
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        user = User(email=data.email, name=data.name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ── Resumes ───────────────────────────────────────────────────────────────────

def list_resumes(db: Session, user_id: str) -> List[Resume]:
    return (
        db.query(Resume)
        .filter(Resume.user_id == user_id)
        .order_by(Resume.uploaded_at.desc())
        .all()
    )


def save_resume(
    db: Session,
    user_id: str,
    filename: str,
    parsed_data: dict,
    skills: list,
    experience_years: float,
) -> Resume:
    resume = Resume(
        user_id=user_id,
        filename=filename,
        parsed_data=parsed_data,
        skills=skills,
        experience_years=experience_years,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


def delete_resume(db: Session, user_id: str, resume_id: str) -> bool:
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == user_id)
        .first()
    )
    if not resume:
        return False
    db.delete(resume)
    db.commit()
    return True


# ── Applications ──────────────────────────────────────────────────────────────

def create_application(
    db: Session, user_id: str, data: ApplicationCreate
) -> Application:
    app = Application(user_id=user_id, **data.model_dump())
    db.add(app)
    db.flush()  # get ID before commit

    # Log the initial status event
    event = StatusEvent(
        application_id=app.id,
        from_status=None,
        to_status="saved",
        note="Application saved",
    )
    db.add(event)
    db.commit()
    db.refresh(app)
    return app


def list_applications(
    db: Session,
    user_id: str,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Application]:
    q = db.query(Application).filter(Application.user_id == user_id)

    if status:
        q = q.filter(Application.status == status)

    if search:
        term = f"%{search.lower()}%"
        q = q.filter(
            Application.job_title.ilike(term) | Application.company.ilike(term)
        )

    return q.order_by(Application.updated_at.desc()).offset(offset).limit(limit).all()


def get_application(db: Session, user_id: str, app_id: str) -> Optional[Application]:
    return (
        db.query(Application)
        .filter(Application.id == app_id, Application.user_id == user_id)
        .first()
    )


def update_application(
    db: Session, user_id: str, app_id: str, data: ApplicationUpdate
) -> Optional[Application]:
    app = get_application(db, user_id, app_id)
    if not app:
        return None

    old_status = app.status
    update_data = data.model_dump(exclude_none=True)

    for field, value in update_data.items():
        setattr(app, field, value)

    # If status changed, log it
    new_status = update_data.get("status")
    if new_status and new_status != old_status:
        event = StatusEvent(
            application_id=app.id,
            from_status=old_status,
            to_status=new_status,
        )
        db.add(event)

        # Auto-set applied_at when moving to "applied"
        if new_status == "applied" and not app.applied_at:
            app.applied_at = datetime.utcnow()

    db.commit()
    db.refresh(app)
    return app


def delete_application(db: Session, user_id: str, app_id: str) -> bool:
    app = get_application(db, user_id, app_id)
    if not app:
        return False
    db.delete(app)
    db.commit()
    return True


# ── Dashboard Stats ───────────────────────────────────────────────────────────

def get_dashboard_stats(db: Session, user_id: str) -> DashboardStats:
    apps = db.query(Application).filter(Application.user_id == user_id)
    total = apps.count()

    # Averages
    avg_match = (
        apps.filter(Application.match_score.isnot(None))
        .with_entities(func.avg(Application.match_score))
        .scalar()
    )
    avg_ats = (
        apps.filter(Application.ats_score.isnot(None))
        .with_entities(func.avg(Application.ats_score))
        .scalar()
    )

    # Status breakdown
    status_rows = (
        apps.with_entities(Application.status, func.count(Application.id))
        .group_by(Application.status)
        .all()
    )
    status_breakdown = [StatusCount(status=s, count=c) for s, c in status_rows]

    # Top companies (by number of applications)
    company_rows = (
        apps.with_entities(Application.company, func.count(Application.id))
        .group_by(Application.company)
        .order_by(func.count(Application.id).desc())
        .limit(5)
        .all()
    )
    top_companies = [c for c, _ in company_rows]

    # This week
    week_ago = datetime.utcnow() - timedelta(days=7)
    this_week = apps.filter(Application.created_at >= week_ago).count()

    return DashboardStats(
        total_applications=total,
        avg_match_score=round(avg_match, 1) if avg_match else None,
        avg_ats_score=round(avg_ats, 1) if avg_ats else None,
        status_breakdown=status_breakdown,
        top_companies=top_companies,
        applications_this_week=this_week,
    )
