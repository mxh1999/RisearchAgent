from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reader.staged_models import Evidence, ExperimentRecord, PaperReadingPackage
from src.survey.models import TopicProfile
from src.survey.topic_update import (
    TopicUpdateStepReport,
    build_preflight_report,
    validate_topic_update_options,
    write_topic_update_report,
)


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Maintain topic artifacts.",
    )


def _package(paper_id: str, has_experiments: bool) -> PaperReadingPackage:
    experiments = []
    if has_experiments:
        experiments.append(
            ExperimentRecord(
                benchmark="GOAT-Bench",
                setting="val unseen",
                metric="SPL",
                method="SampleNav",
                value=35.1,
                higher_is_better=True,
                source=Evidence(
                    text="SPL result",
                    page=8,
                    section="Experiments",
                    quote="SampleNav obtains 35.1 SPL.",
                    confidence="high",
                ),
            )
        )
    return PaperReadingPackage(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        source_path=f"{paper_id}.pdf",
        experiments=experiments,
    )


def test_preflight_report_counts_experiment_coverage(tmp_path: Path) -> None:
    report = build_preflight_report(
        topic=_topic(),
        readings_dir=tmp_path / "papers",
        packages=[
            _package("mtu3d", has_experiments=True),
            _package("msgnav", has_experiments=False),
        ],
    )

    assert report.topic_id == "utility_nav"
    assert report.paper_count == 2
    assert report.paper_ids == ["mtu3d", "msgnav"]
    assert report.papers_with_experiments == ["mtu3d"]
    assert report.papers_without_experiments == ["msgnav"]
    assert report.survey.status == "pending"
    assert report.sota.status == "pending"
    assert report.warnings == ["1 paper has no experiment records: msgnav"]


def test_write_topic_update_report_json(tmp_path: Path) -> None:
    report = build_preflight_report(
        topic=_topic(),
        readings_dir=tmp_path / "papers",
        packages=[_package("mtu3d", has_experiments=True)],
    )
    report.survey = TopicUpdateStepReport(
        status="updated",
        artifacts=["survey.md"],
    )

    path = write_topic_update_report(tmp_path / "utility_nav", report)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert path == tmp_path / "utility_nav" / "state" / "topic_update_report.json"
    assert raw["topic_id"] == "utility_nav"
    assert raw["survey"]["status"] == "updated"
    assert raw["survey"]["artifacts"] == ["survey.md"]


def test_validate_topic_update_options_rejects_both_skips() -> None:
    with pytest.raises(ValueError, match="cannot skip both"):
        validate_topic_update_options(skip_survey=True, skip_sota=True)
