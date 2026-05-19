from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from typing import Any, Optional

import pytest

from src.reader.staged_models import Evidence, ExperimentRecord, PaperReadingPackage
from src.survey.models import TopicProfile
from src.survey.topic_update import (
    TopicUpdateStepReport,
    build_preflight_report,
    update_topic_artifacts,
    validate_topic_update_options,
    write_topic_update_report,
)


class FakeSurveyLLM:
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        return {
            "taxonomy": [
                {
                    "name": "Explicit utility",
                    "description": "Score candidate actions.",
                    "paper_ids": ["mtu3d", "msgnav"],
                    "key_distinction": "Uses decision scores.",
                }
            ],
            "paper_map": [
                {
                    "paper_id": "mtu3d",
                    "title": "Paper mtu3d",
                    "role": "core",
                    "rationale": "Has experiment records.",
                    "evidence": "Candidate scoring.",
                },
                {
                    "paper_id": "msgnav",
                    "title": "Paper msgnav",
                    "role": "adjacent",
                    "rationale": "Scene graph navigation.",
                    "evidence": "VLM reasoning.",
                },
            ],
            "positioning": {
                "thesis_gap": "General utility over 3D memory.",
                "novelty_claim": "Explicit utility over richer primitives.",
                "collision_risks": ["MTU3D overlap."],
                "recommended_positioning": "Generalize utility learning.",
            },
            "references": [
                {
                    "paper_id": "mtu3d",
                    "title": "Paper mtu3d",
                    "why_relevant": "Core.",
                    "evidence": "Candidate scoring.",
                },
                {
                    "paper_id": "msgnav",
                    "title": "Paper msgnav",
                    "why_relevant": "Adjacent.",
                    "evidence": "VLM reasoning.",
                },
            ],
            "open_questions": ["How is utility supervised?"],
        }


class FakeSOTALLM:
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        return {
            "action": "create_new",
            "canonical_benchmark": "GOAT-Bench",
            "canonical_setting": "val unseen",
            "comparison_axes": {"split": "val unseen"},
            "confidence": "high",
            "rationale": "Standard split.",
        }


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


def _write_topic(topic_dir: Path) -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            """
            # Preserve this note.
            topic_id: utility_nav
            name: Utility Navigation
            description: Task-conditioned utility over 3D memory.
            intent: Maintain topic artifacts.
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


def _write_package(topic_dir: Path, package: PaperReadingPackage) -> None:
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / f"{package.paper_id}.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
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


def test_update_topic_artifacts_runs_survey_and_sota(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    original_yaml = topic_path.read_text(encoding="utf-8")
    _write_package(topic_dir, _package("mtu3d", has_experiments=True))
    _write_package(topic_dir, _package("msgnav", has_experiments=False))
    (topic_dir / "survey.md").write_text(
        "# Utility Navigation Survey\n\nManual survey note.\n\n"
        "<!-- BEGIN AUTO:taxonomy -->\nOld taxonomy\n<!-- END AUTO:taxonomy -->\n",
        encoding="utf-8",
    )
    (topic_dir / "sota.md").write_text(
        "# Utility Navigation SOTA\n\nManual SOTA note.\n\n"
        "<!-- BEGIN AUTO:sota -->\nOld SOTA\n<!-- END AUTO:sota -->\n",
        encoding="utf-8",
    )

    report = asyncio.run(
        update_topic_artifacts(
            topic_path=topic_path,
            readings_dir=None,
            survey_llm=FakeSurveyLLM(),
            survey_model="survey-model",
            sota_llm=FakeSOTALLM(),
            sota_model="sota-model",
            skip_survey=False,
            skip_sota=False,
            use_sota_llm=True,
        )
    )

    assert topic_path.read_text(encoding="utf-8") == original_yaml
    survey_md = (topic_dir / "survey.md").read_text(encoding="utf-8")
    sota_md = (topic_dir / "sota.md").read_text(encoding="utf-8")
    report_json = json.loads(
        (topic_dir / "state" / "topic_update_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert "Manual survey note." in survey_md
    assert "Old taxonomy" not in survey_md
    assert "Explicit utility" in survey_md
    assert "Manual SOTA note." in sota_md
    assert "Old SOTA" not in sota_md
    assert "SampleNav" in sota_md
    assert report.survey.status == "updated"
    assert report.sota.status == "updated"
    assert report.paper_count == 2
    assert report.papers_without_experiments == ["msgnav"]
    assert report_json["survey"]["status"] == "updated"
    assert report_json["sota"]["record_count"] == 1


def test_update_topic_artifacts_skip_survey_does_not_create_survey_files(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir, _package("mtu3d", has_experiments=True))
    _write_package(topic_dir, _package("msgnav", has_experiments=False))

    report = asyncio.run(
        update_topic_artifacts(
            topic_path=topic_path,
            readings_dir=None,
            survey_llm=None,
            survey_model=None,
            sota_llm=None,
            sota_model=None,
            skip_survey=True,
            skip_sota=False,
            use_sota_llm=False,
        )
    )

    assert report.survey.status == "skipped"
    assert report.sota.status == "updated"
    assert not (topic_dir / "survey.md").exists()
    assert (topic_dir / "sota.md").exists()


def test_update_topic_artifacts_skip_sota_does_not_create_sota_files(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir, _package("mtu3d", has_experiments=True))
    _write_package(topic_dir, _package("msgnav", has_experiments=False))

    report = asyncio.run(
        update_topic_artifacts(
            topic_path=topic_path,
            readings_dir=None,
            survey_llm=FakeSurveyLLM(),
            survey_model="survey-model",
            sota_llm=None,
            sota_model=None,
            skip_survey=False,
            skip_sota=True,
            use_sota_llm=False,
        )
    )

    assert report.survey.status == "updated"
    assert report.sota.status == "skipped"
    assert (topic_dir / "survey.md").exists()
    assert not (topic_dir / "sota.md").exists()
    update_topic_artifacts,
