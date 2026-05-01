"""Field map diff: compare two FieldMaps from refine runs.

Per docs/onboard-redesign/10-synthesize.md "Refine 模式：Diff 视图". This
is fully deterministic (no LLM). Used by Refine flow to show the user
what changed since the last run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.synthesize.types import BenchmarkEntry, FieldMap, SubArea


@dataclass
class SubAreaChange:
    slug: str
    label_old: str
    label_new: str
    n_old: int
    n_new: int

    @property
    def delta(self) -> int:
        return self.n_new - self.n_old


@dataclass
class FieldMapDiff:
    new_subareas: list[SubArea] = field(default_factory=list)
    removed_subareas: list[SubArea] = field(default_factory=list)
    grown_subareas: list[SubAreaChange] = field(default_factory=list)
    shrunk_subareas: list[SubAreaChange] = field(default_factory=list)
    new_benchmarks: list[BenchmarkEntry] = field(default_factory=list)
    removed_benchmarks: list[str] = field(default_factory=list)


def diff_field_maps(old: FieldMap, new: FieldMap) -> FieldMapDiff:
    """Compute structural diff between an older FieldMap and a newer one.

    "Size" of a sub-area is len(representative_papers) since FieldMap doesn't
    carry the full cluster size — Synthesizer should put a representative
    sample. For a more precise size you'd need the underlying ClusterSnapshot.
    """
    old_by_slug = {sa.slug: sa for sa in old.sub_areas}
    new_by_slug = {sa.slug: sa for sa in new.sub_areas}

    diff = FieldMapDiff()

    for slug, sa_new in new_by_slug.items():
        if slug not in old_by_slug:
            diff.new_subareas.append(sa_new)
            continue
        sa_old = old_by_slug[slug]
        n_old = len(sa_old.representative_papers)
        n_new = len(sa_new.representative_papers)
        if n_new > n_old:
            diff.grown_subareas.append(
                SubAreaChange(slug, sa_old.display_label, sa_new.display_label, n_old, n_new)
            )
        elif n_new < n_old:
            diff.shrunk_subareas.append(
                SubAreaChange(slug, sa_old.display_label, sa_new.display_label, n_old, n_new)
            )

    for slug, sa_old in old_by_slug.items():
        if slug not in new_by_slug:
            diff.removed_subareas.append(sa_old)

    old_bench_names = {b.name for b in old.dominant_benchmarks}
    new_bench_names = {b.name for b in new.dominant_benchmarks}
    for be in new.dominant_benchmarks:
        if be.name not in old_bench_names:
            diff.new_benchmarks.append(be)
    diff.removed_benchmarks = sorted(old_bench_names - new_bench_names)

    return diff


def render_diff_markdown(d: FieldMapDiff) -> str:
    """Render FieldMapDiff to a Markdown summary."""
    lines = ["# Field Map Update", ""]

    if not (
        d.new_subareas
        or d.removed_subareas
        or d.grown_subareas
        or d.shrunk_subareas
        or d.new_benchmarks
        or d.removed_benchmarks
    ):
        lines.append("_No structural changes._")
        return "\n".join(lines) + "\n"

    if d.new_subareas:
        lines.append("## New sub-areas")
        for sa in d.new_subareas:
            lines.append(
                f"- `{sa.slug}` — {sa.display_label} "
                f"({len(sa.representative_papers)} representative papers)"
            )
        lines.append("")

    if d.grown_subareas:
        lines.append("## Grown sub-areas")
        for c in d.grown_subareas:
            lines.append(f"- `{c.slug}`: {c.n_old} → {c.n_new} papers (+{c.delta})")
        lines.append("")

    if d.shrunk_subareas:
        lines.append("## Shrunk sub-areas")
        for c in d.shrunk_subareas:
            lines.append(f"- `{c.slug}`: {c.n_old} → {c.n_new} papers ({c.delta:+d})")
        lines.append("")

    if d.removed_subareas:
        lines.append("## Removed sub-areas")
        for sa in d.removed_subareas:
            lines.append(f"- `{sa.slug}` — {sa.display_label}")
        lines.append("")

    if d.new_benchmarks:
        lines.append("## New benchmarks")
        for be in d.new_benchmarks:
            lines.append(f"- {be.name} ({be.n_papers} papers)")
        lines.append("")

    if d.removed_benchmarks:
        lines.append("## Removed benchmarks")
        for name in d.removed_benchmarks:
            lines.append(f"- {name}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["FieldMapDiff", "SubAreaChange", "diff_field_maps", "render_diff_markdown"]
