"""
Requirement extractor — Module 2's "smart" pass.

Given a job description, this service asks the LLM to identify the hard
requirements: specific skills, years of experience, certifications, education
requirements, must-have tools.

It then checks each requirement against the parsed résumé and labels it as
"match", "partial", or "missing".

The output feeds two downstream signals:
  1. requirement_coverage (a 0–1 score, weighted by importance)
  2. missing_skills (UI surface — "you're missing X, Y, Z")
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import LLMExtractionError
from app.models.match import MatchedRequirement, Requirement
from app.models.resume import ParsedResume
from app.services.llm_extractor import LLMExtractor  # reuse the provider abstraction
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------- Prompts ----------

REQUIREMENT_EXTRACTION_SYSTEM = """\
You are a recruiting assistant. Given a job description, you extract the hard requirements as structured data.

Rules:
1. Extract specific, testable requirements only. "Strong communication" is too vague; "5+ years of Python" is specific.
2. Classify each requirement's type: skill, experience, education, certification, or other.
3. Classify each requirement's importance: required, preferred, or nice_to_have. Use "required" only when the JD explicitly states the requirement is mandatory ("must have", "required", "minimum"). Use "preferred" for things the JD prefers but lists as optional ("ideal candidate", "plus", "bonus"). Use "nice_to_have" for everything else mentioned in passing.
4. Each requirement should be a single, atomic thing — not a list.
5. Output ONLY valid JSON in the exact format below. No prose, no markdown.

JSON format:
{
  "requirements": [
    {"text": "5+ years of Python experience", "type": "experience", "importance": "required"},
    {"text": "Experience with FastAPI", "type": "skill", "importance": "preferred"}
  ]
}
"""

MATCHING_SYSTEM = """\
You are a recruiting assistant. Given a list of job requirements and a candidate's résumé, you decide whether each requirement is satisfied.

For each requirement, output one of:
- "match" — the résumé clearly demonstrates this requirement
- "partial" — the résumé shows related experience but not exactly this requirement
- "missing" — the résumé does not demonstrate this requirement

For each, also output a short "evidence" quote from the résumé that supports your verdict (or null if missing).

Rules:
1. Be evidence-based. Only mark "match" if the résumé clearly demonstrates the requirement.
2. Be honest about partial matches. Years of experience that fall short, skills mentioned in passing, related-but-different tools — all are "partial", not "match".
3. Don't invent evidence. Use a real, short quote from the résumé.
4. Output ONLY valid JSON in the exact format below.

JSON format:
{
  "matches": [
    {"text": "...", "type": "...", "importance": "...", "status": "match|partial|missing", "evidence": "..." }
  ]
}
The "text", "type", and "importance" fields must be copied EXACTLY from the input.
"""


# ---------- Service ----------


class RequirementExtractor:
    """LLM-driven extraction and matching of job requirements."""

    def __init__(self, llm_extractor: LLMExtractor | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        # We reuse the same LLM provider abstraction Module 1 built. The
        # provider may be Gemini, Claude, or OpenAI — we don't care here.
        self.llm = llm_extractor or LLMExtractor(self.settings)

    # ----- Pass A: extract requirements from JD -----

    @retry(
        retry=retry_if_exception_type(LLMExtractionError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def extract_requirements(self, job_description: str) -> list[Requirement]:
        """Pull hard requirements out of a job description."""
        user_prompt = (
            "Extract all hard requirements from this job description.\n\n"
            f"JOB DESCRIPTION:\n\"\"\"\n{job_description.strip()}\n\"\"\"\n\n"
            "Return ONLY the JSON object."
        )

        # Schema hint: we pass a minimal JSON Schema description to the
        # provider abstraction. Even providers that don't strictly enforce
        # the schema benefit from seeing it.
        schema = {
            "type": "object",
            "properties": {
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "type": {"type": "string"},
                            "importance": {"type": "string"},
                        },
                        "required": ["text", "type", "importance"],
                    },
                }
            },
            "required": ["requirements"],
        }

        try:
            raw = self.llm.provider.complete_json(
                REQUIREMENT_EXTRACTION_SYSTEM, user_prompt, schema
            )
        except LLMExtractionError:
            raise
        except Exception as e:
            raise LLMExtractionError(f"Requirement extraction call failed: {e}") from e

        data = self._parse_json(raw)
        items = data.get("requirements", []) if isinstance(data, dict) else []

        out: list[Requirement] = []
        for item in items:
            try:
                out.append(Requirement.model_validate(item))
            except ValidationError as ve:
                logger.warning("Skipping malformed requirement", extra={"errors": ve.errors()})
        return out

    # ----- Pass B: match those requirements against the résumé -----

    @retry(
        retry=retry_if_exception_type(LLMExtractionError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def match_requirements(
        self, requirements: list[Requirement], resume: ParsedResume
    ) -> list[MatchedRequirement]:
        """For each requirement, decide if the résumé satisfies it."""
        if not requirements:
            return []

        # We send the LLM a compact view of the résumé. Sending the whole
        # ParsedResume JSON would burn tokens; this preserves the matter.
        resume_text = self._summarize_resume_for_matching(resume)

        req_json = json.dumps(
            [r.model_dump() for r in requirements], indent=2
        )

        user_prompt = (
            "Decide whether each requirement is satisfied by the résumé.\n\n"
            f"REQUIREMENTS:\n{req_json}\n\n"
            f"RÉSUMÉ:\n\"\"\"\n{resume_text}\n\"\"\"\n\n"
            "Return ONLY the JSON object."
        )

        schema = {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "type": {"type": "string"},
                            "importance": {"type": "string"},
                            "status": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["text", "type", "importance", "status"],
                    },
                }
            },
            "required": ["matches"],
        }

        try:
            raw = self.llm.provider.complete_json(MATCHING_SYSTEM, user_prompt, schema)
        except LLMExtractionError:
            raise
        except Exception as e:
            raise LLMExtractionError(f"Requirement matching call failed: {e}") from e

        data = self._parse_json(raw)
        items = data.get("matches", []) if isinstance(data, dict) else []

        out: list[MatchedRequirement] = []
        for item in items:
            try:
                out.append(MatchedRequirement.model_validate(item))
            except ValidationError as ve:
                logger.warning(
                    "Skipping malformed match entry", extra={"errors": ve.errors()}
                )
        return out

    # ----- helpers -----

    def _parse_json(self, raw: str) -> dict[str, Any]:
        """Tolerate LLMs that wrap JSON in markdown fences."""
        cleaned = (raw or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("LLM returned invalid JSON", extra={"preview": cleaned[:200]})
            raise LLMExtractionError(f"Invalid JSON from LLM: {e}") from e

    def _summarize_resume_for_matching(self, resume: ParsedResume) -> str:
        """Compact résumé view for the matching LLM call.

        We deliberately drop personal contact info — it's irrelevant to
        matching and would waste tokens.
        """
        lines: list[str] = []

        if resume.summary:
            lines.append(f"Summary: {resume.summary}")

        sk = resume.skills
        if sk.technical:
            lines.append("Technical skills: " + ", ".join(sk.technical))
        if sk.tools:
            lines.append("Tools: " + ", ".join(sk.tools))
        if sk.languages:
            lines.append("Programming languages: " + ", ".join(sk.languages))

        for exp in resume.experience:
            lines.append(
                f"- {exp.title} at {exp.company} "
                f"({exp.start_date or '?'} – {exp.end_date or 'Present'})"
            )
            for r in exp.responsibilities[:3]:  # cap to keep prompt tight
                lines.append(f"    • {r}")
            if exp.technologies:
                lines.append(f"    tech: {', '.join(exp.technologies)}")

        for edu in resume.education:
            lines.append(
                f"- Education: {edu.degree or 'Degree'} at {edu.institution}"
            )

        for proj in resume.projects[:5]:
            lines.append(f"- Project: {proj.name}")
            if proj.technologies:
                lines.append(f"    tech: {', '.join(proj.technologies)}")

        for cert in resume.certifications:
            lines.append(f"- Cert: {cert.name}")

        return "\n".join(lines)
