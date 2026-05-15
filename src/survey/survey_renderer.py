from __future__ import annotations

from src.survey.synthesis_models import SurveySynthesis


ROLE_HEADINGS = {
    "core": "Core",
    "adjacent": "Adjacent",
    "collision": "Collision",
    "background": "Background",
}


def render_taxonomy_markdown(synthesis: SurveySynthesis) -> str:
    lines = ["## Method Groups", ""]
    if not synthesis.taxonomy:
        lines.append("No taxonomy groups were generated.")
    for group in synthesis.taxonomy:
        lines.extend(
            [
                f"### {group.name}",
                "",
                group.description,
                "",
                f"- Papers: {_format_ids(group.paper_ids)}",
                f"- Key distinction: {group.key_distinction}",
                "",
            ]
        )
    lines.extend(["## Open Questions", ""])
    lines.extend(_list_or_na(synthesis.open_questions))
    return _finish(lines)


def render_paper_map_markdown(synthesis: SurveySynthesis) -> str:
    lines: list[str] = []
    for role, heading in ROLE_HEADINGS.items():
        items = [item for item in synthesis.paper_map if item.role == role]
        lines.extend([f"## {heading}", ""])
        if not items:
            lines.extend(["N/A", ""])
            continue
        for item in items:
            lines.extend(
                [
                    f"### {item.title} (`{item.paper_id}`)",
                    "",
                    f"- Rationale: {item.rationale}",
                    f"- Evidence: {item.evidence or 'N/A'}",
                    "",
                ]
            )
    return _finish(lines)


def render_positioning_markdown(synthesis: SurveySynthesis) -> str:
    positioning = synthesis.positioning
    lines = [
        "## Thesis Gap",
        "",
        positioning.thesis_gap,
        "",
        "## Novelty Claim",
        "",
        positioning.novelty_claim,
        "",
        "## Recommended Positioning",
        "",
        positioning.recommended_positioning,
        "",
        "## Collision Risks",
        "",
    ]
    lines.extend(_list_or_na(positioning.collision_risks))
    return _finish(lines)


def render_references_markdown(synthesis: SurveySynthesis) -> str:
    rows = [
        [
            f"`{entry.paper_id}`",
            entry.title,
            entry.why_relevant,
            entry.evidence or "N/A",
        ]
        for entry in synthesis.references
    ]
    return _finish(_markdown_table(["Paper ID", "Title", "Why Relevant", "Evidence"], rows))


def _format_ids(paper_ids: list[str]) -> str:
    if not paper_ids:
        return "N/A"
    return ", ".join(f"`{paper_id}`" for paper_id in paper_ids)


def _list_or_na(values: list[str]) -> list[str]:
    if not values:
        return ["N/A"]
    return [f"- {value}" for value in values]


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["N/A"]
    return [
        _markdown_table_row(headers),
        _markdown_table_row(["---"] * len(headers)),
        *[_markdown_table_row(row) for row in rows],
    ]


def _markdown_table_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_table_cell(value) for value in values) + " |"


def _escape_table_cell(value: str) -> str:
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "<br>").replace("|", r"\|")


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"
