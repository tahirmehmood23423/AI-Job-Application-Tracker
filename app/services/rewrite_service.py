"""
Rewrite service — the heart of Module 3.

Takes a parsed résumé and a job description, asks the LLM to produce a tailored
version of the résumé. The LLM is given strict source-bound instructions: it
may rewrite, reorder, and emphasise existing content but must NEVER invent
new skills, jobs, dates, or accomplishments.

After the LLM call, we run a verification pass that catches the most obvious
violations (e.g., a skill in the tailored output that wasn't in the original).
Detected violations are auto-corrected: the offending content is removed and
a warning is logged.

This is the most legally and ethically sensitive code in the product. A
hallucinated résumé entry could blacklist a candidate from a company.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import LLMExtractionError
from app.models.resume import ParsedResume, Skills
from app.models.tailor import RewrittenResume
from app.services.llm_extractor import LLMExtractor
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------- Prompt ----------

REWRITE_SYSTEM_PROMPT = """\
You are a résumé tailoring assistant. You take a candidate's original résumé and a target job description, and produce a tailored version of the résumé that emphasises the most relevant content for that specific role.

CRITICAL RULES — these are absolute:

1. NEVER invent information. Do NOT add skills, technologies, job titles, companies, dates, certifications, or accomplishments that are not in the original résumé. This is the most important rule.

2. You MAY:
   - Rewrite bullet points using stronger action verbs and clearer language
   - Reorder lists (skills, experience bullets, projects) to put the most relevant items first
   - Move items between skill buckets if obviously misclassified (e.g., "Python" from human languages to technical/programming languages)
   - Emphasise specific aspects of an experience that align with the job
   - Tighten verbose bullet points
   - Use keywords from the job description IF and ONLY IF the candidate already demonstrated that skill/experience in the original résumé

3. You MUST PRESERVE:
   - All companies, job titles, dates, and locations exactly as they appear in the original
   - All education entries exactly
   - All certification names and issuers
   - The candidate's name, contact info, and URLs
   - The total set of skills (you may reorder, never add)
   - The total set of experiences (you may rewrite bullets, never invent new jobs)
   - The total set of projects

4. Output MUST match the schema of the original résumé exactly. Every field present in the original must be present in the output.

5. Output ONLY valid JSON. No markdown fences, no prose, no explanations outside the JSON.

If the original résumé does not contain experience relevant to the job, do not pretend it does. A tailored résumé that doesn't match the job is still better than a fraudulent one.
"""


USER_PROMPT_TEMPLATE = """\
Tailor the original résumé below for the target job. Follow all source-bound rules.

TARGET JOB DESCRIPTION:
\"\"\"
{job_description}
\"\"\"

{job_context}

ORIGINAL RÉSUMÉ (as JSON):
\"\"\"
{resume_json}
\"\"\"

Return the tailored résumé as a JSON object matching the same schema. Output ONLY the JSON.
"""


# ---------- Service ----------


class RewriteService:
    """LLM-driven source-bound résumé rewriting."""

    def __init__(self, llm_extractor: LLMExtractor | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.llm = llm_extractor or LLMExtractor(self.settings)

    @retry(
        retry=retry_if_exception_type(LLMExtractionError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def rewrite(
        self,
        resume: ParsedResume,
        job_description: str,
        job_title: str | None = None,
        company: str | None = None,
    ) -> tuple[RewrittenResume, list[str]]:
        """Rewrite the résumé for the given job.

        Returns:
            (rewritten, warnings) — the tailored résumé plus any source-bound
            violations we caught and corrected.
        """
        # Send a compact JSON of the résumé — drop metadata, keep content
        resume_json = self._resume_to_compact_json(resume)

        job_context_lines = []
        if job_title:
            job_context_lines.append(f"Target job title: {job_title}")
        if company:
            job_context_lines.append(f"Target company: {company}")
        job_context = "\n".join(job_context_lines)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            job_description=job_description.strip(),
            job_context=job_context,
            resume_json=resume_json,
        )

        # Schema hint for the LLM (Gemini benefits from seeing it even though
        # we don't use response_schema strictly).
        schema = RewrittenResume.model_json_schema()

        try:
            raw = self.llm.provider.complete_json(
                REWRITE_SYSTEM_PROMPT, user_prompt, schema
            )
        except LLMExtractionError:
            raise
        except Exception as e:
            logger.exception("Rewrite LLM call failed")
            raise LLMExtractionError(f"Rewrite call failed: {e}") from e

        data = self._parse_json(raw)
        try:
            rewritten = RewrittenResume.model_validate(data)
        except ValidationError as ve:
            logger.error("Rewrite response failed schema validation", extra={"errors": ve.errors()})
            raise LLMExtractionError(f"Rewrite response failed validation: {ve}") from ve

        # Source-bound verification: catch hallucinations.
        rewritten, warnings = self._enforce_source_bound(resume, rewritten)
        return rewritten, warnings

    # ---------- Source-bound enforcement ----------

    def _enforce_source_bound(
        self, original: ParsedResume, rewritten: RewrittenResume
    ) -> tuple[RewrittenResume, list[str]]:
        """Catch and correct LLM hallucinations.

        Returns the (possibly modified) rewritten résumé plus a list of
        warnings describing what was corrected.
        """
        warnings: list[str] = []

        # ----- Personal info: must be preserved verbatim -----
        # We don't allow the LLM to change personal info at all.
        if rewritten.personal != original.personal:
            warnings.append("LLM modified personal info; restored from original.")
            rewritten.personal = original.personal

        # ----- Skills: tailored set must be a subset of original set -----
        original_skills_lower = self._all_skills_lower(original.skills)
        rewritten, skill_warnings = self._enforce_skill_subset(
            rewritten, original_skills_lower
        )
        warnings.extend(skill_warnings)

        # ----- Experience: companies, titles, dates must match originals -----
        rewritten, exp_warnings = self._enforce_experience_structure(
            original, rewritten
        )
        warnings.extend(exp_warnings)

        # ----- Education and certifications: must be preserved -----
        # We don't allow rewriting these at all; restore from original.
        if rewritten.education != original.education:
            warnings.append("LLM modified education; restored from original.")
            rewritten.education = original.education

        if rewritten.certifications != original.certifications:
            warnings.append("LLM modified certifications; restored from original.")
            rewritten.certifications = original.certifications

        # ----- Projects: names must come from originals -----
        rewritten, proj_warnings = self._enforce_project_names(original, rewritten)
        warnings.extend(proj_warnings)

        return rewritten, warnings

    @staticmethod
    def _all_skills_lower(skills: Skills) -> set[str]:
        return {
            s.lower().strip()
            for bucket in (skills.technical, skills.tools, skills.soft, skills.languages)
            for s in bucket
        }

    def _enforce_skill_subset(
        self, rewritten: RewrittenResume, original_skills_lower: set[str]
    ) -> tuple[RewrittenResume, list[str]]:
        """Every skill in the tailored output must exist in the original."""
        warnings: list[str] = []

        def filter_bucket(bucket: list[str], label: str) -> list[str]:
            kept: list[str] = []
            for s in bucket:
                if s.lower().strip() in original_skills_lower:
                    kept.append(s)
                else:
                    warnings.append(
                        f"Removed invented skill '{s}' from {label} bucket."
                    )
            return kept

        rewritten.skills.technical = filter_bucket(rewritten.skills.technical, "technical")
        rewritten.skills.tools = filter_bucket(rewritten.skills.tools, "tools")
        rewritten.skills.soft = filter_bucket(rewritten.skills.soft, "soft")
        rewritten.skills.languages = filter_bucket(rewritten.skills.languages, "languages")
        return rewritten, warnings

    def _enforce_experience_structure(
        self, original: ParsedResume, rewritten: RewrittenResume
    ) -> tuple[RewrittenResume, list[str]]:
        """Companies, titles, dates, locations must match originals."""
        warnings: list[str] = []

        # Build a lookup by (company, title) for the originals
        original_by_key: dict[tuple[str, str], Any] = {
            (e.company.strip().lower(), e.title.strip().lower()): e
            for e in original.experience
        }

        if len(rewritten.experience) != len(original.experience):
            warnings.append(
                f"LLM changed experience count "
                f"({len(original.experience)} -> {len(rewritten.experience)}); "
                f"restoring from original."
            )
            rewritten.experience = original.experience
            return rewritten, warnings

        fixed_experience: list[Any] = []
        for r_exp in rewritten.experience:
            key = (r_exp.company.strip().lower(), r_exp.title.strip().lower())
            if key not in original_by_key:
                warnings.append(
                    f"LLM produced an unknown company/title pair "
                    f"('{r_exp.company}' / '{r_exp.title}'); restoring from original by position."
                )
                # Fall back to the original at the same position
                pos = len(fixed_experience)
                if pos < len(original.experience):
                    fixed_experience.append(original.experience[pos])
                continue

            # Pin the immutable fields from the original
            o = original_by_key[key]
            r_exp.company = o.company
            r_exp.title = o.title
            r_exp.location = o.location
            r_exp.start_date = o.start_date
            r_exp.end_date = o.end_date
            r_exp.is_current = o.is_current
            # responsibilities and technologies may be rewritten/reordered, allowed.
            fixed_experience.append(r_exp)

        rewritten.experience = fixed_experience
        return rewritten, warnings

    def _enforce_project_names(
        self, original: ParsedResume, rewritten: RewrittenResume
    ) -> tuple[RewrittenResume, list[str]]:
        """Project names must match originals."""
        warnings: list[str] = []
        original_names_lower = {p.name.strip().lower() for p in original.projects}

        if len(rewritten.projects) != len(original.projects):
            warnings.append(
                f"LLM changed project count "
                f"({len(original.projects)} -> {len(rewritten.projects)}); "
                f"restoring from original."
            )
            rewritten.projects = original.projects
            return rewritten, warnings

        fixed_projects: list[Any] = []
        for r_proj in rewritten.projects:
            if r_proj.name.strip().lower() not in original_names_lower:
                warnings.append(
                    f"LLM invented project name '{r_proj.name}'; restoring from original by position."
                )
                pos = len(fixed_projects)
                if pos < len(original.projects):
                    fixed_projects.append(original.projects[pos])
                continue
            fixed_projects.append(r_proj)

        rewritten.projects = fixed_projects
        return rewritten, warnings

    # ---------- helpers ----------

    def _resume_to_compact_json(self, resume: ParsedResume) -> str:
        """Serialise the résumé for the LLM prompt, dropping metadata."""
        data = resume.model_dump(
            exclude={"request_id", "parsed_at", "raw_text_length", "extraction_warnings"}
        )
        return json.dumps(data, indent=2, default=str)

    def _parse_json(self, raw: str) -> dict:
        """Tolerate LLM responses wrapped in markdown fences."""
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
