"""
Tailor service — top-level orchestrator for Module 3.

Pipeline:
  1. Call RewriteService.rewrite() — LLM produces a tailored RewrittenResume,
     with source-bound enforcement catching hallucinations.
  2. Wrap the RewrittenResume back into a ParsedResume (copying metadata from
     the original).
  3. Call DiffService.compute_changes() — structured list of changes.
  4. Call ATSChecker.check() — ATS report on the tailored résumé.
  5. Assemble TailorResult.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.models.resume import ParsedResume
from app.models.tailor import (
    Change,
    RewrittenResume,
    TailorRequest,
    TailorResult,
)
from app.services.ats_checker import ATSChecker
from app.services.diff_service import DiffService
from app.services.rewrite_service import RewriteService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TailorService:
    """Top-level orchestrator for Module 3."""

    def __init__(
        self,
        settings: Settings | None = None,
        rewrite_service: RewriteService | None = None,
        diff_service: DiffService | None = None,
        ats_checker: ATSChecker | None = None,
    ):
        self.settings = settings or get_settings()
        self.rewriter = rewrite_service or RewriteService(settings=self.settings)
        self.differ = diff_service or DiffService()
        self.ats = ats_checker or ATSChecker()

    def tailor(self, request: TailorRequest) -> TailorResult:
        request_id = str(uuid.uuid4())
        logger.info(
            "Running tailor",
            extra={
                "request_id": request_id,
                "mode": request.mode,
                "jd_length": len(request.job_description),
            },
        )

        # Step 1+2: LLM rewrite with source-bound enforcement
        rewritten, warnings = self.rewriter.rewrite(
            request.resume,
            request.job_description,
            job_title=request.job_title,
            company=request.company,
        )

        # Step 3: wrap into a ParsedResume preserving metadata
        tailored = self._wrap_as_parsed_resume(request.resume, rewritten, warnings)

        # Step 4: structured diff
        changes = self.differ.compute_changes(request.resume, tailored)
        logger.info(
            "Diff computed",
            extra={"request_id": request_id, "n_changes": len(changes)},
        )

        # Step 5: ATS report
        ats_report = self.ats.check(tailored, request.job_description)
        logger.info(
            "ATS check done",
            extra={
                "request_id": request_id,
                "ats_score": ats_report.score,
                "issues": len(ats_report.issues),
            },
        )

        # Step 6: assemble result
        high_impact = sum(1 for c in changes if c.impact == "high")
        return TailorResult(
            request_id=request_id,
            tailored_at=datetime.now(timezone.utc),
            mode=request.mode,
            original=request.resume,
            tailored=tailored,
            changes=changes,
            ats_report=ats_report,
            job_title=request.job_title,
            company=request.company,
            total_changes=len(changes),
            high_impact_changes=high_impact,
        )

    # ---------- helpers ----------

    @staticmethod
    def _wrap_as_parsed_resume(
        original: ParsedResume,
        rewritten: RewrittenResume,
        source_bound_warnings: list[str],
    ) -> ParsedResume:
        """Take the LLM's content and merge it with the original's metadata.

        We do NOT generate a new request_id here — the tailor service has its
        own. We do append any source-bound warnings to extraction_warnings so
        the UI can surface them if it wants.
        """
        merged_warnings = list(original.extraction_warnings) + source_bound_warnings
        return ParsedResume(
            request_id=original.request_id,         # echo from original
            parsed_at=original.parsed_at,           # echo from original
            personal=rewritten.personal,
            summary=rewritten.summary,
            skills=rewritten.skills,
            experience=rewritten.experience,
            education=rewritten.education,
            projects=rewritten.projects,
            certifications=rewritten.certifications,
            raw_text_length=original.raw_text_length,
            extraction_warnings=merged_warnings,
        )
