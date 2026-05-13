from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from src.reader.staged_models import Evidence, PageText
from src.reader.staged_reader import StagedPaperReader


STAGES = ["summary", "section_notes", "method", "experiments", "topic_relation"]


def _evidence() -> dict[str, Any]:
    return {
        "text": "The paper proposes task-conditioned utility scoring.",
        "page": 2,
        "section": "Method",
        "quote": "We score candidate viewpoints with task-conditioned utility.",
        "confidence": "high",
    }


class FakeLLM:
    def __init__(self, malformed_summary: bool = False) -> None:
        self.malformed_summary = malformed_summary
        self.prompts: list[str] = []
        self.calls: list[tuple[Optional[str], Optional[float]]] = []

    def generate_json(
        self,
        prompt: str,
        model: Optional[str],
        temperature: Optional[float],
    ) -> Any:
        self.prompts.append(prompt)
        self.calls.append((model, temperature))

        stage = self._stage_from_prompt(prompt)
        if stage == "summary":
            return {
                "summary": {
                    "problem": ["not a string"]
                    if self.malformed_summary
                    else "The paper studies embodied navigation under sparse goals.",
                    "method": "It learns utility scores over candidate viewpoints.",
                    "takeaway": "Task-conditioned utility improves decision quality.",
                    "contributions": ["Task-conditioned utility scoring"],
                }
            }
        if stage == "section_notes":
            return {
                "claims": [_evidence()],
                "critique": ["Needs stronger unseen-environment analysis."],
                "follow_up_questions": ["How is utility supervision collected?"],
            }
        if stage == "method":
            return {
                "method_modules": [
                    {
                        "name": "Utility Head",
                        "role": "Scores object and frontier candidates.",
                        "inputs": ["3D memory", "goal embedding"],
                        "outputs": ["candidate utility"],
                    }
                ]
            }
        if stage == "experiments":
            return {
                "experiments": [
                    {
                        "benchmark": "GOAT-Bench",
                        "setting": "val unseen",
                        "metric": "SPL",
                        "method": "UtilityNav",
                        "value": 35.1,
                        "higher_is_better": True,
                        "source": _evidence(),
                    }
                ]
            }
        if stage == "topic_relation":
            return {
                "topic_relation": {
                    "relevance": "core",
                    "concept_axes": ["task_conditioned_utility"],
                    "collision_risk": "medium",
                    "differentiation": "Uses learned utility rather than prompted reasoning.",
                }
            }
        raise AssertionError(f"Unexpected stage: {stage}")

    def _stage_from_prompt(self, prompt: str) -> str:
        for stage in STAGES:
            if f"Stage: {stage}" in prompt:
                return stage
        raise AssertionError(f"Prompt is missing a known stage: {prompt}")


def test_staged_reader_builds_package() -> None:
    pages = [
        PageText(page=1, text="Abstract text", char_start=0, char_end=13),
        PageText(page=2, text="Method text", char_start=14, char_end=25),
    ]
    llm = FakeLLM()
    reader = StagedPaperReader(llm=llm, model="test-model")

    package = asyncio.run(
        reader.read(
            paper_id="paper-1",
            title="Utility Navigation",
            source_path="papers/utility.pdf",
            pages=pages,
            topic_context="Embodied AI navigation with task-conditioned memory.",
        )
    )

    assert package.summary is not None
    assert package.summary.problem == (
        "The paper studies embodied navigation under sparse goals."
    )
    assert package.claims == [Evidence.from_dict(_evidence())]
    assert package.method_modules[0].name == "Utility Head"
    assert package.experiments[0].benchmark == "GOAT-Bench"
    assert package.topic_relation is not None
    assert package.topic_relation.relevance == "core"
    assert package.critique == ["Needs stronger unseen-environment analysis."]
    assert package.follow_up_questions == ["How is utility supervision collected?"]
    assert len(llm.prompts) == 5
    assert [llm._stage_from_prompt(prompt) for prompt in llm.prompts] == STAGES
    assert llm.calls == [("test-model", 0.1)] * 5
    for prompt in llm.prompts:
        assert "Utility Navigation" in prompt
        assert "Embodied AI navigation with task-conditioned memory." in prompt
        assert "[Page 1]" in prompt
        assert "[Page 2]" in prompt


def test_staged_reader_rejects_malformed_summary() -> None:
    reader = StagedPaperReader(llm=FakeLLM(malformed_summary=True), model="test-model")

    with pytest.raises(ValueError, match="summary.problem must be a string"):
        asyncio.run(
            reader.read(
                paper_id="paper-1",
                title="Utility Navigation",
                source_path="papers/utility.pdf",
                pages=[PageText(page=1, text="Abstract text", char_start=0, char_end=13)],
                topic_context="Embodied AI navigation.",
            )
        )
