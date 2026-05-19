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

    lines = []
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

    return "\n".join(lines).rstrip()


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
