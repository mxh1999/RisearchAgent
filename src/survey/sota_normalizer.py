from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol

from src.survey.models import TopicProfile
from src.survey.sota_models import (
    RawBenchmarkSetting,
    SettingGroup,
    SettingGroupRegistry,
    TopicSOTARecord,
)


ALLOWED_ACTIONS = {"merge_existing", "create_new"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}


class SettingNormalizerLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        ...


async def assign_setting_groups(
    records: list[TopicSOTARecord],
    registry: SettingGroupRegistry,
    topic: TopicProfile,
    llm: Optional[SettingNormalizerLLM] = None,
    model: Optional[str] = None,
    use_llm: bool = True,
) -> SettingGroupRegistry:
    groups = list(registry.groups)
    for raw_setting, setting_records in _unique_raw_settings(records).items():
        match_index = _find_exact_group(groups, raw_setting)
        if match_index is not None:
            continue

        candidates = _top_candidate_groups(groups, raw_setting, limit=5)
        if use_llm and llm is not None:
            decision = await _llm_decision(
                llm=llm,
                model=model,
                topic=topic,
                raw_setting=raw_setting,
                sample_records=setting_records[:3],
                candidates=candidates,
            )
            group = _apply_decision(decision, raw_setting, groups)
            if group is not None:
                groups = group
                continue

        confidence = "high" if not use_llm else "low"
        rationale = (
            "Created by conservative exact-setting grouping."
            if not use_llm
            else "Created as a separate group because no high-confidence merge was found."
        )
        groups.append(_new_group(raw_setting, confidence=confidence, rationale=rationale))

    return SettingGroupRegistry(groups=groups)


def _unique_raw_settings(
    records: list[TopicSOTARecord],
) -> dict[RawBenchmarkSetting, list[TopicSOTARecord]]:
    grouped: dict[RawBenchmarkSetting, list[TopicSOTARecord]] = {}
    for record in records:
        raw_setting = RawBenchmarkSetting(
            benchmark=record.benchmark,
            setting=record.setting,
        )
        grouped.setdefault(raw_setting, []).append(record)
    return grouped


def _find_exact_group(
    groups: list[SettingGroup],
    raw_setting: RawBenchmarkSetting,
) -> Optional[int]:
    for index, group in enumerate(groups):
        if raw_setting in group.raw_benchmark_settings:
            return index
    return None


def _top_candidate_groups(
    groups: list[SettingGroup],
    raw_setting: RawBenchmarkSetting,
    limit: int,
) -> list[SettingGroup]:
    scored = [
        (_similarity_score(group, raw_setting), group)
        for group in groups
    ]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: (-item[0], item[1].group_id))
    return [group for _, group in scored[:limit]]


def _similarity_score(group: SettingGroup, raw_setting: RawBenchmarkSetting) -> int:
    raw_tokens = _tokens(f"{raw_setting.benchmark} {raw_setting.setting}")
    group_text = " ".join(
        [
            group.canonical_benchmark,
            group.canonical_setting,
            *[
                f"{item.benchmark} {item.setting}"
                for item in group.raw_benchmark_settings
            ],
        ]
    )
    group_tokens = _tokens(group_text)
    return len(raw_tokens & group_tokens)


async def _llm_decision(
    llm: SettingNormalizerLLM,
    model: Optional[str],
    topic: TopicProfile,
    raw_setting: RawBenchmarkSetting,
    sample_records: list[TopicSOTARecord],
    candidates: list[SettingGroup],
) -> dict[str, Any]:
    prompt = _build_prompt(topic, raw_setting, sample_records, candidates)
    raw = await llm.generate_json(prompt, model=model, temperature=0.1)
    if not isinstance(raw, dict):
        raise ValueError("Setting normalization response must be an object")
    return raw


def _apply_decision(
    decision: dict[str, Any],
    raw_setting: RawBenchmarkSetting,
    groups: list[SettingGroup],
) -> Optional[list[SettingGroup]]:
    action = _require_choice(decision, "action", ALLOWED_ACTIONS)
    confidence = _require_choice(decision, "confidence", ALLOWED_CONFIDENCE)
    group_ids = {group.group_id for group in groups}
    if action == "merge_existing":
        group_id = _require_string(decision, "group_id")
        if group_id not in group_ids:
            raise ValueError(f"Setting normalization returned unknown group_id: {group_id}")
        if confidence != "high":
            groups.append(
                _new_group(
                    raw_setting,
                    confidence=confidence,
                    rationale=_require_string(decision, "rationale"),
                    canonical_benchmark=_require_string(
                        decision, "canonical_benchmark"
                    ),
                    canonical_setting=_require_string(
                        decision, "canonical_setting"
                    ),
                    comparison_axes=_require_axes(decision),
                )
            )
            return groups
        return _merge_into_group(
            groups,
            group_id=group_id,
            raw_setting=raw_setting,
            rationale=_require_string(decision, "rationale"),
            comparison_axes=_require_axes(decision),
        )

    groups.append(
        _new_group(
            raw_setting,
            confidence=confidence,
            rationale=_require_string(decision, "rationale"),
            canonical_benchmark=_optional_string(
                decision, "canonical_benchmark", raw_setting.benchmark
            ),
            canonical_setting=_optional_string(
                decision, "canonical_setting", raw_setting.setting
            ),
            comparison_axes=_require_axes(decision),
        )
    )
    return groups


def _merge_into_group(
    groups: list[SettingGroup],
    group_id: str,
    raw_setting: RawBenchmarkSetting,
    rationale: str,
    comparison_axes: dict[str, str],
) -> list[SettingGroup]:
    updated = []
    for group in groups:
        if group.group_id != group_id:
            updated.append(group)
            continue
        raw_settings = list(group.raw_benchmark_settings)
        if raw_setting not in raw_settings:
            raw_settings.append(raw_setting)
        updated.append(
            SettingGroup(
                group_id=group.group_id,
                canonical_benchmark=group.canonical_benchmark,
                canonical_setting=group.canonical_setting,
                raw_benchmark_settings=raw_settings,
                comparison_axes=comparison_axes or group.comparison_axes,
                confidence=group.confidence,
                rationale=rationale or group.rationale,
            )
        )
    return updated


def _new_group(
    raw_setting: RawBenchmarkSetting,
    confidence: str,
    rationale: str,
    canonical_benchmark: Optional[str] = None,
    canonical_setting: Optional[str] = None,
    comparison_axes: Optional[dict[str, str]] = None,
) -> SettingGroup:
    benchmark = canonical_benchmark or raw_setting.benchmark
    setting = canonical_setting or raw_setting.setting
    return SettingGroup(
        group_id=_make_group_id(benchmark, setting),
        canonical_benchmark=benchmark,
        canonical_setting=setting,
        raw_benchmark_settings=[raw_setting],
        comparison_axes=comparison_axes or {},
        confidence=confidence,
        rationale=rationale,
    )


def _build_prompt(
    topic: TopicProfile,
    raw_setting: RawBenchmarkSetting,
    sample_records: list[TopicSOTARecord],
    candidates: list[SettingGroup],
) -> str:
    payload = {
        "topic": {
            "name": topic.name,
            "intent": topic.intent,
            "benchmark_hints": topic.benchmark_hints,
        },
        "raw_setting": raw_setting.to_dict(),
        "sample_records": [
            {
                "record_id": record.record_id,
                "metric": record.metric,
                "method": record.method,
                "value": record.value,
                "paper_id": record.paper_id,
                "evidence": record.source_quote,
            }
            for record in sample_records
        ],
        "candidate_groups": [group.to_dict() for group in candidates],
    }
    return "\n".join(
        [
            "You canonicalize benchmark settings for SOTA tables.",
            "Do not merge settings when split, sensor modality, evaluator, protocol, task definition, or fine-tuning regime differs.",
            "Only return high confidence when the settings are clearly comparable.",
            "",
            "## Input",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "",
            "## Output JSON schema",
            "action: one of merge_existing, create_new.",
            "group_id: required for merge_existing and must be one candidate group_id.",
            "canonical_benchmark: string.",
            "canonical_setting: string.",
            "comparison_axes: object mapping axis names to string values.",
            "confidence: one of high, medium, low.",
            "rationale: string.",
        ]
    )


def _make_group_id(benchmark: str, setting: str) -> str:
    text = f"{benchmark}_{setting}".lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown_setting"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _require_choice(
    raw: dict[str, Any],
    key: str,
    choices: set[str],
) -> str:
    value = _require_string(raw, key)
    if value not in choices:
        raise ValueError(f"Setting normalization {key} must be one of {sorted(choices)}")
    return value


def _require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Setting normalization {key} must be a non-empty string")
    return value.strip()


def _optional_string(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Setting normalization {key} must be a non-empty string")
    return value.strip()


def _require_axes(raw: dict[str, Any]) -> dict[str, str]:
    value = raw.get("comparison_axes", {})
    if not isinstance(value, dict):
        raise ValueError("Setting normalization comparison_axes must be an object")
    return {str(key): str(axis_value) for key, axis_value in value.items()}
