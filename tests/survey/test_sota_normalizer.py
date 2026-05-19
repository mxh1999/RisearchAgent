from __future__ import annotations

from typing import Any, Optional

import pytest

from src.survey.models import TopicProfile
from src.survey.sota_models import (
    RawBenchmarkSetting,
    SettingGroup,
    SettingGroupRegistry,
    TopicSOTARecord,
)
from src.survey.sota_normalizer import assign_setting_groups


class FakeLLM:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.prompts: list[str] = []

    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.prompts.append(prompt)
        return self.response


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Maintain comparable SOTA tables.",
    )


def _record(
    record_id: str = "paper-1::GOAT-Bench::val unseen::SPL::SampleNav",
    benchmark: str = "GOAT-Bench",
    setting: str = "val unseen",
) -> TopicSOTARecord:
    return TopicSOTARecord(
        record_id=record_id,
        paper_id="paper-1",
        title="Paper One",
        benchmark=benchmark,
        setting=setting,
        metric="SPL",
        method="SampleNav",
        value=35.1,
        higher_is_better=True,
        source_page=8,
        source_section="Experiments",
        source_quote="SampleNav obtains 35.1 SPL.",
        source_confidence="high",
    )


def _group(
    group_id: str = "goat_bench_val_unseen",
    benchmark: str = "GOAT-Bench",
    setting: str = "val unseen",
) -> SettingGroup:
    return SettingGroup(
        group_id=group_id,
        canonical_benchmark=benchmark,
        canonical_setting=setting,
        raw_benchmark_settings=[
            RawBenchmarkSetting(benchmark=benchmark, setting=setting)
        ],
        comparison_axes={"split": "val unseen"},
        confidence="high",
        rationale="Same benchmark split.",
    )


@pytest.mark.asyncio
async def test_exact_match_reuses_group_without_llm() -> None:
    llm = FakeLLM(response={"action": "create_new"})
    registry = SettingGroupRegistry(groups=[_group()])

    updated = await assign_setting_groups(
        [_record()],
        registry,
        _topic(),
        llm=llm,
        model="test-model",
        use_llm=True,
    )

    assert updated == registry
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_conservative_mode_creates_new_group_without_llm() -> None:
    llm = FakeLLM(response={"action": "merge_existing"})

    updated = await assign_setting_groups(
        [_record(setting="GOAT validation unseen split")],
        SettingGroupRegistry(groups=[]),
        _topic(),
        llm=llm,
        model="test-model",
        use_llm=False,
    )

    assert len(updated.groups) == 1
    assert updated.groups[0].canonical_setting == "GOAT validation unseen split"
    assert updated.groups[0].confidence == "high"
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_high_confidence_llm_merge_reuses_candidate_group() -> None:
    llm = FakeLLM(
        response={
            "action": "merge_existing",
            "group_id": "goat_bench_val_unseen",
            "canonical_benchmark": "GOAT-Bench",
            "canonical_setting": "val unseen",
            "comparison_axes": {"split": "val unseen"},
            "confidence": "high",
            "rationale": "Equivalent split and protocol.",
        }
    )
    registry = SettingGroupRegistry(groups=[_group()])

    updated = await assign_setting_groups(
        [_record(setting="GOAT validation unseen split")],
        registry,
        _topic(),
        llm=llm,
        model="test-model",
        use_llm=True,
    )

    assert len(updated.groups) == 1
    assert RawBenchmarkSetting(
        benchmark="GOAT-Bench",
        setting="GOAT validation unseen split",
    ) in updated.groups[0].raw_benchmark_settings
    assert len(llm.prompts) == 1
    assert "candidate_groups" in llm.prompts[0]


@pytest.mark.asyncio
async def test_medium_confidence_llm_merge_creates_separate_group() -> None:
    llm = FakeLLM(
        response={
            "action": "merge_existing",
            "group_id": "goat_bench_val_unseen",
            "canonical_benchmark": "GOAT-Bench",
            "canonical_setting": "val unseen RGB-only",
            "comparison_axes": {"split": "val unseen", "sensor": "RGB-only"},
            "confidence": "medium",
            "rationale": "Possibly equivalent, but sensor modality differs.",
        }
    )
    registry = SettingGroupRegistry(groups=[_group()])

    updated = await assign_setting_groups(
        [_record(setting="val unseen RGB-only")],
        registry,
        _topic(),
        llm=llm,
        model="test-model",
        use_llm=True,
    )

    assert len(updated.groups) == 2
    assert updated.groups[1].canonical_setting == "val unseen RGB-only"
    assert updated.groups[1].confidence == "medium"


@pytest.mark.asyncio
async def test_unknown_llm_group_id_is_rejected() -> None:
    llm = FakeLLM(
        response={
            "action": "merge_existing",
            "group_id": "missing",
            "canonical_benchmark": "GOAT-Bench",
            "canonical_setting": "val unseen",
            "comparison_axes": {},
            "confidence": "high",
            "rationale": "Equivalent.",
        }
    )

    with pytest.raises(ValueError, match="unknown group_id"):
        await assign_setting_groups(
            [_record(setting="GOAT validation unseen split")],
            SettingGroupRegistry(groups=[_group()]),
            _topic(),
            llm=llm,
            model="test-model",
            use_llm=True,
        )
