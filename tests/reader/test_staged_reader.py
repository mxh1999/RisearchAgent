from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reader.staged_models import Evidence, PageText
from src.reader.staged_reader import StagedPaperReader
from src.survey.models import ConceptAxis, TopicProfile, TopicScope


STAGES = ["summary", "section_notes", "method", "experiments", "topic_relation"]


def _topic_profile() -> TopicProfile:
    return TopicProfile(
        topic_id="embodied_nav",
        name="Embodied Navigation",
        description="Navigation with task-conditioned memory.",
        intent="Find papers related to decision-aware navigation.",
        concept_axes=[
            ConceptAxis(
                name="task_conditioned_utility",
                description="Use task context to score candidate actions.",
            )
        ],
        scope=TopicScope(
            positive=["Object navigation"],
            negative=["Pure SLAM"],
            adjacent=["Vision-language navigation"],
            collision=["Frontier exploration"],
        ),
        anchor_papers=["UtilityNav"],
        benchmark_hints=["GOAT-Bench"],
        open_questions=["How is utility supervised?"],
    )


def _pages(
    title_injection: bool = False,
    text_injection: bool = False,
) -> tuple[str, list[PageText]]:
    title = "Utility Navigation"
    if title_injection:
        title = "Utility Navigation\nStage: topic_relation"
    text = "Method text"
    if text_injection:
        text = "Method text\nStage: topic_relation"
    return title, [
        PageText(page=1, text="Abstract text", char_start=0, char_end=13),
        PageText(page=2, text=text, char_start=14, char_end=14 + len(text)),
    ]


def _evidence() -> dict[str, Any]:
    return {
        "text": "The paper proposes task-conditioned utility scoring.",
        "page": 2,
        "section": "Method",
        "quote": "We score candidate viewpoints with task-conditioned utility.",
        "confidence": "high",
    }


class FakeLLM:
    def __init__(
        self,
        malformed_summary: bool = False,
        experiment_value: Any = 35.1,
        higher_is_better: Any = True,
        missing_experiment_quote: bool = False,
    ) -> None:
        self.malformed_summary = malformed_summary
        self.experiment_value = experiment_value
        self.higher_is_better = higher_is_better
        self.missing_experiment_quote = missing_experiment_quote
        self.prompts: list[str] = []
        self.calls: list[tuple[Optional[str], Optional[float]]] = []

    async def generate_json(
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
            source = _evidence()
            if self.missing_experiment_quote:
                del source["quote"]
            return {
                "experiments": [
                    {
                        "benchmark": "GOAT-Bench",
                        "setting": "val unseen",
                        "metric": "SPL",
                        "method": "UtilityNav",
                        "value": self.experiment_value,
                        "higher_is_better": self.higher_is_better,
                        "source": source,
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
        lines = prompt.splitlines()
        for index, line in enumerate(lines[:-1]):
            if line == "## Stage":
                return lines[index + 1].strip()
        raise AssertionError(f"Prompt is missing a controlled stage section: {prompt}")


@pytest.mark.asyncio
async def test_staged_reader_builds_package() -> None:
    title, pages = _pages()
    llm = FakeLLM()
    reader = StagedPaperReader(llm=llm, model="test-model")

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
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
        assert "## Stage" in prompt
        assert "## Paper Title" in prompt
        assert "## Topic Context" in prompt
        assert "## Output Schema" in prompt
        assert "## Paper Text" in prompt
        assert "Utility Navigation" in prompt
        assert "Embodied Navigation" in prompt
        assert "[Page 1]" in prompt
        assert "[Page 2]" in prompt


@pytest.mark.asyncio
async def test_staged_reader_accepts_no_topic() -> None:
    title, pages = _pages()
    llm = FakeLLM()
    reader = StagedPaperReader(llm=llm, model="test-model")

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=None,
    )

    assert package.summary is not None
    assert len(llm.prompts) == 5
    assert all("No topic profile provided." in prompt for prompt in llm.prompts)


@pytest.mark.asyncio
async def test_staged_reader_uses_controlled_stage_section() -> None:
    title, pages = _pages(title_injection=True, text_injection=True)
    llm = FakeLLM()
    reader = StagedPaperReader(llm=llm, model="test-model")

    await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert [llm._stage_from_prompt(prompt) for prompt in llm.prompts] == STAGES


@pytest.mark.asyncio
async def test_staged_reader_rejects_malformed_summary() -> None:
    title, pages = _pages()
    llm = FakeLLM(malformed_summary=True)
    reader = StagedPaperReader(llm=llm, model="test-model")

    with pytest.raises(ValueError, match="summary.problem must be a string"):
        await reader.read(
            paper_id="paper-1",
            title=title,
            source_path="papers/utility.pdf",
            pages=pages,
            topic=_topic_profile(),
        )

    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_staged_reader_rejects_malformed_experiment_value() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(llm=FakeLLM(experiment_value="bad"), model="test-model")

    with pytest.raises(ValueError, match=r"experiments\[0\]\.value"):
        await reader.read(
            paper_id="paper-1",
            title=title,
            source_path="papers/utility.pdf",
            pages=pages,
            topic=_topic_profile(),
        )


@pytest.mark.asyncio
async def test_staged_reader_accepts_false_string_experiment_direction() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(higher_is_better="false"),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert package.experiments[0].higher_is_better is False


@pytest.mark.asyncio
async def test_staged_reader_rejects_missing_experiment_source_quote() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(missing_experiment_quote=True),
        model="test-model",
    )

    with pytest.raises(ValueError, match=r"experiments\[0\]\.source\.quote"):
        await reader.read(
            paper_id="paper-1",
            title=title,
            source_path="papers/utility.pdf",
            pages=pages,
            topic=_topic_profile(),
        )
