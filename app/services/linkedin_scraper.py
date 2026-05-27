"""
Module 5 — LinkedIn Job Scraper
Uses LinkedIn's public job search page (HTML scraping, no auth required).
Falls back gracefully if blocked — Remotive handles the bulk anyway.

Note: LinkedIn aggressively blocks cloud/server IPs. This works on:
  ✅ Local development (your laptop IP)
  ✅ Hugging Face Spaces (rotating IPs, usually works)
  ❌ Shared sandbox environments

If LinkedIn returns 403/429, the service silently returns [] and
Remotive + Indeed fill the results — no crash, no error to the user.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Optional
from urllib.parse import quote_plus

import httpx

from app.models.job import JobListing, JobSource, JobType
from app.utils.logger import get_logger

logger = get_logger(__name__)

# LinkedIn's public job search URL (HTML, not RSS — RSS was removed in 2024)
LINKEDIN_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={keywords}&location={location}"
    "&f_TPR=r604800&position=1&pageNum=0"
)

# Guest API endpoint — sometimes works without auth
LINKEDIN_GUEST_API = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords={keywords}&location={location}&start=0"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def _make_id(url: str) -> str:
    return f"linkedin:{hashlib.md5(url.encode()).hexdigest()[:12]}"


def _detect_job_type(text: str) -> JobType:
    lower = text.lower()
    if "remote" in lower:
        return JobType.remote
    if "part-time" in lower or "part time" in lower:
        return JobType.part_time
    if "contract" in lower:
        return JobType.contract
    if "intern" in lower:
        return JobType.internship
    if "full-time" in lower or "full time" in lower:
        return JobType.full_time
    return JobType.unknown


def _parse_html(html: str, max_results: int) -> list[JobListing]:
    """
    Extract job listings from LinkedIn HTML using regex.
    LinkedIn's structure: job cards with data-entity-urn and nested spans.
    """
    jobs: list[JobListing] = []

    # Match job card blocks
    card_pattern = re.compile(
        r'<li[^>]*>\s*<div[^>]*base-card[^>]*>(.*?)</div>\s*</li>',
        re.DOTALL
    )

    # Extract individual fields
    title_pattern = re.compile(r'class="base-search-card__title"[^>]*>\s*([^<]+?)\s*<', re.DOTALL)
    company_pattern = re.compile(r'class="base-search-card__subtitle"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*<', re.DOTALL)
    location_pattern = re.compile(r'class="job-search-card__location"[^>]*>\s*([^<]+?)\s*<', re.DOTALL)
    link_pattern = re.compile(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"?]+)')
    date_pattern = re.compile(r'datetime="([^"]+)"')

    cards = card_pattern.findall(html)[:max_results]

    for card in cards:
        title_m = title_pattern.search(card)
        company_m = company_pattern.search(card)
        location_m = location_pattern.search(card)
        link_m = link_pattern.search(card)
        date_m = date_pattern.search(card)

        if not title_m or not link_m:
            continue

        title = title_m.group(1).strip()
        company = company_m.group(1).strip() if company_m else "Unknown"
        location = location_m.group(1).strip() if location_m else "Not specified"
        url = link_m.group(1).strip()
        posted_at = date_m.group(1) if date_m else None

        jobs.append(JobListing(
            id=_make_id(url),
            title=title,
            company=company,
            location=location,
            description_snippet=f"{title} at {company} — {location}",
            url=url,
            posted_at=posted_at,
            source=JobSource.linkedin,
            job_type=_detect_job_type(location + " " + title),
        ))

    return jobs


class LinkedInScraper:
    """
    Fetches jobs from LinkedIn's public job search page.
    Gracefully returns [] if blocked (403/429) — Remotive fills the gap.
    """

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def search(
        self,
        keywords: list[str],
        location: Optional[str] = None,
        max_results: int = 10,
    ) -> list[JobListing]:
        kw_str = quote_plus(" ".join(keywords))
        loc_str = quote_plus(location or "")

        url = LINKEDIN_SEARCH_URL.format(keywords=kw_str, location=loc_str)
        logger.info(f"LinkedInScraper: fetching jobs for '{' '.join(keywords)}'")

        try:
            # Small delay to be respectful
            time.sleep(1)

            with httpx.Client(
                headers=HEADERS,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                response = client.get(url)

            if response.status_code in (403, 429, 999):
                logger.warning(
                    f"LinkedInScraper: blocked (HTTP {response.status_code}) — "
                    "returning empty list. Remotive will cover results."
                )
                return []

            response.raise_for_status()

            jobs = _parse_html(response.text, max_results)
            logger.info(f"LinkedInScraper: found {len(jobs)} jobs")
            return jobs

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"LinkedInScraper: HTTP {e.response.status_code} — "
                "returning empty. This is normal on cloud IPs."
            )
            return []
        except httpx.RequestError as e:
            logger.warning(f"LinkedInScraper: request failed — {e}")
            return []
        except Exception as e:
            logger.error(f"LinkedInScraper: unexpected error — {e}")
            return []
