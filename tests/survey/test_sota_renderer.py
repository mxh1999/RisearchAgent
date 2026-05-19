from __future__ import annotations

from src.survey.sota_models import (
    RawBenchmarkSetting,
    SettingGroup,
    SettingGroupRegistry,
    TopicSOTARecord,
)
from src.survey.sota_renderer import render_sota_markdown


def _record(
    record_id: str,
    method: str,
    value: float,
    setting: str = "val unseen",
    metric: str = "SPL",
    higher_is_better: bool = True,
    quote: str = "A very long quote about the reported benchmark value that should be truncated in the table because the full text is too verbose for a SOTA row.",
) -> TopicSOTARecord:
    return TopicSOTARecord(
        record_id=record_id,
        paper_id=record_id.split("::", 1)[0],
        title="Paper Title",
        benchmark="GOAT-Bench",
        setting=setting,
        metric=metric,
        method=method,
        value=value,
        higher_is_better=higher_is_better,
        source_page=8,
        source_section="Experiments",
        source_quote=quote,
        source_confidence="high",
    )


def _registry(confidence: str = "high") -> SettingGroupRegistry:
    return SettingGroupRegistry(
        groups=[
            SettingGroup(
                group_id="goat_bench_val_unseen",
                canonical_benchmark="GOAT-Bench",
                canonical_setting="val unseen, standard protocol",
                raw_benchmark_settings=[
                    RawBenchmarkSetting("GOAT-Bench", "val unseen"),
                    RawBenchmarkSetting("GOAT-Bench", "GOAT validation unseen split"),
                ],
                comparison_axes={"split": "val unseen"},
                confidence=confidence,
                rationale="Same benchmark split and protocol.",
            )
        ]
    )


def test_render_sota_markdown_sorts_higher_is_better_descending() -> None:
    markdown = render_sota_markdown(
        [
            _record(
                "paper-1::GOAT-Bench::val unseen::SPL::Baseline",
                "Baseline",
                25.0,
            ),
            _record(
                "paper-2::GOAT-Bench::GOAT validation unseen split::SPL::NewNav",
                "NewNav",
                35.1,
                setting="GOAT validation unseen split",
            ),
        ],
        _registry(),
    )

    assert "## GOAT-Bench" in markdown
    assert "### val unseen, standard protocol / SPL (higher is better)" in markdown
    assert markdown.index("| 1 | NewNav | 35.1 | `paper-2` |") < markdown.index(
        "| 2 | Baseline | 25.0 | `paper-1` |"
    )
    assert "raw setting: GOAT validation unseen split" in markdown
    assert "A very long quote about the reported benchmark value" in markdown
    assert "too verbose for a SOTA row" not in markdown


def test_render_sota_markdown_sorts_lower_is_better_ascending() -> None:
    markdown = render_sota_markdown(
        [
            _record(
                "paper-1::GOAT-Bench::val unseen::Error::SlowNav",
                "SlowNav",
                5.0,
                metric="Error",
                higher_is_better=False,
            ),
            _record(
                "paper-2::GOAT-Bench::val unseen::Error::FastNav",
                "FastNav",
                3.0,
                metric="Error",
                higher_is_better=False,
            ),
        ],
        _registry(),
    )

    assert "### val unseen, standard protocol / Error (lower is better)" in markdown
    assert markdown.index("| 1 | FastNav | 3.0 | `paper-2` |") < markdown.index(
        "| 2 | SlowNav | 5.0 | `paper-1` |"
    )


def test_render_sota_markdown_warns_for_uncertain_groups_and_direction_conflict() -> None:
    markdown = render_sota_markdown(
        [
            _record(
                "paper-1::GOAT-Bench::val unseen::SPL::Baseline",
                "Baseline",
                25.0,
                higher_is_better=True,
            ),
            _record(
                "paper-2::GOAT-Bench::val unseen::SPL::OtherNav",
                "OtherNav",
                20.0,
                higher_is_better=False,
            ),
        ],
        _registry(confidence="medium"),
    )

    assert "Warning: setting group confidence is medium" in markdown
    assert "Warning: mixed metric directions" in markdown
