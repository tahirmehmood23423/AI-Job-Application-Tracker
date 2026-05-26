"""
Module 4 — Pass 1: Talking Point Extractor
Reads the résumé, match result, and job description.
Returns the strongest, most relevant talking points for the cover letter.

Design: One LLM call. Schema goes in the system prompt (same pattern as Module 3
to avoid Gemini's response_schema rejecting Pydantic's anyOf).
"""

import json
import logging
import os
import re
from typing import Optional

import google.generativeai as genai

from app.models.cover_letter import TalkingPoints

logger = logging.getLogger(__name__)


def _resume_to_text(resume: dict) -> str:
    """
    Flatten the parsed résumé dict into a compact, ordered text block.
    Ordered by signal strength: summary → skills → experience → projects → education → certs.
    Mirrors the resume_to_text() helper in Module 2's EmbeddingService.
    """
    parts = []

    if summary := resume.get("summary"):
        parts.append(f"SUMMARY:\n{summary}")

    if skills := resume.get("skills"):
        if isinstance(skills, list):
            parts.append(f"SKILLS:\n{', '.join(skills)}")
        elif isinstance(skills, dict):
            skill_lines = []
            for category, items in skills.items():
                skill_lines.append(f"  {category}: {', '.join(items) if isinstance(items, list) else items}")
            parts.append("SKILLS:\n" + "\n".join(skill_lines))

    if experience := resume.get("experience"):
        exp_lines = ["EXPERIENCE:"]
        for job in experience:
            title = job.get("title", "")
            company = job.get("company", "")
            dates = job.get("dates", "")
            exp_lines.append(f"  {title} at {company} ({dates})")
            for bullet in job.get("bullets", []):
                exp_lines.append(f"    - {bullet}")
        parts.append("\n".join(exp_lines))

    if projects := resume.get("projects"):
        proj_lines = ["PROJECTS:"]
        for proj in projects:
            name = proj.get("name", "")
            desc = proj.get("description", "")
            proj_lines.append(f"  {name}: {desc}")
        parts.append("\n".join(proj_lines))

    if education := resume.get("education"):
        edu_lines = ["EDUCATION:"]
        for edu in education:
            degree = edu.get("degree", "")
            institution = edu.get("institution", "")
            year = edu.get("year", "")
            edu_lines.append(f"  {degree} — {institution} ({year})")
        parts.append("\n".join(edu_lines))

    if certs := resume.get("certifications"):
        parts.append(f"CERTIFICATIONS:\n" + "\n".join(f"  - {c}" for c in certs))

    return "\n\n".join(parts)


def _match_summary(match_result: Optional[dict]) -> str:
    """
    Extract the most useful signals from a Module 2 match result.
    Returns a compact text block to include in the extraction prompt.
    """
    if not match_result:
        return "No match result provided."

    score = match_result.get("score", "N/A")
    verdict = match_result.get("verdict", "")
    matched_skills = match_result.get("matched_skills", [])
    missing_skills = match_result.get("missing_skills", [])

    lines = [f"Match score: {score}/100 ({verdict})"]
    if matched_skills:
        lines.append(f"Matched skills: {', '.join(matched_skills[:8])}")
    if missing_skills:
        lines.append(f"Missing/partial skills: {', '.join(missing_skills[:4])}")

    return "\n".join(lines)


EXTRACTION_SYSTEM_PROMPT = """You are a professional career coach extracting the strongest talking points for a cover letter.

Analyse the résumé, the job description, and the match result (if provided).
Return ONLY a JSON object — no preamble, no markdown fences, no explanation.

The JSON must follow this schema exactly:
{
  "strongest_experiences": ["string", "string"],   // 2-3 résumé bullets most relevant to this specific job
  "matched_skills": ["string", ...],               // skills the résumé has that the JD explicitly requires
  "standout_achievement": "string",                // single most impressive, quantified achievement
  "why_this_company": "string",                    // inferred reason the candidate fits this role (from JD context)
  "gap_to_address": "string or null"              // one key missing requirement to briefly reframe, or null if no significant gap
}

Rules:
- strongest_experiences: copy bullets verbatim from the résumé — do not invent or embellish
- matched_skills: only list skills explicitly present in both résumé and JD
- standout_achievement: must include a number or measurable result if one exists in the résumé
- why_this_company: infer from the JD's language, mission, or product — do not fabricate
- gap_to_address: only populate if the match result shows a required skill is missing; suggest a reframe, not a lie
"""


class TalkingPointExtractor:
    """
    Pass 1 of the cover letter pipeline.
    One LLM call: résumé + JD + match signals → structured talking points.
    """

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite",
            system_instruction=EXTRACTION_SYSTEM_PROMPT,
        )

    def extract(
        self,
        resume: dict,
        job_description: str,
        match_result: Optional[dict] = None,
    ) -> TalkingPoints:
        """
        Extract talking points from résumé + JD + optional match result.
        Returns a validated TalkingPoints object.
        """
        resume_text = _resume_to_text(resume)
        match_summary = _match_summary(match_result)

        user_message = f"""RÉSUMÉ:
{resume_text}

JOB DESCRIPTION:
{job_description}

MATCH ANALYSIS:
{match_summary}

Extract the strongest talking points for a cover letter targeting this specific job."""

        logger.info("TalkingPointExtractor: calling Gemini for extraction")

        response = self.model.generate_content(
            user_message,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.2,  # Low temperature — extraction should be factual
            ),
        )

        raw = response.text.strip()

        # Strip markdown fences if the model adds them despite the instruction
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"TalkingPointExtractor: JSON parse failed: {e}\nRaw: {raw[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

        # Validate with Pydantic
        try:
            talking_points = TalkingPoints(**data)
        except Exception as e:
            logger.error(f"TalkingPointExtractor: Pydantic validation failed: {e}")
            raise ValueError(f"LLM output did not match schema: {e}") from e

        logger.info(
            f"TalkingPointExtractor: extracted {len(talking_points.matched_skills)} matched skills, "
            f"gap={'yes' if talking_points.gap_to_address else 'no'}"
        )

        return talking_points
