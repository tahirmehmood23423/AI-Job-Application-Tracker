"""
Module 6 — Dashboard
FastAPI application — mounts on the existing backend at /dashboard
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import crud
from . import schemas
from .models import create_db, get_session

# ── DB dependency ─────────────────────────────────────────────────────────────

engine = create_db()  # SQLite in dev; swap to Postgres URL in prod


def get_db():
    db = get_session(engine)
    try:
        yield db
    finally:
        db.close()


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Users ─────────────────────────────────────────────────────────────────────

@router.post("/users", response_model=schemas.UserOut, status_code=201)
def create_user(data: schemas.UserCreate, db: Session = Depends(get_db)):
    """Get or create a user by email."""
    return crud.get_or_create_user(db, data)


# ── Resumes ───────────────────────────────────────────────────────────────────

@router.get("/users/{user_id}/resumes", response_model=List[schemas.ResumeOut])
def list_resumes(user_id: str, db: Session = Depends(get_db)):
    """List all resumes for a user."""
    return crud.list_resumes(db, user_id)


@router.delete("/users/{user_id}/resumes/{resume_id}", status_code=204)
def delete_resume(user_id: str, resume_id: str, db: Session = Depends(get_db)):
    """Delete a resume (and cascade-delete its applications)."""
    if not crud.delete_resume(db, user_id, resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")


# ── Applications ──────────────────────────────────────────────────────────────

@router.post(
    "/users/{user_id}/applications",
    response_model=schemas.ApplicationOut,
    status_code=201,
)
def create_application(
    user_id: str,
    data: schemas.ApplicationCreate,
    db: Session = Depends(get_db),
):
    """Save a new job application with all module outputs."""
    return crud.create_application(db, user_id, data)


@router.get(
    "/users/{user_id}/applications",
    response_model=List[schemas.ApplicationOut],
)
def list_applications(
    user_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search job title or company"),
    limit:  int = Query(50, le=200),
    offset: int = Query(0,  ge=0),
    db: Session = Depends(get_db),
):
    """List applications for a user with optional filters."""
    return crud.list_applications(db, user_id, status, search, limit, offset)


@router.get(
    "/users/{user_id}/applications/{app_id}",
    response_model=schemas.ApplicationOut,
)
def get_application(user_id: str, app_id: str, db: Session = Depends(get_db)):
    """Get a single application with full detail."""
    app = crud.get_application(db, user_id, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.patch(
    "/users/{user_id}/applications/{app_id}",
    response_model=schemas.ApplicationOut,
)
def update_application(
    user_id: str,
    app_id: str,
    data: schemas.ApplicationUpdate,
    db: Session = Depends(get_db),
):
    """Update application status, notes, cover letter, or ATS score."""
    app = crud.update_application(db, user_id, app_id, data)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.delete("/users/{user_id}/applications/{app_id}", status_code=204)
def delete_application(user_id: str, app_id: str, db: Session = Depends(get_db)):
    """Permanently delete an application."""
    if not crud.delete_application(db, user_id, app_id):
        raise HTTPException(status_code=404, detail="Application not found")


# ── Dashboard Stats ───────────────────────────────────────────────────────────

@router.get("/users/{user_id}/stats", response_model=schemas.DashboardStats)
def get_stats(user_id: str, db: Session = Depends(get_db)):
    """
    Aggregate stats for the dashboard summary cards:
    total applications, average scores, status breakdown, top companies.
    """
    return crud.get_dashboard_stats(db, user_id)
