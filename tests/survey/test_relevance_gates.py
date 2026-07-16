from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from run import build_parser
from src.reader.staged_models import PaperReadingPackage, PaperSummary, TopicRelation
from src.survey.topic_update import load_topic_update_context


class FakeRelevanceLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.prompts.append(prompt)
        if "Cobb-Douglas" in prompt or "Fractional Production" in prompt:
            return {
                "decision": "reject",
                "score": 0.05,
                "reason": "The paper is about economic production functions, not embodied navigation.",
                "matched_topic_aspects": [],
                "missing_topic_aspects": ["embodied navigation", "3D memory"],
            }
        return {
            "decision": "accept",
            "score": 0.91,
            "reason": "The paper studies embodied navigation with memory and task-conditioned decisions.",
            "matched_topic_aspects": ["embodied navigation", "memory"],
            "missing_topic_aspects": [],
        }


def _write_topic(topic_dir: Path) -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            """
            topic_id: utility_nav
            name: Utility Navigation
            description: Task-conditioned utility estimation for embodied navigation and memory.
            intent: Build a focused reading set.
            concept_axes:
              - name: embodied navigation
                description: Navigation in embodied 3D environments.
            scope:
              positive:
                - embodied navigation
                - spatial memory
              negative:
                - economics
                - production functions
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


def _candidate(
    paper_id: str,
    title: str,
    abstract: str,
    status: str = "candidate",
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "arxiv_id": paper_id,
        "title": title,
        "abstract": abstract,
        "authors": ["A. Researcher"],
        "published": "2026-05-21",
        "year": 2026,
        "categories": ["cs.RO"],
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        "source_url": f"https://arxiv.org/abs/{paper_id}",
        "matched_queries": ["direct"],
        "query_rationales": ["Direct query"],
        "status": status,
    }


def _write_discovery(topic_dir: Path) -> Path:
    state_dir = topic_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "discovery_candidates.json"
    path.write_text(
        json.dumps(
            {
                "topic_id": "utility_nav",
                "topic_name": "Utility Navigation",
                "source": "arxiv",
                "generated_at": "2026-05-21T00:00:00+00:00",
                "query_count": 1,
                "candidate_count": 2,
                "excluded_existing": [],
                "candidates": [
                    _candidate(
                        "2605.00001",
                        "Embodied Navigation Memory",
                        "We study memory for embodied navigation agents in 3D environments.",
                    ),
                    _candidate(
                        "2605.00002",
                        "Caputo-Type Memory Invariants: A Fractional Production Function",
                        "This paper studies Cobb-Douglas production functions with memory.",
                    ),
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_package(topic_dir: Path, package: PaperReadingPackage) -> None:
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / f"{package.paper_id}.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )


def _package(paper_id: str, title: str) -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation agents need memory.",
            method="Uses spatial memory for task-conditioned decisions.",
            takeaway="Relevant to embodied navigation memory.",
            contributions=["Memory-based embodied navigation"],
        ),
        topic_relation=TopicRelation(
            relevance="core",
            concept_axes=["embodied navigation"],
            collision_risk="low",
            differentiation="Uses spatial memory.",
        ),
    )


def test_screen_discovery_candidates_updates_statuses_and_artifacts(
    tmp_path: Path,
) -> None:
    from src.survey.relevance import screen_discovery_candidates

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    candidates_path = _write_discovery(topic_dir)
    llm = FakeRelevanceLLM()

    report = asyncio.run(
        screen_discovery_candidates(
            topic_path=topic_path,
            candidates_path=candidates_path,
            threshold=0.6,
            limit=None,
            dry_run=False,
            llm=llm,
            model="fake-model",
        )
    )

    raw = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert report.accepted == ["2605.00001"]
    assert report.rejected == ["2605.00002"]
    assert [candidate["status"] for candidate in raw["candidates"]] == [
        "candidate",
        "rejected",
    ]
    assert raw["candidates"][0]["relevance"]["decision"] == "accept"
    assert raw["candidates"][1]["relevance"]["decision"] == "reject"
    assert "2605.00001" in (topic_dir / "ingest_manifest.draft.yaml").read_text(
        encoding="utf-8"
    )
    assert "2605.00002" not in (topic_dir / "ingest_manifest.draft.yaml").read_text(
        encoding="utf-8"
    )
    assert "rejected" in (topic_dir / "discovery.md").read_text(encoding="utf-8")
    assert (topic_dir / "state" / "screening_report.json").exists()
    assert len(llm.prompts) == 2


def test_screen_discovery_candidates_dry_run_leaves_candidates_unchanged(
    tmp_path: Path,
) -> None:
    from src.survey.relevance import screen_discovery_candidates

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    candidates_path = _write_discovery(topic_dir)
    before = candidates_path.read_text(encoding="utf-8")

    report = asyncio.run(
        screen_discovery_candidates(
            topic_path=topic_path,
            candidates_path=candidates_path,
            threshold=0.6,
            limit=1,
            dry_run=True,
            llm=FakeRelevanceLLM(),
            model=None,
        )
    )

    assert report.accepted == ["2605.00001"]
    assert candidates_path.read_text(encoding="utf-8") == before
    assert (topic_dir / "state" / "screening_report.json").exists()


def test_validate_reading_packages_writes_report(tmp_path: Path) -> None:
    from src.survey.relevance import validate_reading_packages

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir, _package("mtu3d", "Embodied Navigation Memory"))
    _write_package(topic_dir, _package("econ", "Cobb-Douglas Memory Function"))

    report = asyncio.run(
        validate_reading_packages(
            topic_path=topic_path,
            readings_dir=None,
            threshold=0.6,
            limit=None,
            dry_run=False,
            llm=FakeRelevanceLLM(),
            model="fake-model",
        )
    )

    assert report.included == ["mtu3d"]
    assert report.excluded == ["econ"]
    raw = json.loads(
        (topic_dir / "state" / "relevance_validations.json").read_text(
            encoding="utf-8"
        )
    )
    assert [item["paper_id"] for item in raw["decisions"]] == ["econ", "mtu3d"]
    assert {item["paper_id"]: item["include"] for item in raw["decisions"]} == {
        "econ": False,
        "mtu3d": True,
    }


def test_validate_reading_packages_dry_run_does_not_change_update_filtering(
    tmp_path: Path,
) -> None:
    from src.survey.relevance import validate_reading_packages

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir, _package("mtu3d", "Embodied Navigation Memory"))
    _write_package(topic_dir, _package("econ", "Cobb-Douglas Memory Function"))

    report = asyncio.run(
        validate_reading_packages(
            topic_path=topic_path,
            readings_dir=None,
            threshold=0.6,
            limit=None,
            dry_run=True,
            llm=FakeRelevanceLLM(),
            model=None,
        )
    )
    context = load_topic_update_context(topic_path, None)

    assert report.excluded == ["econ"]
    assert not (topic_dir / "state" / "relevance_validations.json").exists()
    assert (topic_dir / "state" / "relevance_validations.dry_run.json").exists()
    assert [package.paper_id for package in context.packages] == ["econ", "mtu3d"]


def test_topic_update_context_filters_rejected_validation(tmp_path: Path) -> None:
    from src.survey.relevance import validate_reading_packages

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir, _package("mtu3d", "Embodied Navigation Memory"))
    _write_package(topic_dir, _package("econ", "Cobb-Douglas Memory Function"))
    asyncio.run(
        validate_reading_packages(
            topic_path=topic_path,
            readings_dir=None,
            threshold=0.6,
            limit=None,
            dry_run=False,
            llm=FakeRelevanceLLM(),
            model=None,
        )
    )

    context = load_topic_update_context(topic_path, None)

    assert [package.paper_id for package in context.packages] == ["mtu3d"]


def test_topic_screen_and_validate_parsers_accept_options() -> None:
    screen_args = build_parser().parse_args(
        [
            "topic",
            "screen",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--candidates",
            "candidates.json",
            "--threshold",
            "0.7",
            "--limit",
            "3",
            "--dry-run",
            "--model",
            "gemini-test",
        ]
    )
    validate_args = build_parser().parse_args(
        [
            "topic",
            "validate",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--readings-dir",
            "papers",
            "--threshold",
            "0.7",
        ]
    )

    assert screen_args.topic_command == "screen"
    assert screen_args.candidates == "candidates.json"
    assert screen_args.threshold == 0.7
    assert screen_args.limit == 3
    assert screen_args.dry_run is True
    assert screen_args.model == "gemini-test"
    assert validate_args.topic_command == "validate"
    assert validate_args.readings_dir == "papers"
    assert validate_args.threshold == 0.7


@pytest.mark.parametrize(
    "argv",
    [
        [
            "topic",
            "screen",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--threshold",
            "0",
        ],
        [
            "topic",
            "validate",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--threshold",
            "1.2",
        ],
        [
            "topic",
            "screen",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--limit",
            "0",
        ],
    ],
)
def test_topic_relevance_parsers_reject_invalid_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_cmd_topic_screen_reports_local_errors_before_llm(tmp_path: Path) -> None:
    from src.survey import relevance_cli

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    args = SimpleNamespace(
        config="config.yaml",
        topic=str(topic_path),
        candidates=None,
        threshold=0.6,
        limit=None,
        dry_run=False,
        model=None,
    )

    with pytest.raises(SystemExit, match="discovery candidates"):
        asyncio.run(
            relevance_cli.cmd_topic_screen(
                args,
                llm=FakeRelevanceLLM(),
            )
        )
