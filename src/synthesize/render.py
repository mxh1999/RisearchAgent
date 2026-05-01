"""Render a FieldMap to Markdown — pure deterministic.

The renderer doesn't call any LLM; rerunning produces byte-identical output
for the same FieldMap input. All variability lives in the prior LLM stage
(synthesizer.py).

Per docs/onboard-redesign/10-synthesize.md "Stage 2: 渲染".
"""

from __future__ import annotations

from src.synthesize.types import (
    AnchorPaper,
    BenchmarkEntry,
    ClassicPaper,
    FieldMap,
    Header,
    OpenQuestion,
    PaperRef,
    SchoolOfThought,
    SubArea,
    ActiveGroup,
)


ARXIV_BASE = "https://arxiv.org/abs/"


def render_field_map(fm: FieldMap) -> str:
    """Return a Markdown string. Newlines normalized to '\\n'."""
    parts: list[str] = []
    parts.append(_render_header(fm.header, fm.notes))
    parts.append(_render_sub_areas(fm.sub_areas))
    parts.append(_render_benchmarks(fm.dominant_benchmarks))
    parts.append(_render_schools(fm.schools_of_thought))
    parts.append(_render_classics(fm.classic_baselines))
    parts.append(_render_groups(fm.active_groups))
    parts.append(_render_open_questions(fm.open_questions))
    parts.append(_render_anchors(fm.anchor_papers))
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"


# —————————————————————————————————————————————————————————————
# Section renderers
# —————————————————————————————————————————————————————————————


def _arxiv_link(arxiv_id: str) -> str:
    return f"[{arxiv_id}]({ARXIV_BASE}{arxiv_id})"


def _ref_line(ref: PaperRef) -> str:
    return f"- {_arxiv_link(ref.arxiv_id)} — {ref.title}"


def _render_header(h: Header, notes: list[str]) -> str:
    lines = [
        f"# Field Map: {h.intent_snippet}",
        "",
        f"_Generated {h.generated_at.isoformat(timespec='seconds')}  |  "
        f"{h.n_papers_surveyed} papers surveyed  |  "
        f"{h.n_queries} queries  |  "
        f"{h.elapsed_seconds:.0f}s_",
    ]
    if notes:
        lines.append("")
        lines.append("> **Notes:**")
        for n in notes:
            lines.append(f"> - {n}")
    return "\n".join(lines)


def _render_sub_areas(sub_areas: list[SubArea]) -> str:
    if not sub_areas:
        return "## Sub-areas\n\n_(no sub-areas; clustering may not have run yet)_"
    out = ["## Sub-areas"]
    for sa in sub_areas:
        out.append("")
        out.append(f"### `{sa.slug}` — {sa.display_label}")
        out.append("")
        out.append(sa.description)
        out.append("")
        out.append("**Representative papers:**")
        for ref in sa.representative_papers:
            out.append(_ref_line(ref))
        if sa.shared_benchmarks:
            out.append("")
            out.append(f"**Shared benchmarks:** {', '.join(sa.shared_benchmarks)}")
        if sa.active_authors:
            out.append(f"**Active authors:** {', '.join(sa.active_authors)}")
        out.append(f"**Year range:** {sa.year_range[0]}–{sa.year_range[1]}")
    return "\n".join(out)


def _render_benchmarks(entries: list[BenchmarkEntry]) -> str:
    if not entries:
        return ""
    out = ["## Dominant Benchmarks", ""]
    out.append("| Benchmark | Task | Papers | Sub-areas |")
    out.append("| --- | --- | ---: | --- |")
    for e in entries:
        sas = ", ".join(f"`{s}`" for s in e.associated_subarea_slugs) or "—"
        task = e.task or "—"
        out.append(f"| {e.name} | {task} | {e.n_papers} | {sas} |")
    return "\n".join(out)


def _render_schools(schools: list[SchoolOfThought]) -> str:
    if not schools:
        return ""
    out = ["## Schools of Thought"]
    for s in schools:
        out.append("")
        out.append(f"### {s.name}")
        out.append("")
        out.append(s.description)
        out.append("")
        out.append("**Representative:**")
        for ref in s.representative_papers:
            out.append(_ref_line(ref))
    return "\n".join(out)


def _render_classics(classics: list[ClassicPaper]) -> str:
    if not classics:
        return ""
    out = ["## Classic Baselines", ""]
    for c in classics:
        out.append(
            f"- {_arxiv_link(c.arxiv_id)} ({c.year}) — **{c.title}**  "
        )
        out.append(f"  {c.why_classic}")
    return "\n".join(out)


def _render_groups(groups: list[ActiveGroup]) -> str:
    if not groups:
        return ""
    out = ["## Active Groups", ""]
    for g in groups:
        sas = ", ".join(f"`{s}`" for s in g.associated_subarea_slugs) or "—"
        out.append(f"- **{g.name}** — {g.n_papers} papers — sub-areas: {sas}")
    return "\n".join(out)


def _render_open_questions(qs: list[OpenQuestion]) -> str:
    if not qs:
        return ""
    out = ["## Open Questions", ""]
    for q in qs:
        out.append(f"- {q.question}")
        for ref in q.evidence_papers:
            out.append(f"  - {_arxiv_link(ref.arxiv_id)} — {ref.title}")
    return "\n".join(out)


def _render_anchors(anchors: list[AnchorPaper]) -> str:
    if not anchors:
        return ""
    out = ["## Anchor Papers (for SOTA seeding)", ""]
    for a in anchors:
        out.append(
            f"- {_arxiv_link(a.arxiv_id)} — **{a.title}**  "
            f"_(cluster: `{a.cluster_slug}`)_  "
        )
        out.append(f"  {a.rationale}")
    return "\n".join(out)


__all__ = ["render_field_map"]
