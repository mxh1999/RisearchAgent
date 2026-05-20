from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from run import build_parser
from src.survey.arxiv_provider import convert_arxiv_result
from src.survey.models import TopicProfile, TopicQuery
from src.survey.topic_discover import (
    RawDiscoveryPaper,
    build_discovery_report,
    render_discovery_manifest_draft,
    render_discovery_markdown,
    write_discovery_artifacts,
)


class FakeDiscoveryProvider:
    def __init__(
        self,
        papers_by_query: dict[str, list[RawDiscoveryPaper]] | None = None,
        fail: bool = False,
    ):
        self.papers_by_query = papers_by_query or {}
        self.calls: list[tuple[str, str, str, int, str]] = []
        self.fail = fail

    async def search(
        self,
        query: str,
        query_name: str,
        query_purpose: str,
        max_results: int,
        sort: str,
    ) -> list[RawDiscoveryPaper]:
        self.calls.append((query, query_name, query_purpose, max_results, sort))
        if self.fail:
            raise RuntimeError("provider failed")
        return list(self.papers_by_query.get(query_name, []))


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


def _published_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _write_topic_yaml(topic_dir: Path, topic: TopicProfile | None = None) -> Path:
    topic = topic or _topic()
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        yaml.safe_dump(topic.to_dict(), sort_keys=False),
        encoding="utf-8",
    )
    return topic_path


def test_topic_discover_parser_accepts_all_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "topic",
            "discover",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--max-results-per-query",
            "7",
            "--sort",
            "relevance",
            "--days-lookback",
            "90",
            "--include-existing",
        ]
    )

    assert args.command == "topic"
    assert args.topic_command == "discover"
    assert args.topic == "data/topics/utility_nav/topic.yaml"
    assert args.max_results_per_query == 7
    assert args.sort == "relevance"
    assert args.days_lookback == 90
    assert args.include_existing is True


def test_topic_discover_parser_defaults_match_design() -> None:
    args = build_parser().parse_args(
        [
            "topic",
            "discover",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
        ]
    )

    assert args.max_results_per_query == 20
    assert args.sort == "submitted"
    assert args.days_lookback == 365
    assert args.include_existing is False


@pytest.mark.parametrize(
    "option,value",
    [
        ("--sort", "updated"),
        ("--max-results-per-query", "0"),
        ("--days-lookback", "0"),
    ],
)
def test_topic_discover_parser_rejects_invalid_options(option: str, value: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "topic",
                "discover",
                "--topic",
                "data/topics/utility_nav/topic.yaml",
                option,
                value,
            ]
        )


def test_cmd_topic_discover_writes_artifacts_and_calls_provider(
    tmp_path: Path,
) -> None:
    from src.survey.discover_cli import cmd_topic_discover

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic_yaml(topic_dir)
    provider = FakeDiscoveryProvider(
        {
            "direct": [
                _paper(
                    "2605.00001",
                    "Fresh Direct Paper",
                    "direct",
                    published=_published_days_ago(1),
                ),
                _paper(
                    "2301.00001",
                    "Stale Direct Paper",
                    "direct",
                    published="2023-01-01T00:00:00+00:00",
                ),
            ],
            "benchmark": [
                _paper(
                    "2605.00002",
                    "Fresh Benchmark Paper",
                    "benchmark",
                    published=_published_days_ago(2),
                )
            ],
        }
    )
    args = SimpleNamespace(
        topic=str(topic_path),
        max_results_per_query=5,
        sort="submitted",
        days_lookback=30,
        include_existing=False,
    )

    report = asyncio.run(cmd_topic_discover(args, provider=provider))

    assert provider.calls == [
        ('"utility" "navigation"', "direct", "Direct topic query.", 5, "submitted"),
        ('"GOAT-Bench" navigation', "benchmark", "Benchmark query.", 5, "submitted"),
    ]
    assert report.candidate_count == 2
    assert [candidate.paper_id for candidate in report.candidates] == [
        "2605.00001",
        "2605.00002",
    ]
    assert (topic_dir / "state" / "discovery_candidates.json").exists()
    assert (topic_dir / "discovery.md").exists()
    assert (topic_dir / "ingest_manifest.draft.yaml").exists()
    raw_report = json.loads(
        (topic_dir / "state" / "discovery_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    assert raw_report["candidate_count"] == 2


def test_cmd_topic_discover_rejects_empty_search_queries_before_provider(
    tmp_path: Path,
) -> None:
    from src.survey.discover_cli import cmd_topic_discover

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic_yaml(
        topic_dir,
        TopicProfile(
            topic_id="utility_nav",
            name="Utility Navigation",
            description="Task-conditioned utility over 3D memory.",
            intent="Find candidate papers.",
            search_queries=[],
        ),
    )
    provider = FakeDiscoveryProvider()
    args = SimpleNamespace(
        topic=str(topic_path),
        max_results_per_query=5,
        sort="submitted",
        days_lookback=30,
        include_existing=False,
    )

    with pytest.raises(SystemExit, match="search_queries"):
        asyncio.run(cmd_topic_discover(args, provider=provider))

    assert provider.calls == []


def test_cmd_topic_discover_provider_failure_writes_no_partial_artifacts(
    tmp_path: Path,
) -> None:
    from src.survey.discover_cli import cmd_topic_discover

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic_yaml(topic_dir)
    provider = FakeDiscoveryProvider(fail=True)
    args = SimpleNamespace(
        topic=str(topic_path),
        max_results_per_query=5,
        sort="submitted",
        days_lookback=30,
        include_existing=False,
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        asyncio.run(cmd_topic_discover(args, provider=provider))

    assert provider.calls
    assert not (topic_dir / "state" / "discovery_candidates.json").exists()
    assert not (topic_dir / "discovery.md").exists()
    assert not (topic_dir / "ingest_manifest.draft.yaml").exists()


def test_cmd_topic_discover_rejects_topic_id_mismatch_before_provider(
    tmp_path: Path,
) -> None:
    from src.survey.discover_cli import cmd_topic_discover

    topic_dir = tmp_path / "wrong_dir"
    topic_path = _write_topic_yaml(topic_dir)
    provider = FakeDiscoveryProvider()
    args = SimpleNamespace(
        topic=str(topic_path),
        max_results_per_query=5,
        sort="submitted",
        days_lookback=30,
        include_existing=False,
    )

    with pytest.raises(SystemExit, match="topic_id does not match"):
        asyncio.run(cmd_topic_discover(args, provider=provider))

    assert provider.calls == []


def test_convert_arxiv_result_to_raw_discovery_paper() -> None:
    result = SimpleNamespace(
        entry_id="https://arxiv.org/abs/2401.00001v2",
        title="  A Useful Paper  ",
        summary="\n  This paper studies useful behavior.  \n",
        authors=[
            SimpleNamespace(name="A. Researcher"),
            SimpleNamespace(name="B. Researcher"),
        ],
        published=datetime(2024, 1, 2, tzinfo=timezone.utc),
        categories=["cs.RO", "cs.CV"],
        pdf_url="https://arxiv.org/pdf/2401.00001v2",
    )

    paper = convert_arxiv_result(
        result,
        query_name="direct",
        query_purpose="Direct topic query.",
    )

    assert paper.arxiv_id == "2401.00001"
    assert paper.title == "A Useful Paper"
    assert paper.abstract == "This paper studies useful behavior."
    assert paper.authors == ["A. Researcher", "B. Researcher"]
    assert paper.published == datetime(2024, 1, 2, tzinfo=timezone.utc)
    assert paper.categories == ["cs.RO", "cs.CV"]
    assert paper.pdf_url == "https://arxiv.org/pdf/2401.00001"
    assert paper.source_url == "https://arxiv.org/abs/2401.00001"
    assert paper.query_name == "direct"
    assert paper.query_purpose == "Direct topic query."


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


def test_build_discovery_report_sorts_same_date_by_paper_id(tmp_path: Path) -> None:
    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[
            _paper("2401.00003", "Third Paper", "direct"),
            _paper("2401.00001", "First Paper", "direct"),
            _paper("2401.00002", "Second Paper", "direct"),
        ],
        topic_dir=tmp_path,
        include_existing=False,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert [candidate.paper_id for candidate in report.candidates] == [
        "2401.00001",
        "2401.00002",
        "2401.00003",
    ]


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
    assert "This paper studies utility for embodied navigation." in markdown
    assert "Abstract Preview" in markdown
    manifest_raw = yaml.safe_load(manifest)
    assert manifest_raw["papers"][0]["paper_id"] == "2401.00001"
    assert manifest_raw["papers"][0]["pdf_url"] == "https://arxiv.org/pdf/2401.00001"
    assert manifest_raw["papers"][0]["source_url"] == "https://arxiv.org/abs/2401.00001"
    assert manifest_raw["papers"][0]["venue"] == "arXiv"
    assert manifest_raw["papers"][0]["year"] == 2024
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["candidate_count"] == 1
    assert "First Paper" in paths["markdown"].read_text(encoding="utf-8")
    assert "pdf_url" in paths["manifest"].read_text(encoding="utf-8")
