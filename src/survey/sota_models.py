from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from src.reader.staged_models import PaperReadingPackage


@dataclass(frozen=True)
class TopicSOTARecord:
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TopicSOTARecord":
        return cls(
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
        )


def collect_sota_records(
    packages: list[PaperReadingPackage],
) -> list[TopicSOTARecord]:
    records = []
    for package in packages:
        for experiment in package.experiments:
            records.append(
                TopicSOTARecord(
                    paper_id=package.paper_id,
                    title=package.title,
                    benchmark=_normalize_text(experiment.benchmark),
                    setting=_normalize_text(experiment.setting, default="N/A"),
                    metric=_normalize_text(experiment.metric),
                    method=_normalize_text(experiment.method),
                    value=experiment.value,
                    higher_is_better=experiment.higher_is_better,
                    source_page=experiment.source.page,
                    source_section=_normalize_text(experiment.source.section),
                    source_quote=_normalize_text(experiment.source.quote),
                    source_confidence=_normalize_text(experiment.source.confidence),
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
