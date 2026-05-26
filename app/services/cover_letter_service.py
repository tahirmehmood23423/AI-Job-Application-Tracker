"""
Module 4 — CoverLetterService (Orchestrator)
Runs Pass 1 (extraction) then Pass 2 (writing).
Returns the complete CoverLetterResult.

Mirrors MatcherService from Module 2 — single responsibility: orchestrate and combine.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.models.cover_letter import CoverLetterRequest, CoverLetterResult
from app.services.cover_letter_writer import CoverLetterWriter
from app.services.talking_point_extractor import TalkingPointExtractor
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CoverLetterService:
    """
    Singleton orchestrator. Holds one instance of each pass service.
    FastAPI wires this up via Depends() in routes.py.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.extractor = TalkingPointExtractor(settings=self.settings)
        self.writer = CoverLetterWriter(settings=self.settings)
        logger.info("CoverLetterService initialised (extractor + writer ready)")

    def generate(self, request: CoverLetterRequest) -> CoverLetterResult:
        """
        Full two-pass pipeline:
          Pass 1: Extract talking points from résumé + JD + match result
          Pass 2: Write cover letter from talking points + tone
        """
        logger.info(
            f"CoverLetterService.generate: tone={request.tone.value}, "
            f"has_match_result={request.match_result is not None}, "
            f"jd_length={len(request.job_description)}"
        )

        # --- Pass 1: Extract talking points ---
        talking_points = self.extractor.extract(
            resume=request.resume,
            job_description=request.job_description,
            match_result=request.match_result,
        )

        # --- Pass 2: Write the cover letter ---
        cover_letter = self.writer.write(
            talking_points=talking_points,
            tone=request.tone,
            job_title=request.job_title,
            company_name=request.company_name,
        )

        # Extract match score if provided
        match_score = None
        if request.match_result:
            # Support both "overall_score" (Module 2 schema) and "score" (generic)
            match_score = request.match_result.get(
                "overall_score", request.match_result.get("score")
            )
            if match_score is not None:
                try:
                    match_score = float(match_score)
                except (TypeError, ValueError):
                    match_score = None

        word_count = len(cover_letter.split())

        logger.info(
            f"CoverLetterService.generate: complete — "
            f"{word_count} words, match_score={match_score}"
        )

        return CoverLetterResult(
            cover_letter=cover_letter,
            talking_points=talking_points,
            word_count=word_count,
            tone_applied=request.tone,
            match_score_used=match_score,
        )
