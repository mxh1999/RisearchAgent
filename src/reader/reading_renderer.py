from __future__ import annotations

import json
from pathlib import Path

from src.reader.staged_models import PaperReadingPackage


def render_reading_markdown(package: PaperReadingPackage) -> str:
    lines: list[str] = [
        f"# {package.title}",
        "",
        "## Metadata",
        "",
    ]
    lines.extend(
        _markdown_table(
            ["Field", "Value"],
            [
                ["Paper ID", package.paper_id],
                ["Source Path", package.source_path],
                ["Pages", str(len(package.pages))],
            ],
        )
    )
    lines.extend(["", "## One-Sentence Takeaway", ""])
    lines.append(package.summary.takeaway if package.summary else "N/A")
    lines.extend(["", "## Problem", ""])
    lines.append(package.summary.problem if package.summary else "N/A")
    lines.extend(["", "## Method", ""])
    lines.append(package.summary.method if package.summary else "N/A")
    lines.extend(["", "## Key Contributions", ""])
    lines.extend(_markdown_list(package.summary.contributions if package.summary else []))
    lines.extend(["", "## Claims And Evidence", ""])
    lines.extend(
        _markdown_table(
            ["Claim", "Page", "Section", "Quote", "Confidence"],
            [
                [
                    claim.text,
                    str(claim.page),
                    claim.section,
                    claim.quote,
                    claim.confidence,
                ]
                for claim in package.claims
            ],
        )
    )
    lines.extend(["", "## Method Breakdown", ""])
    lines.extend(
        _markdown_table(
            ["Module", "Role", "Inputs", "Outputs"],
            [
                [
                    module.name,
                    module.role,
                    ", ".join(module.inputs),
                    ", ".join(module.outputs),
                ]
                for module in package.method_modules
            ],
        )
    )
    lines.extend(["", "## Experiments", ""])
    lines.extend(
        _markdown_table(
            ["Benchmark", "Setting", "Metric", "Method", "Value", "Direction", "Source"],
            [
                [
                    record.benchmark,
                    record.setting,
                    record.metric,
                    record.method,
                    f"{record.value:g}",
                    "higher is better" if record.higher_is_better else "lower is better",
                    f"p. {record.source.page}: {record.source.quote}",
                ]
                for record in package.experiments
            ],
        )
    )
    lines.extend(["", "## Relation To Topic", ""])
    if package.topic_relation:
        lines.extend(
            _markdown_table(
                ["Field", "Value"],
                [
                    ["Relevance", package.topic_relation.relevance],
                    ["Concept Axes", ", ".join(package.topic_relation.concept_axes)],
                    ["Collision Risk", package.topic_relation.collision_risk],
                    ["Differentiation", package.topic_relation.differentiation],
                ],
            )
        )
    else:
        lines.append("N/A")
    lines.extend(["", "## Critical Assessment", ""])
    lines.extend(_markdown_list(package.critique))
    lines.extend(["", "## Follow-Up", ""])
    lines.extend(_markdown_list(package.follow_up_questions))

    return "\n".join(lines).rstrip() + "\n"


def write_reading_package(
    package: PaperReadingPackage,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{package.paper_id}.json"
    markdown_path = output_dir / f"{package.paper_id}.reading.md"

    json_path.write_text(
        json.dumps(package.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    markdown_path.write_text(render_reading_markdown(package), encoding="utf-8")

    return json_path, markdown_path


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
    return str(value).replace("\n", "<br>").replace("|", r"\|")


def _markdown_list(values: list[str]) -> list[str]:
    if not values:
        return ["N/A"]
    return [f"- {value}" for value in values]
