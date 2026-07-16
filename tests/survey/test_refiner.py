from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.survey.refiner import TopicRefiner


def topic_json() -> dict[str, Any]:
    return {
        "name": "Decision-Aware 3D Navigation",
        "description": "Study how 3D memory becomes navigation decisions.",
        "intent": "Find papers about task-conditioned utility over 3D memories.",
        "concept_axes": [
            {
                "name": "task_conditioned_utility",
                "description": "Scores objects, frontiers, regions, or viewpoints.",
            }
        ],
        "scope": {
            "positive": ["3D memory for embodied navigation"],
            "negative": ["pure SLAM without semantic decisions"],
            "adjacent": ["static 3D grounding"],
            "collision": ["MSGNav"],
        },
        "anchor_papers": ["MTU3D"],
        "benchmark_hints": ["GOAT-Bench"],
        "search_queries": [
            {
                "name": "direct",
                "query": '"embodied navigation" "3D memory"',
                "purpose": "Find direct matches.",
            }
        ],
        "open_questions": ["What utility supervision is available?"],
    }


class FakeLLM:
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        expected_prompt_parts: tuple[str, ...] = (),
    ) -> None:
        self.response = response or topic_json()
        self.expected_prompt_parts = expected_prompt_parts

    async def generate_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
    ) -> dict[str, Any]:
        assert "Topic Refinement Task" in prompt
        assert model == "fake-model"
        assert temperature == 0.2
        for part in self.expected_prompt_parts:
            assert part in prompt
        return self.response


@pytest.mark.asyncio
async def test_refine_text_builds_topic_profile() -> None:
    refiner = TopicRefiner(FakeLLM(), model="fake-model")

    profile = await refiner.refine_text("I want decision-aware 3D navigation papers.")

    assert profile.topic_id == "decision_aware_3d_navigation"
    assert profile.scope.collision == ["MSGNav"]
    assert profile.search_queries[0].name == "direct"


@pytest.mark.asyncio
async def test_refine_note_includes_note_path(tmp_path: Path) -> None:
    note_path = tmp_path / "brainstorm.md"
    note_content = "# Brainstorm\n\nDecision-aware 3D navigation."
    note_path.write_text(note_content, encoding="utf-8")
    refiner = TopicRefiner(
        FakeLLM(expected_prompt_parts=(str(note_path), note_content)),
        model="fake-model",
    )

    profile = await refiner.refine_note(note_path)

    assert profile.name == "Decision-Aware 3D Navigation"


@pytest.mark.asyncio
async def test_refine_text_preserves_braces_in_user_material() -> None:
    refiner = TopicRefiner(
        FakeLLM(expected_prompt_parts=("Use {utility} in topic",)),
        model="fake-model",
    )

    profile = await refiner.refine_text("Use {utility} in topic")

    assert profile.name == "Decision-Aware 3D Navigation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"anchor_papers": "MTU3D"},
        {"scope": {"positive": "3D nav"}},
    ],
)
async def test_refine_text_rejects_malformed_list_fields(
    patch: dict[str, Any],
) -> None:
    raw = deepcopy(topic_json())
    for key, value in patch.items():
        if isinstance(value, dict):
            raw[key].update(value)
        else:
            raw[key] = value
    refiner = TopicRefiner(FakeLLM(response=raw), model="fake-model")

    with pytest.raises(ValueError, match="Invalid topic profile schema"):
        await refiner.refine_text("I want decision-aware 3D navigation papers.")
