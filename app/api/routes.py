"""
FastAPI HTTP routes.

Endpoints:
  POST   /api/v1/parse    Parse a résumé file (Module 1)
  POST   /api/v1/match    Match a parsed résumé against a job description (Module 2)
  GET    /health          Liveness check
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import Settings, get_settings
from app.core.exceptions import (
    EmptyFileError,
    FileTooLargeError,
    LLMExtractionError,
    ParserError,
    TextExtractionError,
    UnsupportedFileTypeError,
)
from app.models.match import MatchRequest, MatchResult
from app.models.resume import ParsedResume
from app.services.matcher_service import MatcherService
from app.services.parser_service import ResumeParserService
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# Singletons per process — both services have internal state (caches, LLM
# clients) and benefit from being reused across requests.
_parser_singleton: ResumeParserService | None = None
_matcher_singleton: MatcherService | None = None


def get_parser(settings: Settings = Depends(get_settings)) -> ResumeParserService:
    global _parser_singleton
    if _parser_singleton is None:
        _parser_singleton = ResumeParserService(settings=settings)
    return _parser_singleton


def get_matcher(settings: Settings = Depends(get_settings)) -> MatcherService:
    global _matcher_singleton
    if _matcher_singleton is None:
        _matcher_singleton = MatcherService(settings=settings)
    return _matcher_singleton


# ----- Health -----


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness check used by load balancers and uptime monitors."""
    return {"status": "ok"}


# ----- Module 1: Parse -----


@router.post(
    "/api/v1/parse",
    response_model=ParsedResume,
    tags=["parser"],
    summary="Parse a résumé",
    description=(
        "Upload a PDF or DOCX résumé and receive structured JSON in return. "
        "The response contains personal info, skills, work experience, "
        "education, projects, and certifications."
    ),
    responses={
        400: {"description": "Invalid file (unsupported type, too large, empty)"},
        422: {"description": "File could not be parsed (corrupt or unreadable)"},
        500: {"description": "Internal error (LLM failure, unexpected exception)"},
    },
)
async def parse_resume(
    file: UploadFile = File(..., description="Résumé file (PDF or DOCX, max 10 MB)"),
    parser: ResumeParserService = Depends(get_parser),
) -> ParsedResume:
    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no name")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        return parser.parse(contents, file.filename)
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except EmptyFileError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except TextExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LLMExtractionError as e:
        logger.exception("LLM extraction failed", extra={"upload_filename": file.filename})
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {e}") from e
    except ParserError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.exception("Unexpected parser error", extra={"upload_filename": file.filename})
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Check server logs.",
        ) from e


# ----- Module 2: Match -----


@router.post(
    "/api/v1/match",
    response_model=MatchResult,
    tags=["matcher"],
    summary="Match a parsed résumé against a job description",
    description=(
        "Takes a parsed résumé (the output of /api/v1/parse) plus a job "
        "description and returns a 0–100 match score with breakdowns: "
        "semantic similarity, requirement coverage, matched and missing skills, "
        "and a short narrative summary."
    ),
    responses={
        400: {"description": "Invalid input (missing fields, JD too short)"},
        502: {"description": "LLM or embedding API failed"},
        500: {"description": "Internal error"},
    },
)
async def match_resume_to_job(
    request: MatchRequest,
    matcher: MatcherService = Depends(get_matcher),
) -> MatchResult:
    try:
        return matcher.match(request)
    except LLMExtractionError as e:
        logger.exception("Match LLM/embedding call failed")
        raise HTTPException(status_code=502, detail=f"LLM/embedding call failed: {e}") from e
    except Exception as e:
        logger.exception("Unexpected matcher error")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Check server logs.",
        ) from e
