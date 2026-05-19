"""
Top-level parser service.

Orchestrates the pipeline:
  1. TextExtractor.extract(file_bytes) -> str
  2. RegexExtractor.extract(text)      -> contact info (authoritative)
  3. Segmenter.segment(text)            -> sections (optional optimization)
  4. LLMExtractor.extract(text)         -> LLMExtractionResult
  5. Merge regex + LLM results        -> ParsedResume

The merge step is important: regex extraction is ALWAYS preferred for fields
it covers (email, phone, LinkedIn, GitHub), because those are deterministic.
The LLM fills in everything else.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.exceptions import FileTooLargeError, ParserError
from app.config import Settings, get_settings
from app.models.resume import ParsedResume, PersonalInfo
from app.services.llm_extractor import LLMExtractor
from app.services.regex_extractor import RegexExtractor
from app.services.segmenter import Segmenter
from app.services.text_extractor import TextExtractor
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ResumeParserService:
    """The main entry point for parsing a resume from raw bytes."""

    def __init__(
        self,
        settings: Settings | None = None,
        text_extractor: TextExtractor | None = None,
        regex_extractor: RegexExtractor | None = None,
        segmenter: Segmenter | None = None,
        llm_extractor: LLMExtractor | None = None,
    ):
        # Dependency injection makes this easy to test.
        self.settings = settings or get_settings()
        self.text_extractor = text_extractor or TextExtractor()
        self.regex_extractor = regex_extractor or RegexExtractor()
        self.segmenter = segmenter or Segmenter()
        self.llm_extractor = llm_extractor or LLMExtractor(self.settings)

    def parse(self, file_bytes: bytes, filename: str) -> ParsedResume:
        """
        Parse a resume from raw file bytes.

        Args:
            file_bytes: The uploaded file.
            filename: Original filename (used for extension detection).

        Returns:
            A fully populated ParsedResume.

        Raises:
            FileTooLargeError, UnsupportedFileTypeError, EmptyFileError,
            TextExtractionError, LLMExtractionError.
        """
        request_id = str(uuid.uuid4())
        logger.info(
            "Parsing resume",
            extra={"request_id": request_id, "upload_filename": filename},
        )

        # 1. Size guard
        if len(file_bytes) > self.settings.max_file_size_bytes:
            raise FileTooLargeError(
                f"File is {len(file_bytes)} bytes; max allowed is "
                f"{self.settings.max_file_size_bytes} bytes"
            )

        warnings: list[str] = []

        # 2. Text extraction
        text = self.text_extractor.extract(file_bytes, filename)

        # 3. Regex extraction (cheap, always run)
        regex_result = self.regex_extractor.extract(text)

        # 4. Segmentation (used for warnings, not strictly required by LLM)
        segmented = self.segmenter.segment(text)
        if not segmented.has("experience"):
            warnings.append("No 'Experience' section detected — extraction may be incomplete.")
        if not segmented.has("skills"):
            warnings.append("No 'Skills' section detected — skill extraction may be limited.")

        # 5. LLM extraction
        llm_result = self.llm_extractor.extract(text)

        # 6. Merge: regex wins for the fields it knows about
        merged_personal = PersonalInfo(
            full_name=llm_result.personal.full_name,
            email=regex_result.email or llm_result.personal.email,
            phone=regex_result.phone or llm_result.personal.phone,
            location=llm_result.personal.location,
            linkedin_url=regex_result.linkedin_url or llm_result.personal.linkedin_url,
            github_url=regex_result.github_url or llm_result.personal.github_url,
            portfolio_url=regex_result.portfolio_url or llm_result.personal.portfolio_url,
        )

        result = ParsedResume(
            request_id=request_id,
            parsed_at=datetime.now(timezone.utc),
            personal=merged_personal,
            summary=llm_result.summary,
            skills=llm_result.skills,
            experience=llm_result.experience,
            education=llm_result.education,
            projects=llm_result.projects,
            certifications=llm_result.certifications,
            raw_text_length=len(text),
            extraction_warnings=warnings,
        )

        logger.info(
            "Resume parsed successfully",
            extra={
                "request_id": request_id,
                "experience_count": len(result.experience),
                "education_count": len(result.education),
                "skills_count": (
                    len(result.skills.technical)
                    + len(result.skills.tools)
                    + len(result.skills.soft)
                ),
                "warnings": len(warnings),
            },
        )
        return result
