"""
Module 5 — Indeed Job Scraper
Uses Indeed's public RSS feed — no API key needed.
RSS URL: https://www.indeed.com/rss?q=keywords&l=location
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote_plus

import httpx

from app.models.job import JobListing, JobSource, JobType
from app.utils.logger import get_logger

logger = get_logger(__name__)

INDEED_RSS = "https://www.indeed.com/rss?q={keywords}&l={location}&sort=date"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _make_id(url: str) -> str:
    return f"indeed:{hashlib.md5(url.encode()).hexdigest()[:12]}"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


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


def _parse_rss(xml_text: str, max_results: int) -> list[JobListing]:
    """Parse Indeed RSS XML into JobListing objects."""
    jobs: list[JobListing] = []

    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return jobs

        ns = {"indeed": "https://www.indeed.com/"}
        items = channel.findall("item")[:max_results]

        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pubdate_el = item.find("pubDate")

            # Indeed-specific elements
            company_el = item.find("indeed:company", ns)
            location_el = item.find("indeed:city", ns)
            state_el = item.find("indeed:state", ns)
            salary_el = item.find("indeed:salary", ns)

            if title_el is None or link_el is None:
                continue

            title = (title_el.text or "").strip()
            # Indeed title format: "Job Title - Company"
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                company_fallback = parts[1].strip()
            else:
                company_fallback = ""

            company = (company_el.text if company_el is not None else company_fallback) or "Unknown"

            city = location_el.text if location_el is not None else ""
            state = state_el.text if state_el is not None else ""
            location = ", ".join(filter(None, [city, state])) or "Not specified"

            salary = salary_el.text if salary_el is not None else None

            desc_raw = desc_el.text if desc_el is not None else ""
            desc_clean = _strip_html(desc_raw)
            snippet = desc_clean[:300] + "..." if len(desc_clean) > 300 else desc_clean

            url = (link_el.text or "").strip()
            pub_date = pubdate_el.text if pubdate_el is not None else None

            jobs.append(JobListing(
                id=_make_id(url),
                title=title,
                company=company,
                location=location,
                salary=salary,
                job_type=_detect_job_type(desc_clean + " " + title),
                description_snippet=snippet,
                url=url,
                posted_at=pub_date,
                source=JobSource.indeed,
            ))

    except ET.ParseError as e:
        logger.error(f"IndeedScraper: RSS parse error — {e}")

    return jobs


class IndeedScraper:
    """
    Fetches jobs from Indeed's public RSS feed.
    No API key required.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(
        self,
        keywords: list[str],
        location: Optional[str] = None,
        max_results: int = 10,
    ) -> list[JobListing]:
        kw_str = quote_plus(" ".join(keywords))
        loc_str = quote_plus(location or "")

        url = INDEED_RSS.format(keywords=kw_str, location=loc_str)
        logger.info(f"IndeedScraper: fetching RSS for '{' '.join(keywords)}'")

        try:
            with httpx.Client(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()

            jobs = _parse_rss(response.text, max_results)
            logger.info(f"IndeedScraper: found {len(jobs)} jobs")
            return jobs

        except httpx.HTTPStatusError as e:
            logger.warning(f"IndeedScraper: HTTP {e.response.status_code}")
            return []
        except httpx.RequestError as e:
            logger.warning(f"IndeedScraper: request failed — {e}")
            return []
        except Exception as e:
            logger.error(f"IndeedScraper: unexpected error — {e}")
            return []
