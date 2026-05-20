from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.reader.reading_renderer import validate_safe_paper_id
from src.survey.models import TopicProfile


@dataclass(frozen=True)
class RawDiscoveryPaper:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: datetime
    categories: list[str]
    pdf_url: str
    source_url: str
    query_name: str
    query_purpose: str


@dataclass
class DiscoveryCandidate:
    paper_id: str
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    year: int
    categories: list[str]
    pdf_url: str
    source_url: str
    matched_queries: list[str] = field(default_factory=list)
    query_rationales: list[str] = field(default_factory=list)
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "published": self.published,
            "year": self.year,
            "categories": list(self.categories),
            "pdf_url": self.pdf_url,
            "source_url": self.source_url,
            "matched_queries": list(self.matched_queries),
            "query_rationales": list(self.query_rationales),
            "status": self.status,
        }


@dataclass
class DiscoveryReport:
    topic_id: str
    topic_name: str
    generated_at: str
    query_count: int
    candidate_count: int
    excluded_existing: list[str]
    candidates: list[DiscoveryCandidate]
    source: str = "arxiv"

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "source": self.source,
            "generated_at": self.generated_at,
            "query_count": self.query_count,
            "candidate_count": self.candidate_count,
            "excluded_existing": list(self.excluded_existing),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def build_discovery_report(
    topic: TopicProfile,
    raw_papers: list[RawDiscoveryPaper],
    topic_dir: Path,
    include_existing: bool,
    generated_at: datetime,
) -> DiscoveryReport:
    existing_ids = _existing_paper_ids(topic_dir)
    candidates_by_id: dict[str, DiscoveryCandidate] = {}
    excluded_existing: set[str] = set()

    for raw in raw_papers:
        validate_safe_paper_id(raw.arxiv_id)
        if raw.arxiv_id in existing_ids and not include_existing:
            excluded_existing.add(raw.arxiv_id)
            continue

        candidate = candidates_by_id.get(raw.arxiv_id)
        if candidate is None:
            candidate = DiscoveryCandidate(
                paper_id=raw.arxiv_id,
                arxiv_id=raw.arxiv_id,
                title=raw.title,
                abstract=raw.abstract,
                authors=list(raw.authors),
                published=raw.published.date().isoformat(),
                year=raw.published.year,
                categories=list(raw.categories),
                pdf_url=raw.pdf_url,
                source_url=raw.source_url,
            )
            candidates_by_id[raw.arxiv_id] = candidate

        if raw.query_name not in candidate.matched_queries:
            candidate.matched_queries.append(raw.query_name)
        if raw.query_purpose not in candidate.query_rationales:
            candidate.query_rationales.append(raw.query_purpose)

    candidates = sorted(
        candidates_by_id.values(),
        key=lambda candidate: candidate.paper_id,
    )
    candidates = sorted(
        candidates,
        key=lambda candidate: candidate.published,
        reverse=True,
    )
    return DiscoveryReport(
        topic_id=topic.topic_id,
        topic_name=topic.name,
        generated_at=generated_at.isoformat(),
        query_count=len(topic.search_queries),
        candidate_count=len(candidates),
        excluded_existing=sorted(excluded_existing),
        candidates=candidates,
    )


def render_discovery_markdown(report: DiscoveryReport, topic: TopicProfile) -> str:
    lines = [
        f"# Discovery Candidates: {report.topic_name}",
        "",
        "## Summary",
        "",
        f"- Topic ID: `{report.topic_id}`",
        f"- Source: {report.source}",
        f"- Generated: {report.generated_at}",
        f"- Query Count: {report.query_count}",
        f"- Candidate Count: {report.candidate_count}",
        f"- Excluded Existing: {len(report.excluded_existing)}",
        "",
        "## Queries",
        "",
        "| Name | Query | Purpose |",
        "| --- | --- | --- |",
    ]
    for query in topic.search_queries:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(query.name),
                    _markdown_cell(query.query),
                    _markdown_cell(query.purpose),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Candidates", ""])
    if report.candidates:
        lines.extend(
            [
                "| Paper ID | Title | Published | Year | Categories | Queries | PDF | Source |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for candidate in report.candidates:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(candidate.paper_id),
                        _markdown_cell(candidate.title),
                        _markdown_cell(candidate.published),
                        str(candidate.year),
                        _markdown_cell(", ".join(candidate.categories)),
                        _markdown_cell(", ".join(candidate.matched_queries)),
                        _markdown_cell(candidate.pdf_url),
                        _markdown_cell(candidate.source_url),
                    ]
                )
                + " |"
            )
    else:
        lines.append("No candidates.")

    return "\n".join(lines).rstrip() + "\n"


def render_discovery_manifest_draft(report: DiscoveryReport) -> str:
    raw = {
        "papers": [
            {
                "paper_id": candidate.paper_id,
                "title": candidate.title,
                "pdf_url": candidate.pdf_url,
                "source_url": candidate.source_url,
                "venue": "arXiv",
                "year": candidate.year,
            }
            for candidate in report.candidates
        ]
    }
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


def write_discovery_artifacts(
    topic_dir: Path,
    report: DiscoveryReport,
    topic: TopicProfile,
) -> dict[str, Path]:
    state_dir = topic_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    json_path = state_dir / "discovery_candidates.json"
    markdown_path = topic_dir / "discovery.md"
    manifest_path = topic_dir / "ingest_manifest.draft.yaml"

    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_discovery_markdown(report, topic), encoding="utf-8")
    manifest_path.write_text(
        render_discovery_manifest_draft(report),
        encoding="utf-8",
    )

    return {"json": json_path, "markdown": markdown_path, "manifest": manifest_path}


def _existing_paper_ids(topic_dir: Path) -> set[str]:
    papers_dir = topic_dir / "papers"
    if not papers_dir.exists():
        return set()
    return {path.stem for path in papers_dir.glob("*.json")}


def _markdown_cell(value: object) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "<br>").replace("|", r"\|")
