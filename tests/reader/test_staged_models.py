from __future__ import annotations

import pytest

from src.reader.staged_models import (
    Evidence,
    ExperimentRecord,
    MethodModule,
    PaperReadingPackage,
    PageText,
    PaperSummary,
    TopicRelation,
)


def test_page_text_to_dict_round_trip() -> None:
    page = PageText(page=1, text="Abstract text", char_start=0, char_end=13)

    restored = PageText.from_dict(page.to_dict())

    assert restored == page


def test_reading_package_round_trip() -> None:
    package = PaperReadingPackage(
        paper_id="sample_paper",
        title="Sample Paper",
        source_path="paper/sample.pdf",
        pages=[PageText(page=1, text="Introduction text", char_start=0, char_end=17)],
        summary=PaperSummary(
            problem="The paper studies navigation decisions.",
            method="It scores candidate viewpoints.",
            takeaway="The key idea is learned utility over memory.",
            contributions=["Task-conditioned utility scoring"],
        ),
        claims=[
            Evidence(
                text="The method improves SPL.",
                page=7,
                section="Experiments",
                quote="Our method improves SPL by 5 points.",
                confidence="high",
            )
        ],
        method_modules=[
            MethodModule(
                name="Utility Head",
                role="Scores object and frontier candidates.",
                inputs=["3D memory", "goal embedding"],
                outputs=["candidate utility"],
            )
        ],
        experiments=[
            ExperimentRecord(
                benchmark="GOAT-Bench",
                setting="val unseen",
                metric="SPL",
                method="SampleNav",
                value=35.1,
                higher_is_better=True,
                result_kind="main_task",
                source=Evidence(
                    text="SPL result",
                    page=8,
                    section="Experiments",
                    quote="SampleNav obtains 35.1 SPL.",
                    confidence="high",
                ),
            )
        ],
        topic_relation=TopicRelation(
            relevance="core",
            concept_axes=["task_conditioned_utility"],
            collision_risk="medium",
            differentiation="Uses explicit utility rather than prompted reasoning.",
        ),
        critique=["Needs stronger baseline comparisons."],
        follow_up_questions=["How is utility supervised?"],
    )

    restored = PaperReadingPackage.from_dict(package.to_dict())

    assert restored == package
    assert restored.experiments[0].source.page == 8


def test_experiment_record_from_dict_preserves_false_metric_direction() -> None:
    raw = {
        "benchmark": "GOAT-Bench",
        "setting": "val unseen",
        "metric": "Error",
        "method": "SampleNav",
        "value": 12.3,
        "higher_is_better": False,
        "source": {
            "text": "Error result",
            "page": 8,
            "section": "Experiments",
            "quote": "SampleNav obtains 12.3 error.",
            "confidence": "high",
        },
    }

    restored = ExperimentRecord.from_dict(raw)

    assert restored.higher_is_better is False
    assert restored.result_kind == "main_task"


def test_experiment_record_round_trip_preserves_result_kind() -> None:
    raw = {
        "benchmark": "Map Completion Test Dataset",
        "setting": "MP3D validation",
        "metric": "IoU",
        "method": "SampleNav",
        "value": 41.2,
        "higher_is_better": True,
        "result_kind": "auxiliary",
        "source": {
            "text": "Map completion result",
            "page": 8,
            "section": "Experiments",
            "quote": "SampleNav obtains 41.2 IoU.",
            "confidence": "high",
        },
    }

    restored = ExperimentRecord.from_dict(raw)

    assert restored.result_kind == "auxiliary"
    assert restored.to_dict()["result_kind"] == "auxiliary"


def test_experiment_record_from_dict_parses_false_string_metric_direction() -> None:
    raw = {
        "benchmark": "GOAT-Bench",
        "setting": "val unseen",
        "metric": "Error",
        "method": "SampleNav",
        "value": 12.3,
        "higher_is_better": "false",
        "source": {
            "text": "Error result",
            "page": 8,
            "section": "Experiments",
            "quote": "SampleNav obtains 12.3 error.",
            "confidence": "high",
        },
    }

    restored = ExperimentRecord.from_dict(raw)

    assert restored.higher_is_better is False


def test_experiment_record_from_dict_rejects_invalid_metric_direction() -> None:
    raw = {
        "benchmark": "GOAT-Bench",
        "setting": "val unseen",
        "metric": "SPL",
        "method": "SampleNav",
        "value": 35.1,
        "higher_is_better": "sometimes",
        "source": {
            "text": "SPL result",
            "page": 8,
            "section": "Experiments",
            "quote": "SampleNav obtains 35.1 SPL.",
            "confidence": "high",
        },
    }

    with pytest.raises(ValueError):
        ExperimentRecord.from_dict(raw)
