"""
Module 5 — Remotive Job Scraper
Remotive has a completely free, public API — no key needed.
Queries TWO categories to maximize results when LinkedIn is blocked.
API docs: https://remotive.com/api/remote-jobs
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Optional

import httpx

from app.models.job import JobListing, JobSource, JobType
from app.utils.logger import get_logger

logger = get_logger(__name__)

REMOTIVE_API = "https://remotive.com/api/remote-jobs"

# Primary category map
CATEGORY_MAP = {
    "nlp": "machine-learning",
    "ml": "machine-learning",
    "ai": "machine-learning",
    "transformers": "machine-learning",
    "rag": "machine-learning",
    "deep learning": "machine-learning",
    "pytorch": "machine-learning",
    "tensorflow": "machine-learning",
    "llm": "machine-learning",
    "data science": "data",
    "data analyst": "data",
    "backend": "software-dev",
    "frontend": "software-dev",
    "fullstack": "software-dev",
    "devops": "devops-sysadmin",
    "cloud": "devops-sysadmin",
    "fastapi": "software-dev",
    "django": "software-dev",
    "react": "software-dev",
}

# Secondary category to query when primary has few results
SECONDARY_CATEGORY = {
    "machine-learning": "software-dev",
    "software-dev": "data",
    "data": "software-dev",
    "devops-sysadmin": "software-dev",
}


def _make_id(url: str) -> str:
    return f"remotive:{hashlib.md5(url.encode()).hexdigest()[:12]}"


def _detect_category(keywords: list[str]) -> str:
    kw_lower = " ".join(keywords).lower()
    for key, category in CATEGORY_MAP.items():
        if key in kw_lower:
            return category
    return "software-dev"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_jobs(raw_jobs: list[dict], max_results: int) -> list[JobListing]:
    jobs: list[JobListing] = []
    for job in raw_jobs[:max_results]:
        desc_raw = job.get("description", "")
        desc_clean = _strip_html(desc_raw)
        snippet = desc_clean[:300] + "..." if len(desc_clean) > 300 else desc_clean

        job_type_str = (job.get("job_type") or "").lower()
        if "contract" in job_type_str:
            job_type = JobType.contract
        elif "part" in job_type_str:
            job_type = JobType.part_time
        elif "intern" in job_type_str:
            job_type = JobType.internship
        else:
            job_type = JobType.remote

        url = job.get("url", "")
        jobs.append(JobListing(
            id=_make_id(url or str(job.get("id", ""))),
            title=job.get("title", "Unknown Title"),
            company=job.get("company_name", "Unknown"),
            location=job.get("candidate_required_location") or "Remote (Worldwide)",
            salary=job.get("salary") or None,
            job_type=job_type,
            description_snippet=snippet,
            url=url,
            posted_at=job.get("publication_date"),
            source=JobSource.remotive,
        ))
    return jobs


class RemotiveScraper:
    """
    Fetches remote jobs from Remotive's free public API.
    Queries primary + secondary categories for maximum coverage.
    """

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def _fetch_category(self, category: str, search_term: str, limit: int) -> list[dict]:
        """Fetch one category from Remotive API."""
        params = {"category": category, "search": search_term, "limit": limit}
        try:
            with httpx.Client(
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; JobDiscovery/1.0)",
                    "Accept": "application/json",
                },
            ) as client:
                response = client.get(REMOTIVE_API, params=params)
                response.raise_for_status()
            return response.json().get("jobs", [])
        except Exception as e:
            logger.warning(f"RemotiveScraper: category '{category}' failed — {e}")
            return []

    def search(
        self,
        keywords: list[str],
        location: Optional[str] = None,
        max_results: int = 10,
    ) -> list[JobListing]:
        primary_category = _detect_category(keywords)
        secondary_category = SECONDARY_CATEGORY.get(primary_category, "software-dev")
        search_term = " ".join(keywords[:3])

        logger.info(
            f"RemotiveScraper: primary='{primary_category}' "
            f"secondary='{secondary_category}' search='{search_term}'"
        )

        # Fetch primary category
        primary_jobs = self._fetch_category(primary_category, search_term, max_results)
        logger.info(f"RemotiveScraper: primary returned {len(primary_jobs)} jobs")

        all_raw = list(primary_jobs)

        # If primary has fewer than half max_results, query secondary too
        if len(primary_jobs) < max_results // 2:
            time.sleep(0.5)  # polite delay
            secondary_jobs = self._fetch_category(secondary_category, search_term, max_results)
            logger.info(f"RemotiveScraper: secondary returned {len(secondary_jobs)} jobs")
            all_raw.extend(secondary_jobs)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_raw = []
        for job in all_raw:
            url = job.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique_raw.append(job)

        jobs = _parse_jobs(unique_raw, max_results)
        logger.info(f"RemotiveScraper: returning {len(jobs)} unique jobs")
        return jobs
