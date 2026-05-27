"""
Module 5 — JobDiscoveryService (Orchestrator)
1. Extract keywords from résumé if not provided
2. Query all requested sources in parallel
3. Deduplicate by job ID
4. Auto-match each job against the résumé using embedding similarity
5. Sort by match score descending
"""

from __future__ import annotations

import concurrent.futures
from typing import Optional

from app.config import Settings, get_settings
from app.models.job import JobListing, JobSearchRequest, JobSearchResult, JobSource
from app.services.indeed_scraper import IndeedScraper
from app.services.linkedin_scraper import LinkedInScraper
from app.services.remotive_scraper import RemotiveScraper
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How many top skills to use as search keywords
MAX_KEYWORDS = 5


def _extract_keywords(resume: dict) -> list[str]:
    """
    Auto-extract the best search keywords from a parsed résumé.
    Priority: technical skills > job titles > tools.
    """
    keywords: list[str] = []

    skills = resume.get("skills", {})
    if isinstance(skills, dict):
        technical = skills.get("technical", [])
        tools = skills.get("tools", [])
        # Prefer specific technical terms
        keywords.extend(technical[:3])
        keywords.extend(tools[:2])
    elif isinstance(skills, list):
        keywords.extend(skills[:MAX_KEYWORDS])

    # Add most recent job title if we still need more
    if len(keywords) < 3:
        experience = resume.get("experience", [])
        if experience:
            title = experience[0].get("title", "")
            if title:
                keywords.insert(0, title)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique.append(kw)

    return unique[:MAX_KEYWORDS]


def _compute_simple_match(job: JobListing, resume: dict) -> tuple[float, str]:
    """
    Fast keyword-based match score (no LLM, no embeddings — keeps this endpoint snappy).
    Returns (score 0-100, verdict).
    """
    # Collect all resume text
    skills = resume.get("skills", {})
    if isinstance(skills, dict):
        all_skills = (
            skills.get("technical", []) +
            skills.get("tools", []) +
            skills.get("soft", []) +
            skills.get("languages", [])
        )
    else:
        all_skills = skills if isinstance(skills, list) else []

    experience = resume.get("experience", [])
    titles = [e.get("title", "") for e in experience]
    summary = resume.get("summary", "") or ""

    resume_text = " ".join(all_skills + titles + [summary]).lower()

    # Score against job title + snippet
    job_text = f"{job.title} {job.description_snippet}".lower()

    job_words = set(w for w in job_text.split() if len(w) > 3)
    resume_words = set(w for w in resume_text.split() if len(w) > 3)

    if not job_words:
        return 0.0, "weak"

    overlap = job_words & resume_words
    raw_score = len(overlap) / len(job_words)

    # Scale: raw cosine-like overlap rarely exceeds 0.4 for good matches
    score = min(round(raw_score * 250), 100)

    if score >= 70:
        verdict = "strong"
    elif score >= 45:
        verdict = "moderate"
    else:
        verdict = "weak"

    return float(score), verdict


def _deduplicate(jobs: list[JobListing]) -> list[JobListing]:
    seen_ids: set[str] = set()
    unique: list[JobListing] = []
    for job in jobs:
        if job.id not in seen_ids:
            seen_ids.add(job.id)
            unique.append(job)
    return unique


class JobDiscoveryService:
    """
    Orchestrates job discovery across multiple sources.
    Singleton — instantiated once at startup.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.linkedin = LinkedInScraper()
        self.indeed = IndeedScraper()
        self.remotive = RemotiveScraper()
        logger.info("JobDiscoveryService initialised")

    def discover(self, request: JobSearchRequest) -> JobSearchResult:
        """
        Full pipeline:
        1. Extract keywords from résumé
        2. Query all sources concurrently
        3. Deduplicate
        4. Auto-match if requested
        5. Sort by score
        """
        # Step 1: Keywords
        keywords = request.keywords or _extract_keywords(request.resume)
        if not keywords:
            keywords = ["software engineer"]  # fallback

        logger.info(
            f"JobDiscoveryService.discover: keywords={keywords}, "
            f"location={request.location}, sources={request.sources}"
        )

        # Step 2: Query sources concurrently
        all_jobs: list[JobListing] = []

        def fetch_linkedin():
            if JobSource.linkedin in request.sources:
                return self.linkedin.search(
                    keywords=keywords,
                    location=request.location,
                    max_results=request.max_results_per_source,
                )
            return []

        def fetch_indeed():
            if JobSource.indeed in request.sources:
                return self.indeed.search(
                    keywords=keywords,
                    location=request.location,
                    max_results=request.max_results_per_source,
                )
            return []

        def fetch_remotive():
            if JobSource.remotive in request.sources:
                return self.remotive.search(
                    keywords=keywords,
                    location=request.location,
                    max_results=request.max_results_per_source,
                )
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(fetch_linkedin),
                executor.submit(fetch_indeed),
                executor.submit(fetch_remotive),
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    all_jobs.extend(future.result())
                except Exception as e:
                    logger.error(f"JobDiscoveryService: source fetch failed — {e}")

        # Step 3: Deduplicate
        unique_jobs = _deduplicate(all_jobs)
        logger.info(f"JobDiscoveryService: {len(all_jobs)} total → {len(unique_jobs)} after dedup")

        # Step 4: Auto-match
        if request.auto_match:
            for job in unique_jobs:
                score, verdict = _compute_simple_match(job, request.resume)
                job.match_score = score
                job.match_verdict = verdict

            # Sort by match score descending
            unique_jobs.sort(key=lambda j: j.match_score or 0, reverse=True)

        return JobSearchResult(
            jobs=unique_jobs,
            total_found=len(unique_jobs),
            keywords_used=keywords,
            location_used=request.location,
            sources_queried=request.sources,
            auto_matched=request.auto_match,
        )
