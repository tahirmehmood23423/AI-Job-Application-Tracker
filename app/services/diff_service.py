"""
Diff service — computes a structured diff between the original and tailored résumés.

Produces a list of Change objects, each describing one atomic modification:
  - summary_rewritten:               summary text changed
  - skill_reordered:                 same skills, different order
  - skill_emphasised:                skill moved between buckets
  - experience_bullet_rewritten:     a responsibility line was rewritten
  - experience_bullets_reordered:    bullets within a role reordered
  - project_description_rewritten:   a project description changed
  - projects_reordered:              project order changed

Each Change has stable ID (so the UI can checkbox-track strict-mode acceptance)
and an impact rating (high/medium/low) used to summarise the result.
"""
from __future__ import annotations

from app.models.resume import ParsedResume
from app.models.tailor import Change, ChangeImpact, ChangeType
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DiffService:
    """Pure-function service. No external dependencies."""

    def compute_changes(
        self, original: ParsedResume, tailored: ParsedResume
    ) -> list[Change]:
        changes: list[Change] = []

        # Summary
        if (original.summary or "").strip() != (tailored.summary or "").strip():
            changes.append(Change(
                id="summary",
                type="summary_rewritten",
                impact="high",
                section="summary",
                rationale="Summary rewritten to emphasise content relevant to the target job.",
                before=original.summary,
                after=tailored.summary,
            ))

        # Skills — reordering and movement between buckets
        changes.extend(self._diff_skills(original, tailored))

        # Experience — per role
        changes.extend(self._diff_experience(original, tailored))

        # Projects — descriptions + ordering
        changes.extend(self._diff_projects(original, tailored))

        return changes

    # ---------- Skills ----------

    def _diff_skills(self, original: ParsedResume, tailored: ParsedResume) -> list[Change]:
        out: list[Change] = []

        # Per-bucket reordering check
        bucket_pairs = [
            ("technical", original.skills.technical, tailored.skills.technical),
            ("tools", original.skills.tools, tailored.skills.tools),
            ("soft", original.skills.soft, tailored.skills.soft),
            ("languages", original.skills.languages, tailored.skills.languages),
        ]
        for label, orig, tail in bucket_pairs:
            if set(orig) == set(tail) and orig != tail:
                # Same items, different order
                out.append(Change(
                    id=f"skill-{label}-reorder",
                    type="skill_reordered",
                    impact="medium",
                    section=f"skills.{label}",
                    rationale=f"{label.capitalize()} skills reordered to put the most job-relevant items first.",
                    before_list=orig,
                    after_list=tail,
                ))

        # Bucket-emphasis: a skill moved between buckets
        orig_loc = self._skill_locations(original)
        tail_loc = self._skill_locations(tailored)
        for skill_lower, orig_bucket in orig_loc.items():
            tail_bucket = tail_loc.get(skill_lower)
            if tail_bucket and tail_bucket != orig_bucket:
                out.append(Change(
                    id=f"skill-emphasise-{skill_lower.replace(' ', '-')}",
                    type="skill_emphasised",
                    impact="low",
                    section=f"skills.{tail_bucket}",
                    rationale=(
                        f"'{skill_lower}' moved from {orig_bucket} to {tail_bucket} bucket "
                        f"to better fit the job's emphasis."
                    ),
                    before=orig_bucket,
                    after=tail_bucket,
                ))

        return out

    @staticmethod
    def _skill_locations(resume: ParsedResume) -> dict[str, str]:
        """Map skill (lowercase) → bucket name."""
        out: dict[str, str] = {}
        for bucket_name, items in [
            ("technical", resume.skills.technical),
            ("tools", resume.skills.tools),
            ("soft", resume.skills.soft),
            ("languages", resume.skills.languages),
        ]:
            for s in items:
                out[s.lower().strip()] = bucket_name
        return out

    # ---------- Experience ----------

    def _diff_experience(self, original: ParsedResume, tailored: ParsedResume) -> list[Change]:
        out: list[Change] = []
        # Pair up by position (the rewriter preserves count and order per
        # source-bound enforcement, so positional pairing is reliable).
        for idx, (o_exp, t_exp) in enumerate(zip(original.experience, tailored.experience)):
            # Bullet text changes (per-bullet at matching positions)
            orig_bullets = o_exp.responsibilities
            tail_bullets = t_exp.responsibilities

            if set(orig_bullets) == set(tail_bullets) and orig_bullets != tail_bullets:
                # Same set, different order
                out.append(Change(
                    id=f"exp-{idx}-bullets-reorder",
                    type="experience_bullets_reordered",
                    impact="medium",
                    section=f"experience.{idx}",
                    rationale=(
                        f"Bullets in {o_exp.title} at {o_exp.company} reordered "
                        f"to lead with the most job-relevant achievements."
                    ),
                    before_list=orig_bullets,
                    after_list=tail_bullets,
                ))
                continue

            # Detect per-bullet rewrites (by position)
            for j, (ob, tb) in enumerate(zip(orig_bullets, tail_bullets)):
                if ob.strip() != tb.strip():
                    out.append(Change(
                        id=f"exp-{idx}-bullet-{j}",
                        type="experience_bullet_rewritten",
                        impact=self._estimate_bullet_impact(ob, tb),
                        section=f"experience.{idx}.bullet.{j}",
                        rationale=(
                            f"Bullet {j + 1} of {o_exp.title} at {o_exp.company} "
                            f"rewritten for clarity and job alignment."
                        ),
                        before=ob,
                        after=tb,
                    ))

        return out

    @staticmethod
    def _estimate_bullet_impact(before: str, after: str) -> ChangeImpact:
        """Heuristic: significant length change or strong action verb adoption → high."""
        before_len = len(before.split())
        after_len = len(after.split())
        if abs(after_len - before_len) > 5:
            return "high"
        return "medium"

    # ---------- Projects ----------

    def _diff_projects(self, original: ParsedResume, tailored: ParsedResume) -> list[Change]:
        out: list[Change] = []

        orig_names = [p.name for p in original.projects]
        tail_names = [p.name for p in tailored.projects]
        if set(orig_names) == set(tail_names) and orig_names != tail_names:
            out.append(Change(
                id="projects-reorder",
                type="projects_reordered",
                impact="medium",
                section="projects",
                rationale="Projects reordered to lead with the most job-relevant work.",
                before_list=orig_names,
                after_list=tail_names,
            ))

        # Per-project description changes (match by name to be robust to reorder)
        orig_by_name = {p.name.strip().lower(): p for p in original.projects}
        for idx, t_proj in enumerate(tailored.projects):
            o_proj = orig_by_name.get(t_proj.name.strip().lower())
            if o_proj is None:
                continue
            if (o_proj.description or "").strip() != (t_proj.description or "").strip():
                out.append(Change(
                    id=f"project-{idx}-description",
                    type="project_description_rewritten",
                    impact="medium",
                    section=f"projects.{idx}",
                    rationale=f"Description of '{t_proj.name}' rewritten for job alignment.",
                    before=o_proj.description,
                    after=t_proj.description,
                ))

        return out
