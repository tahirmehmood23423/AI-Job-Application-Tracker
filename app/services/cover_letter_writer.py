"""
Module 4 — Pass 2: Cover Letter Writer
Takes the talking points from Pass 1 + tone preference + context.
Writes a complete, structured 4-paragraph cover letter.

Design: One LLM call. Higher temperature than Pass 1 (creative writing, not extraction).
Source-bound: the writer is instructed to use only the provided talking points.
"""

from __future__ import annotations

import google.generativeai as genai

from app.config import Settings, get_settings
from app.models.cover_letter import TalkingPoints, TonePreference
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Tone instruction fragments injected into the writer prompt
TONE_INSTRUCTIONS = {
    TonePreference.professional: (
        "Write in a polished, formal tone. Use clear, direct sentences. "
        "Avoid contractions. Convey competence and reliability."
    ),
    TonePreference.conversational: (
        "Write in a warm, natural tone — like a smart person talking to a hiring manager, not reading from a template. "
        "Contractions are fine. Short sentences are fine. Sound like a human."
    ),
    TonePreference.confident: (
        "Write with authority. Lead with achievements, not qualifications. "
        "Use active verbs. No hedging language ('I believe', 'I think', 'I hope'). "
        "State facts and let them speak."
    ),
    TonePreference.enthusiastic: (
        "Write with genuine energy. Show real interest in the company and role. "
        "The candidate is excited — that should be apparent. "
        "Balance enthusiasm with substance; avoid hollow filler phrases."
    ),
}

WRITER_SYSTEM_PROMPT = """You are an expert cover letter writer. Your job is to write a complete, compelling cover letter using ONLY the talking points provided. Do not invent new experiences, skills, or achievements.

Structure — four paragraphs:
1. OPENING: Hook + why this specific role/company. Reference the job title and company name if provided.
2. EXPERIENCE: Weave the strongest_experiences and matched_skills into a coherent narrative about what the candidate brings.
3. ACHIEVEMENT: Highlight the standout_achievement. Connect it to what the employer needs.
4. CLOSING: Forward-looking. Express interest in next steps. Professional sign-off.

Format rules:
- Include a proper salutation ("Dear Hiring Manager," or "Dear [Company] Team," if company is known)
- End with "Sincerely," followed by a blank line for the signature
- No placeholder text like [Your Name] — just leave the signature line blank
- 250–350 words total
- No bullet points — flowing prose only

Source-bound rule: Every claim must come from the provided talking points. If a talking point is null or empty, skip it gracefully — do not fill the gap with invented content."""


class CoverLetterWriter:
    """
    Pass 2 of the cover letter pipeline.
    One LLM call: talking points + tone + context → complete cover letter.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

        if not self.settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set in settings")

        genai.configure(api_key=self.settings.gemini_api_key)

        # Mirror GeminiProvider: accept model name with or without "models/" prefix
        model = self.settings.gemini_model
        model_name = model if model.startswith("models/") else f"models/{model}"

        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=WRITER_SYSTEM_PROMPT,
        )

    def write(
        self,
        talking_points: TalkingPoints,
        tone: TonePreference,
        job_title: str | None = None,
        company_name: str | None = None,
    ) -> str:
        """
        Write a cover letter from talking points + tone + optional context.
        Returns the cover letter as a plain string.
        """
        tone_instruction = TONE_INSTRUCTIONS[tone]

        tp_lines = [
            "Strongest experiences (use verbatim from résumé):",
            *[f"  - {exp}" for exp in talking_points.strongest_experiences],
            f"\nMatched skills: {', '.join(talking_points.matched_skills)}",
            f"\nStandout achievement: {talking_points.standout_achievement}",
            f"\nWhy this company/role: {talking_points.why_this_company}",
        ]
        if talking_points.gap_to_address:
            tp_lines.append(f"\nGap to address/reframe: {talking_points.gap_to_address}")

        talking_points_block = "\n".join(tp_lines)

        context_lines = []
        if job_title:
            context_lines.append(f"Job title: {job_title}")
        if company_name:
            context_lines.append(f"Company: {company_name}")
        context_block = "\n".join(context_lines) if context_lines else "Job title and company not specified."

        user_message = f"""Context:
{context_block}

Tone instruction:
{tone_instruction}

Talking points to use:
{talking_points_block}

Write the complete cover letter now."""

        logger.info(f"CoverLetterWriter: calling Gemini (tone={tone.value})")

        response = self.model.generate_content(
            user_message,
            generation_config=genai.GenerationConfig(
                temperature=0.7,
            ),
        )

        cover_letter = response.text.strip()

        logger.info(
            f"CoverLetterWriter: generated {len(cover_letter.split())} words "
            f"(tone={tone.value})"
        )

        return cover_letter
