"""
ATS compatibility checker.

Scans the tailored résumé content against a set of rules that ATS (Applicant
Tracking System) software is known to handle well or poorly, and against the
job description for keyword coverage.

This is content-only analysis — we don't render a PDF, so we can't catch
layout-level ATS issues (tables, multi-column, icons, headers/footers). Those
are properties of the original document and the user's chosen format, not of
our JSON output. We focus on the things we CAN check from structured data.

Score formula: 100 - (errors × 15) - (warnings × 5) - (info × 1), floored at 0.
"""
from __future__ import annotations

import re
from collections import Counter

from app.models.resume import ParsedResume
from app.models.tailor import ATSIssue, ATSReport
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Words too common to be meaningful "keywords". Used to filter JD tokens.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "he", "in", "is", "it", "its", "of", "on", "or", "she", "that",
    "the", "their", "they", "this", "to", "was", "we", "were", "will", "with",
    "you", "your", "our", "us", "i", "me", "my", "but", "if", "then", "so",
    "do", "does", "did", "can", "could", "should", "would", "may", "might",
    "must", "shall", "such", "than", "too", "very", "just", "into", "out",
    "up", "down", "over", "under", "about", "across", "after", "before",
    "between", "during", "while", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "no", "not", "only", "own", "same",
    "what", "when", "where", "who", "whom", "why", "how", "which",
    # Job-description boilerplate
    "role", "team", "company", "candidate", "candidates", "responsibilities",
    "requirements", "experience", "skills", "ability", "able", "looking",
    "join", "work", "working", "build", "building", "develop", "developing",
    "help", "ideal", "plus", "bonus", "preferred", "required", "must",
    "years", "year", "include", "including", "etc",
}

# Severity weights
WEIGHTS = {"error": 15, "warning": 5, "info": 1}


class ATSChecker:
    """Pure-function service. No external dependencies."""

    def check(self, tailored: ParsedResume, job_description: str) -> ATSReport:
        issues: list[ATSIssue] = []

        # 1. Required sections present
        issues.extend(self._check_completeness(tailored))

        # 2. Contact info on the résumé
        issues.extend(self._check_contact(tailored))

        # 3. Bullet quality (length, action verbs)
        issues.extend(self._check_bullet_quality(tailored))

        # 4. Skill density (too few skills hurts ATS keyword scoring)
        issues.extend(self._check_skill_density(tailored))

        # 5. Date format consistency
        issues.extend(self._check_date_formats(tailored))

        # Keyword coverage against the JD
        coverage, matches, misses = self._keyword_coverage(tailored, job_description)
        if coverage < 0.4:
            issues.append(ATSIssue(
                severity="warning",
                rule="LOW_KEYWORD_COVERAGE",
                message=(
                    f"Only {int(coverage * 100)}% of the job's keywords appear in the résumé. "
                    f"Consider weaving in more of them where you genuinely have experience."
                ),
            ))
        elif coverage < 0.6:
            issues.append(ATSIssue(
                severity="info",
                rule="MODERATE_KEYWORD_COVERAGE",
                message=f"Keyword coverage is {int(coverage * 100)}%. Decent but could be tighter.",
            ))

        # Compute score
        score = 100
        for issue in issues:
            score -= WEIGHTS.get(issue.severity, 0)
        score = max(0, score)

        return ATSReport(
            score=score,
            issues=issues,
            keyword_coverage=round(coverage, 3),
            keyword_matches=matches,
            keyword_misses=misses,
        )

    # ---------- Section checks ----------

    @staticmethod
    def _check_completeness(resume: ParsedResume) -> list[ATSIssue]:
        out: list[ATSIssue] = []
        if not resume.experience:
            out.append(ATSIssue(
                severity="error",
                rule="MISSING_EXPERIENCE",
                message="No work experience listed. ATS systems weight experience heavily.",
                where="experience",
            ))
        if not resume.education:
            out.append(ATSIssue(
                severity="warning",
                rule="MISSING_EDUCATION",
                message="No education listed. Most ATS systems require this section.",
                where="education",
            ))
        skill_total = (
            len(resume.skills.technical) + len(resume.skills.tools)
            + len(resume.skills.soft) + len(resume.skills.languages)
        )
        if skill_total == 0:
            out.append(ATSIssue(
                severity="error",
                rule="MISSING_SKILLS",
                message="No skills listed. ATS keyword matching depends on this section.",
                where="skills",
            ))
        if not resume.summary:
            out.append(ATSIssue(
                severity="info",
                rule="MISSING_SUMMARY",
                message=(
                    "No summary section. A 2–3 sentence summary at the top helps "
                    "ATS systems and human screeners quickly grok the candidate."
                ),
                where="summary",
            ))
        return out

    # ---------- Contact info ----------

    @staticmethod
    def _check_contact(resume: ParsedResume) -> list[ATSIssue]:
        out: list[ATSIssue] = []
        p = resume.personal
        if not p.email:
            out.append(ATSIssue(
                severity="error",
                rule="MISSING_EMAIL",
                message="No email address. ATS systems use email as the primary contact identifier.",
                where="personal.email",
            ))
        if not p.phone:
            out.append(ATSIssue(
                severity="warning",
                rule="MISSING_PHONE",
                message="No phone number. Many ATS systems require this for screening.",
                where="personal.phone",
            ))
        if not p.full_name:
            out.append(ATSIssue(
                severity="error",
                rule="MISSING_NAME",
                message="No name on the résumé.",
                where="personal.full_name",
            ))
        return out

    # ---------- Bullet quality ----------

    # Strong action verbs commonly recommended for résumé bullets
    ACTION_VERBS = {
        "led", "built", "designed", "developed", "implemented", "architected",
        "delivered", "shipped", "launched", "scaled", "optimised", "optimized",
        "reduced", "increased", "improved", "drove", "spearheaded", "founded",
        "created", "established", "engineered", "deployed", "automated",
        "migrated", "refactored", "owned", "managed", "mentored", "trained",
        "researched", "analysed", "analyzed", "modelled", "modeled", "tuned",
        "evaluated", "tested", "integrated", "presented", "published",
    }

    def _check_bullet_quality(self, resume: ParsedResume) -> list[ATSIssue]:
        out: list[ATSIssue] = []
        bullets_without_action = 0
        very_long_bullets = 0
        very_short_bullets = 0
        total = 0

        for exp in resume.experience:
            for bullet in exp.responsibilities:
                total += 1
                words = bullet.split()
                first = words[0].lower().rstrip(",.;:") if words else ""
                if first not in self.ACTION_VERBS:
                    bullets_without_action += 1
                if len(words) > 35:
                    very_long_bullets += 1
                elif len(words) < 4:
                    very_short_bullets += 1

        if total > 0:
            if bullets_without_action / total > 0.5:
                out.append(ATSIssue(
                    severity="info",
                    rule="WEAK_ACTION_VERBS",
                    message=(
                        f"{bullets_without_action} of {total} bullets don't start with a strong action verb. "
                        f"Try 'Led', 'Built', 'Reduced', 'Designed' etc."
                    ),
                ))
            if very_long_bullets > 0:
                out.append(ATSIssue(
                    severity="info",
                    rule="LONG_BULLETS",
                    message=f"{very_long_bullets} bullet(s) are over 35 words. ATS and recruiters prefer concise bullets.",
                ))
            if very_short_bullets > total / 3:
                out.append(ATSIssue(
                    severity="info",
                    rule="SHORT_BULLETS",
                    message=f"{very_short_bullets} bullet(s) are under 4 words. Add detail and context.",
                ))

        return out

    # ---------- Skill density ----------

    @staticmethod
    def _check_skill_density(resume: ParsedResume) -> list[ATSIssue]:
        total = (
            len(resume.skills.technical) + len(resume.skills.tools)
            + len(resume.skills.languages)
        )
        if total < 5:
            return [ATSIssue(
                severity="warning",
                rule="LOW_SKILL_DENSITY",
                message=(
                    f"Only {total} hard skills listed. Most successful résumés have 10–20 "
                    f"tagged skills/tools/languages — this is what ATS systems index."
                ),
                where="skills",
            )]
        return []

    # ---------- Date format consistency ----------

    @staticmethod
    def _check_date_formats(resume: ParsedResume) -> list[ATSIssue]:
        # Just look for obvious year-only vs YYYY-MM inconsistency
        formats_seen: Counter[str] = Counter()
        for exp in resume.experience:
            for d in (exp.start_date, exp.end_date):
                if not d or d == "Present":
                    continue
                if re.fullmatch(r"\d{4}", d):
                    formats_seen["year"] += 1
                elif re.fullmatch(r"\d{4}-\d{2}", d):
                    formats_seen["year-month"] += 1
                else:
                    formats_seen["other"] += 1

        if len(formats_seen) > 1 and sum(formats_seen.values()) > 1:
            return [ATSIssue(
                severity="info",
                rule="INCONSISTENT_DATES",
                message=(
                    "Date formats vary across the résumé (mix of YYYY and YYYY-MM). "
                    "Pick one and stick with it for cleaner ATS parsing."
                ),
                where="experience",
            )]
        return []

    # ---------- Keyword coverage ----------

    def _keyword_coverage(
        self, resume: ParsedResume, job_description: str
    ) -> tuple[float, list[str], list[str]]:
        """Returns (coverage_fraction, matched_keywords, missed_keywords)."""
        jd_keywords = self._extract_jd_keywords(job_description)
        if not jd_keywords:
            return 1.0, [], []

        resume_text = self._resume_text(resume).lower()
        matched: list[str] = []
        missed: list[str] = []
        for kw in jd_keywords:
            if kw.lower() in resume_text:
                matched.append(kw)
            else:
                missed.append(kw)

        coverage = len(matched) / len(jd_keywords)
        return coverage, matched, missed

    @staticmethod
    def _extract_jd_keywords(jd: str, top_n: int = 20) -> list[str]:
        """Extract candidate keywords from the JD by frequency, minus stopwords.

        Heuristic: prefer capitalised tokens (likely proper nouns / tech names)
        and tokens with at least 3 chars.
        """
        # Find tokens including dots and pluses for things like C++, Node.js
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9\.\+\#\-]{1,}", jd)
        # Keep tokens with at least 3 chars
        tokens = [t for t in tokens if len(t) >= 3]

        # Count, ignoring stopwords (case-insensitive comparison)
        counter: Counter[str] = Counter()
        for t in tokens:
            if t.lower() in STOPWORDS:
                continue
            counter[t] += 1

        # De-duplicate case variants: keep the most common casing
        consolidated: dict[str, tuple[str, int]] = {}
        for token, count in counter.most_common():
            key = token.lower()
            if key in consolidated:
                _, existing = consolidated[key]
                consolidated[key] = (token, existing + count)
            else:
                consolidated[key] = (token, count)

        ranked = sorted(consolidated.values(), key=lambda x: -x[1])
        return [token for token, _ in ranked[:top_n]]

    @staticmethod
    def _resume_text(resume: ParsedResume) -> str:
        """Flatten the résumé to one big searchable text blob."""
        parts: list[str] = []
        if resume.summary:
            parts.append(resume.summary)
        parts.extend(resume.skills.technical)
        parts.extend(resume.skills.tools)
        parts.extend(resume.skills.languages)
        parts.extend(resume.skills.soft)
        for e in resume.experience:
            parts.append(f"{e.title} {e.company}")
            parts.extend(e.responsibilities)
            parts.extend(e.technologies)
        for p in resume.projects:
            parts.append(p.name)
            if p.description:
                parts.append(p.description)
            parts.extend(p.technologies)
        for edu in resume.education:
            parts.append(f"{edu.degree or ''} {edu.field_of_study or ''} {edu.institution}")
        for c in resume.certifications:
            parts.append(c.name)
        return " ".join(parts)
