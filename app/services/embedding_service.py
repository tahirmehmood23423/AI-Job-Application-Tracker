"""
Embedding service for the Job-Résumé Matcher.

Uses Google's Gemini embedding model (`text-embedding-004`) — free, no card,
and shares credentials with the LLM extractor from Module 1.

The cosine similarity math is plain Python — we don't need numpy for two
vectors. Keeping dependencies light helps the Docker image stay small.

Caching: we cache embeddings in memory keyed by SHA-256 of the input text.
A parsed résumé doesn't change between match requests, so re-embedding it
every time is wasteful. The cache is per-process, no persistence; fine for
our scale.
"""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from app.config import Settings, get_settings
from app.core.exceptions import LLMConfigurationError, LLMExtractionError
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Task type hints make Gemini's embeddings more useful for retrieval tasks.
# "retrieval_document" for the corpus side (résumé), "retrieval_query" for the
# query side (JD). Mixing these correctly improves match scores noticeably.
TASK_DOCUMENT = "retrieval_document"
TASK_QUERY = "retrieval_query"


def _hash_text(text: str) -> str:
    """Stable cache key for arbitrarily long text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingService:
    """Wraps Gemini's embedding API with a tiny in-memory cache."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

        if self.settings.llm_provider != "gemini" or not self.settings.gemini_api_key:
            raise LLMConfigurationError(
                "EmbeddingService currently requires Gemini credentials. "
                "Set LLM_PROVIDER=gemini and GEMINI_API_KEY in your environment."
            )

        try:
            import google.generativeai as genai
        except ImportError as e:
            raise LLMConfigurationError("`google-generativeai` package not installed") from e

        genai.configure(api_key=self.settings.gemini_api_key)
        self._genai = genai
        # Hard-coded to text-embedding-004 because it's the only currently
        # free Gemini embedding model (May 2026). If that changes, expose
        # it via Settings.
        self._model = "models/gemini-embedding-001"
        # In-memory cache; small footprint, big speedup on repeat matches.
        self._cache: dict[tuple[str, str], list[float]] = {}

    def embed(self, text: str, task: str = TASK_DOCUMENT) -> list[float]:
        """Return the embedding vector for the given text.

        Args:
            text: input text. Will be truncated by the model if very long;
                we don't pre-truncate so we get whatever Gemini does.
            task: 'retrieval_document' for indexed corpora, 'retrieval_query'
                for the search side. See Google's docs for the full list.

        Returns:
            A list of floats (the embedding vector).
        """
        # Empty / whitespace-only input would error; guard up-front.
        clean = (text or "").strip()
        if not clean:
            raise LLMExtractionError("Cannot embed empty text")

        cache_key = (task, _hash_text(clean))
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            result = self._genai.embed_content(
                model=self._model,
                content=clean,
                task_type=task,
            )
        except Exception as e:
            logger.exception("Gemini embedding call failed")
            raise LLMExtractionError(f"Embedding call failed: {e}") from e

        # The SDK returns either {"embedding": [...]} or .embedding depending
        # on version. Handle both shapes defensively.
        if isinstance(result, dict):
            vector = result.get("embedding")
        else:
            vector = getattr(result, "embedding", None)

        if not vector or not isinstance(vector, list):
            raise LLMExtractionError("Gemini embedding response was empty or malformed")

        self._cache[cache_key] = vector
        return vector


# --- Pure math, no external deps ----------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. For text embeddings this is almost
    always in [0, 1] in practice."""
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --- Resume → text helper used by the matcher --------------------------


def resume_to_text(resume) -> str:
    """Flatten a ParsedResume into a single string suitable for embedding.

    We don't just concatenate everything in declaration order — we put the
    high-signal stuff (skills, titles, responsibilities) first so the
    embedding emphasises them. Empty fields are skipped.
    """
    parts: list[str] = []

    if resume.summary:
        parts.append(f"Summary: {resume.summary}")

    # Skills — flatten across buckets but tag them so the model knows the type
    skills = resume.skills
    if skills.technical:
        parts.append("Technical skills: " + ", ".join(skills.technical))
    if skills.tools:
        parts.append("Tools: " + ", ".join(skills.tools))
    if skills.languages:
        parts.append("Languages: " + ", ".join(skills.languages))
    if skills.soft:
        parts.append("Soft skills: " + ", ".join(skills.soft))

    # Experience — title, company, and every bullet
    for exp in resume.experience:
        header = f"{exp.title} at {exp.company}"
        if exp.start_date or exp.end_date:
            header += f" ({exp.start_date or '?'} – {exp.end_date or 'Present'})"
        parts.append(header)
        for r in exp.responsibilities:
            parts.append(f"- {r}")
        if exp.technologies:
            parts.append("Technologies: " + ", ".join(exp.technologies))

    # Projects
    for proj in resume.projects:
        line = f"Project: {proj.name}"
        if proj.description:
            line += f" — {proj.description}"
        parts.append(line)
        if proj.technologies:
            parts.append("Stack: " + ", ".join(proj.technologies))

    # Education (lower weight, but include for completeness)
    for edu in resume.education:
        parts.append(
            f"Education: {edu.degree or ''} {edu.field_of_study or ''} at {edu.institution}".strip()
        )

    # Certifications
    for cert in resume.certifications:
        parts.append(f"Certification: {cert.name}")

    return "\n".join(parts).strip()
