from __future__ import annotations

from src.reader.staged_models import Evidence, ExperimentRecord, PaperReadingPackage
from src.survey.sota_models import (
    TopicSOTARecord,
    collect_sota_records,
    records_from_jsonl,
    records_to_jsonl,
    sort_sota_records,
)


def _evidence(quote: str = "SampleNav obtains 35.1 SPL.") -> Evidence:
    return Evidence(
        text="SPL result",
        page=8,
        section="Experiments",
        quote=quote,
        confidence="high",
    )


def _package(
    paper_id: str,
    title: str,
    experiments: list[ExperimentRecord],
) -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"{paper_id}.pdf",
        experiments=experiments,
    )


def _experiment(
    benchmark: str,
    setting: str,
    metric: str,
    method: str,
    value: float,
    higher_is_better: bool = True,
) -> ExperimentRecord:
    return ExperimentRecord(
        benchmark=benchmark,
        setting=setting,
        metric=metric,
        method=method,
        value=value,
        higher_is_better=higher_is_better,
        source=_evidence(f"{method} obtains {value} {metric}."),
    )


def test_collect_sota_records_normalizes_text_fields() -> None:
    package = _package(
        "paper-1",
        "Paper One",
        [
            _experiment(
                benchmark="  GOAT-Bench   ",
                setting=" ",
                metric="  SPL  ",
                method="  SampleNav  ",
                value=35.1,
            )
        ],
    )

    records = collect_sota_records([package])

    assert records == [
        TopicSOTARecord(
            paper_id="paper-1",
            title="Paper One",
            benchmark="GOAT-Bench",
            setting="N/A",
            metric="SPL",
            method="SampleNav",
            value=35.1,
            higher_is_better=True,
            source_page=8,
            source_section="Experiments",
            source_quote="SampleNav obtains 35.1 SPL.",
            source_confidence="high",
        )
    ]


def test_sort_sota_records_respects_metric_direction() -> None:
    high_better = [
        TopicSOTARecord(
            paper_id="b",
            title="B",
            benchmark="GOAT-Bench",
            setting="val",
            metric="SPL",
            method="Beta",
            value=30.0,
            higher_is_better=True,
            source_page=1,
            source_section="Results",
            source_quote="Beta result.",
            source_confidence="medium",
        ),
        TopicSOTARecord(
            paper_id="a",
            title="A",
            benchmark="GOAT-Bench",
            setting="val",
            metric="SPL",
            method="Alpha",
            value=40.0,
            higher_is_better=True,
            source_page=1,
            source_section="Results",
            source_quote="Alpha result.",
            source_confidence="medium",
        ),
    ]
    low_better = [
        TopicSOTARecord(
            paper_id="d",
            title="D",
            benchmark="GOAT-Bench",
            setting="val",
            metric="Error",
            method="Delta",
            value=4.0,
            higher_is_better=False,
            source_page=1,
            source_section="Results",
            source_quote="Delta result.",
            source_confidence="medium",
        ),
        TopicSOTARecord(
            paper_id="c",
            title="C",
            benchmark="GOAT-Bench",
            setting="val",
            metric="Error",
            method="Gamma",
            value=3.0,
            higher_is_better=False,
            source_page=1,
            source_section="Results",
            source_quote="Gamma result.",
            source_confidence="medium",
        ),
    ]

    sorted_records = sort_sota_records(high_better + low_better)

    assert [record.method for record in sorted_records] == [
        "Gamma",
        "Delta",
        "Alpha",
        "Beta",
    ]


def test_records_jsonl_round_trip_preserves_evidence() -> None:
    records = collect_sota_records(
        [
            _package(
                "paper-1",
                "Paper One",
                [_experiment("GOAT-Bench", "val unseen", "SPL", "SampleNav", 35.1)],
            )
        ]
    )

    restored = records_from_jsonl(records_to_jsonl(records))

    assert restored == records
    assert restored[0].source_quote == "SampleNav obtains 35.1 SPL."
