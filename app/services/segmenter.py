"""
Heuristic section detection for resumes.

The output is a dict like:
  {
    "experience": "Senior Engineer at Acme...",
    "education": "MS in CS, NUST...",
    "skills": "Python, FastAPI, ...",
    ...
  }

We don't rely on this being perfect. The LLM gets the full text as a backup
input, so segmentation is an optimization, not a hard requirement.

Why bother then? Two reasons:
  1. Some resumes (especially long ones) are easier for the LLM to parse
     when given clear section labels.
  2. It lets us run quick sanity checks: "did we find a Skills section?
     If not, raise an extraction_warning."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Common header variations for each canonical section. Order matters —
# the longest/most specific match should come first.
SECTION_PATTERNS: dict[str, list[str]] = {
    "summary": [
        "professional summary",
        "career summary",
        "executive summary",
        "summary",
        "profile",
        "objective",
        "career objective",
        "about me",
        "about",
    ],
    "experience": [
        "professional experience",
        "work experience",
        "employment history",
        "experience",
        "work history",
        "employment",
    ],
    "education": [
        "education",
        "academic background",
        "academic qualifications",
        "qualifications",
    ],
    "skills": [
        "technical skills",
        "core competencies",
        "key skills",
        "skills",
        "competencies",
        "technologies",
        "tech stack",
    ],
    "projects": [
        "projects",
        "personal projects",
        "selected projects",
        "key projects",
        "academic projects",
    ],
    "certifications": [
        "certifications",
        "certificates",
        "licenses",
        "credentials",
    ],
}


def _build_header_regex() -> re.Pattern[str]:
    """
    One compiled regex that matches any known section header at the start
    of a line. The named group tells us which canonical section it is.
    """
    alternatives: list[str] = []
    for canonical, variants in SECTION_PATTERNS.items():
        # Escape variants and join with |; wrap in a named group
        escaped = [re.escape(v) for v in variants]
        group = rf"(?P<{canonical}>{'|'.join(escaped)})"
        alternatives.append(group)

    pattern = (
        r"^\s*"                                       # start of line, optional leading whitespace
        r"(?:" + "|".join(alternatives) + r")"        # one of the section headers
        r"\s*[:\-—–]?\s*$"                            # optional trailing colon/dash, end of line
    )
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


_HEADER_RE = _build_header_regex()


@dataclass
class SegmentedResume:
    sections: dict[str, str] = field(default_factory=dict)
    preamble: str = ""  # Text before the first detected section (usually name + contact)

    def has(self, section: str) -> bool:
        return section in self.sections and bool(self.sections[section].strip())


class Segmenter:
    """Splits a resume into canonical sections by detecting headers."""

    def segment(self, text: str) -> SegmentedResume:
        """
        Args:
            text: Cleaned resume text from TextExtractor.

        Returns:
            SegmentedResume with one entry per detected section.
        """
        matches = list(_HEADER_RE.finditer(text))

        if not matches:
            # No headers detected — treat entire text as preamble.
            # The LLM will handle this from the full text.
            return SegmentedResume(preamble=text)

        result = SegmentedResume()
        result.preamble = text[: matches[0].start()].strip()

        for i, m in enumerate(matches):
            # Determine which canonical section this header matched
            canonical = next(
                (name for name in SECTION_PATTERNS if m.group(name) is not None),
                None,
            )
            if canonical is None:
                continue

            # Content runs from end-of-header to start-of-next-header (or end-of-text)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()

            # If we hit the same section twice (shouldn't usually happen),
            # concatenate.
            if canonical in result.sections:
                result.sections[canonical] += "\n" + content
            else:
                result.sections[canonical] = content

        return result
