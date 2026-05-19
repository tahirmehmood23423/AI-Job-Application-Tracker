"""
Deterministic extraction of fields that DO NOT need an LLM.

Why this exists:
  - Email and phone extraction is a solved problem with regex.
  - LLMs occasionally hallucinate digits in phone numbers or strip the +
    from international numbers.
  - Doing it deterministically here lets us trust these fields 100%, and
    save LLM tokens.

We extract:
  - email (first valid match wins, since most resumes have one)
  - phone (handles international formats like +92-300-1234567)
  - LinkedIn URL
  - GitHub URL
  - Generic portfolio URL (anything else that looks like a personal site)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ---------- Regex patterns ----------

# RFC 5322 is overkill; this catches >99% of resume emails reliably.
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
)

# International-aware phone matcher. Accepts:
#   +92 300 1234567 / +1-555-555-5555 / (555) 555-5555 / 555.555.5555 etc.
# We require at least 7 digits total to avoid matching dates or zip codes.
PHONE_RE = re.compile(
    r"""
    (?:
      \+?\d{1,3}[\s\-.()]*       # optional country code
    )?
    (?:\(?\d{2,4}\)?[\s\-.()]*)  # area code or first chunk
    \d{3,4}[\s\-.()]*\d{3,4}     # remaining digits
    """,
    re.VERBOSE,
)

# LinkedIn: matches both linkedin.com/in/username and full URLs
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_\-./]+",
    re.IGNORECASE,
)

# GitHub: matches github.com/username (not nested paths to repos)
GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_\-]+/?",
    re.IGNORECASE,
)

# Generic URL — used to find a portfolio/personal site if no specific match
URL_RE = re.compile(
    r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+",
    re.IGNORECASE,
)

# Domains we DON'T treat as portfolios (they are profiles, not personal sites)
NON_PORTFOLIO_DOMAINS = {
    "linkedin.com",
    "github.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "medium.com",
    "stackoverflow.com",
}


# ---------- Output container ----------


@dataclass
class RegexExtractionResult:
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class RegexExtractor:
    """Pulls out the fields that don't need AI."""

    def extract(self, text: str) -> RegexExtractionResult:
        """Run all regex extractions on the given resume text."""
        return RegexExtractionResult(
            email=self._extract_email(text),
            phone=self._extract_phone(text),
            linkedin_url=self._extract_linkedin(text),
            github_url=self._extract_github(text),
            portfolio_url=self._extract_portfolio(text),
        )

    # ----- Individual extractors -----

    def _extract_email(self, text: str) -> str | None:
        # First match is almost always correct on a resume.
        match = EMAIL_RE.search(text)
        return match.group(0).lower() if match else None

    def _extract_phone(self, text: str) -> str | None:
        # Phone numbers are tricky. Try a few candidates and pick the one
        # with the most digits (resumes sometimes list both an office and
        # personal line; we want the longest/most complete).
        candidates = PHONE_RE.findall(text)
        if not candidates:
            return None

        best: str | None = None
        best_digit_count = 0
        for c in candidates:
            digits = re.sub(r"\D", "", c)
            # 7–15 digits is the legitimate range for any global phone number
            if 7 <= len(digits) <= 15 and len(digits) > best_digit_count:
                best = c.strip().strip(".,;:|")
                best_digit_count = len(digits)
        return best

    def _extract_linkedin(self, text: str) -> str | None:
        match = LINKEDIN_RE.search(text)
        if not match:
            return None
        url = match.group(0).rstrip("/.,;:|")
        if not url.startswith("http"):
            url = "https://" + url
        return url

    def _extract_github(self, text: str) -> str | None:
        match = GITHUB_RE.search(text)
        if not match:
            return None
        url = match.group(0).rstrip("/.,;:|")
        if not url.startswith("http"):
            url = "https://" + url
        return url

    def _extract_portfolio(self, text: str) -> str | None:
        """First URL that isn't LinkedIn, GitHub, etc."""
        for match in URL_RE.finditer(text):
            url = match.group(0).rstrip(".,;:|)")
            if not any(domain in url.lower() for domain in NON_PORTFOLIO_DOMAINS):
                return url
        return None
