from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.survey.models import TopicProfile, TopicQuery
from src.survey.topic_discover import (
    RawDiscoveryPaper,
    build_discovery_report,
    render_discovery_manifest_draft,
    render_discovery_markdown,
    write_discovery_artifacts,
)


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Find candidate papers.",
        search_queries=[
            TopicQuery(
                name="direct",
                query='"utility" "navigation"',
                purpose="Direct topic query.",
            ),
            TopicQuery(
                name="benchmark",
                query='"GOAT-Bench" navigation',
                purpose="Benchmark query.",
            ),
        ],
    )


def _paper(
    arxiv_id: str,
    title: str,
    query_name: str,
    published: str = "2024-01-02T00:00:00+00:00",
) -> RawDiscoveryPaper:
    return RawDiscoveryPaper(
        arxiv_id=arxiv_id,
        title=title,
        abstract="This paper studies utility for embodied navigation. " * 4,
        authors=["A. Researcher", "B. Researcher"],
        published=datetime.fromisoformat(published),
        categories=["cs.RO", "cs.CV"],
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        query_name=query_name,
        query_purpose=f"{query_name} purpose",
    )


def test_build_discovery_report_deduplicates_queries_and_excludes_existing(
    tmp_path: Path,
) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "2401.00002.json").write_text("{}", encoding="utf-8")

    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[
            _paper("2401.00001", "First Paper", "direct"),
            _paper("2401.00001", "First Paper", "benchmark"),
            _paper("2401.00002", "Existing Paper", "direct"),
        ],
        topic_dir=tmp_path,
        include_existing=False,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert report.query_count == 2
    assert report.candidate_count == 1
    assert report.excluded_existing == ["2401.00002"]
    assert report.candidates[0].paper_id == "2401.00001"
    assert report.candidates[0].matched_queries == ["direct", "benchmark"]
    assert report.candidates[0].query_rationales == [
        "direct purpose",
        "benchmark purpose",
    ]


def test_build_discovery_report_include_existing_keeps_existing(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "2401.00002.json").write_text("{}", encoding="utf-8")

    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[_paper("2401.00002", "Existing Paper", "direct")],
        topic_dir=tmp_path,
        include_existing=True,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert report.candidate_count == 1
    assert report.excluded_existing == []


def test_discovery_renderers_and_artifact_writes(tmp_path: Path) -> None:
    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[_paper("2401.00001", "First Paper", "direct")],
        topic_dir=tmp_path,
        include_existing=False,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    markdown = render_discovery_markdown(report, _topic())
    manifest = render_discovery_manifest_draft(report)
    paths = write_discovery_artifacts(tmp_path, report, _topic())

    assert "# Discovery Candidates: Utility Navigation" in markdown
    assert "| direct |" in markdown
    assert "First Paper" in markdown
    manifest_raw = yaml.safe_load(manifest)
    assert manifest_raw["papers"][0]["paper_id"] == "2401.00001"
    assert manifest_raw["papers"][0]["pdf_url"] == "https://arxiv.org/pdf/2401.00001"
    assert manifest_raw["papers"][0]["source_url"] == "https://arxiv.org/abs/2401.00001"
    assert manifest_raw["papers"][0]["venue"] == "arXiv"
    assert manifest_raw["papers"][0]["year"] == 2024
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["candidate_count"] == 1
    assert "First Paper" in paths["markdown"].read_text(encoding="utf-8")
    assert "pdf_url" in paths["manifest"].read_text(encoding="utf-8")
