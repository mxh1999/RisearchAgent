from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from src.reader.staged_models import PaperReadingPackage


@dataclass(frozen=True)
class RawBenchmarkSetting:
    benchmark: str
    setting: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RawBenchmarkSetting":
        return cls(
            benchmark=str(raw["benchmark"]),
            setting=str(raw["setting"]),
        )


@dataclass(frozen=True)
class SettingGroup:
    group_id: str
    canonical_benchmark: str
    canonical_setting: str
    raw_benchmark_settings: list[RawBenchmarkSetting]
    comparison_axes: dict[str, str]
    confidence: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "canonical_benchmark": self.canonical_benchmark,
            "canonical_setting": self.canonical_setting,
            "raw_benchmark_settings": [
                raw_setting.to_dict()
                for raw_setting in self.raw_benchmark_settings
            ],
            "comparison_axes": dict(self.comparison_axes),
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SettingGroup":
        return cls(
            group_id=str(raw["group_id"]),
            canonical_benchmark=str(raw["canonical_benchmark"]),
            canonical_setting=str(raw["canonical_setting"]),
            raw_benchmark_settings=[
                RawBenchmarkSetting.from_dict(item)
                for item in raw.get("raw_benchmark_settings", [])
            ],
            comparison_axes={
                str(key): str(value)
                for key, value in raw.get("comparison_axes", {}).items()
            },
            confidence=str(raw["confidence"]),
            rationale=str(raw["rationale"]),
        )


@dataclass(frozen=True)
class SettingGroupRegistry:
    groups: list[SettingGroup]

    def to_dict(self) -> dict[str, Any]:
        return {"groups": [group.to_dict() for group in self.groups]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SettingGroupRegistry":
        groups = [
            SettingGroup.from_dict(item)
            for item in raw.get("groups", [])
        ]
        _validate_registry(groups)
        return cls(groups=groups)


@dataclass(frozen=True)
class TopicSOTARecord:
    record_id: str
    paper_id: str
    title: str
    benchmark: str
    setting: str
    metric: str
    method: str
    value: float
    higher_is_better: bool
    source_page: int
    source_section: str
    source_quote: str
    source_confidence: str
    result_kind: str = "main_task"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TopicSOTARecord":
        return cls(
            record_id=str(raw["record_id"]),
            paper_id=str(raw["paper_id"]),
            title=str(raw["title"]),
            benchmark=str(raw["benchmark"]),
            setting=str(raw["setting"]),
            metric=str(raw["metric"]),
            method=str(raw["method"]),
            value=float(raw["value"]),
            higher_is_better=_parse_bool(raw["higher_is_better"]),
            source_page=int(raw["source_page"]),
            source_section=str(raw["source_section"]),
            source_quote=str(raw["source_quote"]),
            source_confidence=str(raw["source_confidence"]),
            result_kind=str(raw.get("result_kind", "main_task")),
        )


def collect_sota_records(
    packages: list[PaperReadingPackage],
) -> list[TopicSOTARecord]:
    records = []
    for package in packages:
        for experiment in package.experiments:
            benchmark = _normalize_text(experiment.benchmark)
            setting = _normalize_text(experiment.setting, default="N/A")
            metric = _normalize_text(experiment.metric)
            method = _normalize_text(experiment.method)
            records.append(
                TopicSOTARecord(
                    record_id=_make_record_id(
                        package.paper_id,
                        benchmark,
                        setting,
                        metric,
                        method,
                    ),
                    paper_id=package.paper_id,
                    title=package.title,
                    benchmark=benchmark,
                    setting=setting,
                    metric=metric,
                    method=method,
                    value=experiment.value,
                    higher_is_better=experiment.higher_is_better,
                    source_page=experiment.source.page,
                    source_section=_normalize_text(experiment.source.section),
                    source_quote=_normalize_text(experiment.source.quote),
                    source_confidence=_normalize_text(experiment.source.confidence),
                    result_kind=_normalize_text(
                        experiment.result_kind,
                        default="main_task",
                    ),
                )
            )
    return sort_sota_records(records)


def sort_sota_records(records: list[TopicSOTARecord]) -> list[TopicSOTARecord]:
    return sorted(records, key=_record_sort_key)


def records_to_jsonl(records: list[TopicSOTARecord]) -> str:
    lines = [
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
        for record in records
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def records_from_jsonl(text: str) -> list[TopicSOTARecord]:
    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("SOTA record JSONL line must be an object")
        records.append(TopicSOTARecord.from_dict(raw))
    return records


def setting_registry_to_json(registry: SettingGroupRegistry) -> str:
    return json.dumps(registry.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def setting_registry_from_json(text: str) -> SettingGroupRegistry:
    if not text.strip():
        return SettingGroupRegistry(groups=[])
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("Setting group registry must be a JSON object")
    return SettingGroupRegistry.from_dict(raw)


def _validate_registry(groups: list[SettingGroup]) -> None:
    seen_group_ids: set[str] = set()
    seen_raw_settings: set[RawBenchmarkSetting] = set()
    for group in groups:
        if group.group_id in seen_group_ids:
            raise ValueError(f"Duplicate setting group id: {group.group_id}")
        seen_group_ids.add(group.group_id)
        for raw_setting in group.raw_benchmark_settings:
            if raw_setting in seen_raw_settings:
                raise ValueError(
                    "Duplicate raw benchmark setting in SOTA registry: "
                    f"{raw_setting.benchmark} / {raw_setting.setting}"
                )
            seen_raw_settings.add(raw_setting)


def _record_sort_key(record: TopicSOTARecord) -> tuple[Any, ...]:
    value_key = -record.value if record.higher_is_better else record.value
    return (
        record.benchmark.lower(),
        record.setting.lower(),
        record.metric.lower(),
        value_key,
        record.method.lower(),
        record.paper_id.lower(),
    )


def _make_record_id(
    paper_id: str,
    benchmark: str,
    setting: str,
    metric: str,
    method: str,
) -> str:
    return "::".join([paper_id, benchmark, setting, metric, method])


def _normalize_text(raw: str, default: str = "") -> str:
    normalized = re.sub(r"\s+", " ", str(raw)).strip()
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    return normalized or default


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"Expected bool or 'true'/'false' string, got {raw!r}")
