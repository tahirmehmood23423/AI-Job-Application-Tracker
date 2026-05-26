"""
FastAPI HTTP routes.

Endpoints:
  POST  /api/v1/parse          Parse a résumé file (Module 1)
  POST  /api/v1/match          Match a parsed résumé against a job description (Module 2)
  POST  /api/v1/tailor         Tailor a parsed résumé for a job description (Module 3)
  POST  /api/v1/cover-letter   Generate a cover letter (Module 4)
  GET   /health                Liveness check
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
from app.models.cover_letter import CoverLetterRequest, CoverLetterResult
from app.models.match import MatchRequest, MatchResult
from app.models.resume import ParsedResume
from app.models.tailor import TailorRequest, TailorResult
from app.services.cover_letter_service import CoverLetterService
from app.services.matcher_service import MatcherService
from app.services.parser_service import ResumeParserService
from app.services.tailor_service import TailorService
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ----- Singletons per process (reuse caches and LLM clients) -----

_parser_singleton: ResumeParserService | None = None
_matcher_singleton: MatcherService | None = None
_tailor_singleton: TailorService | None = None
_cover_letter_singleton: CoverLetterService | None = None


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


def get_tailor(settings: Settings = Depends(get_settings)) -> TailorService:
    global _tailor_singleton
    if _tailor_singleton is None:
        _tailor_singleton = TailorService(settings=settings)
    return _tailor_singleton


def get_cover_letter_service() -> CoverLetterService:
    global _cover_letter_singleton
    if _cover_letter_singleton is None:
        _cover_letter_singleton = CoverLetterService()
    return _cover_letter_singleton


# ----- Health -----


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ----- Module 1: Parse -----


@router.post(
    "/api/v1/parse",
    response_model=ParsedResume,
    tags=["parser"],
    summary="Parse a résumé",
    description=(
        "Upload a PDF or DOCX résumé and receive structured JSON in return."
    ),
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
        raise HTTPException(status_code=500, detail="An unexpected error occurred.") from e


# ----- Module 2: Match -----


@router.post(
    "/api/v1/match",
    response_model=MatchResult,
    tags=["matcher"],
    summary="Match a parsed résumé against a job description",
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
        raise HTTPException(status_code=500, detail="An unexpected error occurred.") from e


# ----- Module 3: Tailor -----


@router.post(
    "/api/v1/tailor",
    response_model=TailorResult,
    tags=["tailor"],
    summary="Tailor a parsed résumé for a specific job description",
    description=(
        "Takes a parsed résumé and a job description, returns a tailored version "
        "of the résumé along with a structured diff (what changed) and an ATS "
        "compatibility report. The LLM is source-bound: it may rewrite, reorder, "
        "and emphasise existing content but never invent new information."
    ),
    responses={
        400: {"description": "Invalid input"},
        502: {"description": "LLM call failed"},
        500: {"description": "Internal error"},
    },
)
async def tailor_resume_for_job(
    request: TailorRequest,
    tailor: TailorService = Depends(get_tailor),
) -> TailorResult:
    try:
        return tailor.tailor(request)
    except LLMExtractionError as e:
        logger.exception("Tailor LLM call failed")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}") from e
    except Exception as e:
        logger.exception("Unexpected tailor error")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.") from e


# ----- Module 4: Cover Letter -----


@router.post(
    "/api/v1/cover-letter",
    response_model=CoverLetterResult,
    tags=["cover-letter"],
    summary="Generate a tailored cover letter",
    description=(
        "Two-pass cover letter generator. Pass 1 extracts the strongest talking "
        "points from the résumé, job description, and optional match result. "
        "Pass 2 writes a structured 4-paragraph letter in the chosen tone. "
        "Source-bound: nothing is invented beyond what is in the résumé."
    ),
    responses={
        422: {"description": "LLM returned invalid output"},
        502: {"description": "LLM call failed"},
        500: {"description": "Internal error"},
    },
)
async def generate_cover_letter(
    request: CoverLetterRequest,
    service: CoverLetterService = Depends(get_cover_letter_service),
) -> CoverLetterResult:
    try:
        return service.generate(request)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LLMExtractionError as e:
        logger.exception("Cover letter LLM call failed")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}") from e
    except Exception as e:
        logger.exception("Unexpected cover letter error")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.") from e