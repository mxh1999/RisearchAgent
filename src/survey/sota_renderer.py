from __future__ import annotations

from collections import defaultdict

from src.survey.sota_models import (
    RawBenchmarkSetting,
    SettingGroup,
    SettingGroupRegistry,
    TopicSOTARecord,
)


def render_sota_markdown(
    records: list[TopicSOTARecord],
    registry: SettingGroupRegistry,
) -> str:
    if not records:
        return "No experiment records have been extracted yet."

    main_records = [
        record for record in records if _is_main_result(record)
    ]
    auxiliary_records = [
        record for record in records if not _is_main_result(record)
    ]

    lines = []
    if main_records:
        lines.extend(_render_main_leaderboards(main_records, registry))
    else:
        lines.append("No main-task SOTA records have been extracted yet.")

    if auxiliary_records:
        if lines:
            lines.append("")
        lines.extend(_render_auxiliary_records(auxiliary_records))

    return "\n".join(lines).rstrip()


def _render_main_leaderboards(
    records: list[TopicSOTARecord],
    registry: SettingGroupRegistry,
) -> list[str]:
    group_by_raw = _group_lookup(registry)
    grouped: dict[tuple[str, str, str], list[TopicSOTARecord]] = defaultdict(list)
    group_for_key: dict[tuple[str, str, str], SettingGroup] = {}
    for record in records:
        group = group_by_raw.get(
            RawBenchmarkSetting(record.benchmark, record.setting),
            _fallback_group(record),
        )
        key = (group.canonical_benchmark, group.canonical_setting, record.metric)
        grouped[key].append(record)
        group_for_key[key] = group

    lines: list[str] = []
    current_benchmark = None
    for key in sorted(grouped.keys(), key=lambda item: (item[0].lower(), item[1].lower(), item[2].lower())):
        benchmark, setting, metric = key
        if benchmark != current_benchmark:
            if lines:
                lines.append("")
            lines.append(f"## {benchmark}")
            current_benchmark = benchmark

        group = group_for_key[key]
        table_records = _sort_table_records(grouped[key])
        direction = _direction_label(table_records)
        lines.extend(
            [
                "",
                f"### {setting} / {metric} ({direction})",
            ]
        )
        if group.confidence != "high":
            lines.append(
                f"Warning: setting group confidence is {group.confidence}. {group.rationale}"
            )
        if _has_direction_conflict(table_records):
            lines.append(
                "Warning: mixed metric directions were reported for this table; verify comparability before citing ranks."
            )
        lines.extend(
            [
                "",
                "| Rank | Method | Value | Paper | Evidence |",
                "|---:|---|---:|---|---|",
            ]
        )
        for rank, record in enumerate(table_records, start=1):
            lines.append(
                "| {rank} | {method} | {value} | `{paper_id}` | {evidence} |".format(
                    rank=rank,
                    method=_escape_cell(record.method),
                    value=_format_value(record.value),
                    paper_id=_escape_cell(record.paper_id),
                    evidence=_escape_cell(_evidence_text(record)),
                )
            )

    return lines


def _render_auxiliary_records(records: list[TopicSOTARecord]) -> list[str]:
    lines = [
        "## Auxiliary / Diagnostic Results",
        "",
        "| Kind | Benchmark | Setting | Metric | Method | Value | Paper | Evidence |",
        "|---|---|---|---|---|---:|---|---|",
    ]
    for record in sorted(
        records,
        key=lambda item: (
            item.result_kind.lower(),
            item.benchmark.lower(),
            item.setting.lower(),
            item.metric.lower(),
            item.method.lower(),
            item.paper_id.lower(),
        ),
    ):
        lines.append(
            "| {kind} | {benchmark} | {setting} | {metric} | {method} | {value} | `{paper}` | {evidence} |".format(
                kind=_escape_cell(record.result_kind),
                benchmark=_escape_cell(record.benchmark),
                setting=_escape_cell(record.setting),
                metric=_escape_cell(record.metric),
                method=_escape_cell(record.method),
                value=_format_value(record.value),
                paper=_escape_cell(record.paper_id),
                evidence=_escape_cell(_evidence_text(record)),
            )
        )
    return lines


def _group_lookup(
    registry: SettingGroupRegistry,
) -> dict[RawBenchmarkSetting, SettingGroup]:
    lookup = {}
    for group in registry.groups:
        for raw_setting in group.raw_benchmark_settings:
            lookup[raw_setting] = group
    return lookup


def _fallback_group(record: TopicSOTARecord) -> SettingGroup:
    raw_setting = RawBenchmarkSetting(record.benchmark, record.setting)
    return SettingGroup(
        group_id=record.record_id,
        canonical_benchmark=record.benchmark,
        canonical_setting=record.setting,
        raw_benchmark_settings=[raw_setting],
        comparison_axes={},
        confidence="low",
        rationale="No setting group was found for this raw setting.",
    )


def _sort_table_records(records: list[TopicSOTARecord]) -> list[TopicSOTARecord]:
    higher_count = sum(1 for record in records if record.higher_is_better)
    lower_count = len(records) - higher_count
    higher_is_better = higher_count >= lower_count
    return sorted(
        records,
        key=lambda record: (
            -record.value if higher_is_better else record.value,
            record.method.lower(),
            record.paper_id.lower(),
        ),
    )


def _direction_label(records: list[TopicSOTARecord]) -> str:
    higher_count = sum(1 for record in records if record.higher_is_better)
    lower_count = len(records) - higher_count
    return "higher is better" if higher_count >= lower_count else "lower is better"


def _has_direction_conflict(records: list[TopicSOTARecord]) -> bool:
    return len({record.higher_is_better for record in records}) > 1


def _is_main_result(record: TopicSOTARecord) -> bool:
    return record.result_kind.strip().lower() == "main_task"


def _evidence_text(record: TopicSOTARecord) -> str:
    quote = _truncate(record.source_quote, limit=96)
    return (
        f"raw setting: {record.setting}; "
        f"p.{record.source_page}, {record.source_section}: \"{quote}\""
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_value(value: float) -> str:
    return str(value)


def _escape_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")
