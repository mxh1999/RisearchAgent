from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reader.staged_models import Evidence, PageText, SourceTable
from src.reader.staged_reader import StagedPaperReader
from src.survey.models import ConceptAxis, TopicProfile, TopicScope


STAGES = ["summary", "section_notes", "method", "experiments", "topic_relation"]
_DEFAULT_TOPIC_CONCEPT_AXES = object()


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
        critique: Any = None,
        follow_up_questions: Any = None,
        experiments_response: Any = None,
        experiment_setting: Any = "val unseen",
        evidence_page: Any = 2,
        evidence_confidence: Any = "high",
        experiment_result_kind: Any = "main_task",
        topic_relevance: Any = "core",
        topic_concept_axes: Any = _DEFAULT_TOPIC_CONCEPT_AXES,
        topic_relation_response: Any = None,
    ) -> None:
        self.malformed_summary = malformed_summary
        self.experiment_value = experiment_value
        self.higher_is_better = higher_is_better
        self.missing_experiment_quote = missing_experiment_quote
        self.critique = (
            critique
            if critique is not None
            else ["Needs stronger unseen-environment analysis."]
        )
        self.follow_up_questions = (
            follow_up_questions
            if follow_up_questions is not None
            else ["How is utility supervision collected?"]
        )
        self.experiments_response = experiments_response
        self.experiment_setting = experiment_setting
        self.evidence_page = evidence_page
        self.evidence_confidence = evidence_confidence
        self.experiment_result_kind = experiment_result_kind
        self.topic_relevance = topic_relevance
        self.topic_concept_axes = (
            ["task_conditioned_utility"]
            if topic_concept_axes is _DEFAULT_TOPIC_CONCEPT_AXES
            else topic_concept_axes
        )
        self.topic_relation_response = topic_relation_response
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
            claim = _evidence()
            claim["page"] = self.evidence_page
            claim["confidence"] = self.evidence_confidence
            return {
                "claims": [claim],
                "critique": self.critique,
                "follow_up_questions": self.follow_up_questions,
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
            source["page"] = self.evidence_page
            source["confidence"] = self.evidence_confidence
            if self.missing_experiment_quote:
                del source["quote"]
            experiments = [
                {
                    "benchmark": "GOAT-Bench",
                    "setting": self.experiment_setting,
                    "metric": "SPL",
                    "method": "UtilityNav",
                    "value": self.experiment_value,
                    "higher_is_better": self.higher_is_better,
                    "result_kind": self.experiment_result_kind,
                    "source": source,
                }
            ]
            if self.experiments_response == "bare_list":
                return experiments
            return {"experiments": experiments}
        if stage == "topic_relation":
            if self.topic_relation_response is not None:
                return {"topic_relation": self.topic_relation_response}
            return {
                "topic_relation": {
                    "relevance": self.topic_relevance,
                    "concept_axes": self.topic_concept_axes,
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

    experiments_prompt = llm.prompts[STAGES.index("experiments")]
    assert "Use \"N/A\" for unknown string fields; do not use null." in experiments_prompt
    assert "source must be an object with text, page, section, quote, confidence" in (
        experiments_prompt
    )
    assert "result_kind" in experiments_prompt
    assert "table row or nearby sentence" in experiments_prompt
    assert "Do not use source_evidence." in experiments_prompt
    topic_relation_prompt = llm.prompts[STAGES.index("topic_relation")]
    assert (
        "If no topic profile is provided, return relevance \"unknown\", "
        "concept_axes [], collision_risk \"unknown\", differentiation \"\"."
    ) in topic_relation_prompt


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
async def test_staged_reader_adds_source_tables_to_experiments_prompt() -> None:
    title, pages = _pages()
    llm = FakeLLM()
    reader = StagedPaperReader(llm=llm, model="test-model")
    source_tables = [
        SourceTable(
            table_id="table-1",
            caption="ObjectNav results on HM3D and MP3D.",
            label="tab:objectnav",
            section="Experiments",
            latex=(
                r"\begin{tabular}{lcc} Method & SR & SPL \\ "
                r"Ours & 53.5 & 27.3 \end{tabular}"
            ),
            markdown="| Method | SR | SPL |\n|---|---|---|\n| Ours | 53.5 | 27.3 |",
            source_path="source/main.tex",
        )
    ]

    package = await reader.read(
        paper_id="utility",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        source_tables=source_tables,
    )

    experiments_prompt = llm.prompts[STAGES.index("experiments")]
    assert "## Source Tables" in experiments_prompt
    assert "Table ID: table-1" in experiments_prompt
    assert "ObjectNav results on HM3D and MP3D." in experiments_prompt
    assert "| Ours | 53.5 | 27.3 |" in experiments_prompt
    assert package.source_tables == source_tables


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
async def test_staged_reader_accepts_single_string_critique() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(critique="Needs stronger unseen-environment analysis."),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert package.critique == ["Needs stronger unseen-environment analysis."]


@pytest.mark.asyncio
async def test_staged_reader_coerces_text_note_drift() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(
            critique=[{"issue": "Needs stronger baselines"}, 3],
            follow_up_questions={"question": "Which data supervises utility?"},
        ),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert package.critique == ['{"issue": "Needs stronger baselines"}', "3"]
    assert package.follow_up_questions == [
        '{"question": "Which data supervises utility?"}'
    ]


@pytest.mark.asyncio
async def test_staged_reader_accepts_bare_experiments_list() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(experiments_response="bare_list"),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert package.experiments[0].benchmark == "GOAT-Bench"


@pytest.mark.asyncio
async def test_staged_reader_normalizes_llm_scalar_drift() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(
            experiment_setting=None,
            evidence_page="2",
            evidence_confidence=0.9,
        ),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert package.claims[0].page == 2
    assert package.claims[0].confidence == "0.9"
    assert package.experiments[0].setting == "N/A"
    assert package.experiments[0].source.page == 2
    assert package.experiments[0].source.confidence == "0.9"


@pytest.mark.asyncio
async def test_staged_reader_defaults_missing_topic_relevance() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(topic_relevance=None),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=None,
    )

    assert package.topic_relation is not None
    assert package.topic_relation.relevance == "unknown"


@pytest.mark.asyncio
async def test_staged_reader_defaults_null_topic_concept_axes() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(topic_concept_axes=None),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=None,
    )

    assert package.topic_relation is not None
    assert package.topic_relation.concept_axes == []


@pytest.mark.asyncio
async def test_staged_reader_coerces_topic_relation_axis_map() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(
            topic_concept_axes={
                "scene_representation": "core",
                "decision_mechanism": "partial",
            }
        ),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=None,
    )

    assert package.topic_relation is not None
    assert package.topic_relation.concept_axes == [
        "scene_representation",
        "decision_mechanism",
    ]


@pytest.mark.asyncio
async def test_staged_reader_coerces_topic_relation_text_drift() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(topic_relevance={"level": "adjacent", "reason": "2D value map"}),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=None,
    )

    assert package.topic_relation is not None
    assert package.topic_relation.relevance == (
        '{"level": "adjacent", "reason": "2D value map"}'
    )


@pytest.mark.asyncio
async def test_staged_reader_coerces_topic_relation_root_text_drift() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(
            topic_relation_response="adjacent: semantic navigation without learned utility"
        ),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=None,
    )

    assert package.topic_relation is not None
    assert (
        package.topic_relation.relevance
        == "adjacent: semantic navigation without learned utility"
    )
    assert package.topic_relation.concept_axes == []
    assert package.topic_relation.collision_risk == "unknown"
    assert package.topic_relation.differentiation == ""


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


@pytest.mark.asyncio
async def test_staged_reader_accepts_auxiliary_experiment_kind() -> None:
    title, pages = _pages()
    reader = StagedPaperReader(
        llm=FakeLLM(experiment_result_kind="auxiliary"),
        model="test-model",
    )

    package = await reader.read(
        paper_id="paper-1",
        title=title,
        source_path="papers/utility.pdf",
        pages=pages,
        topic=_topic_profile(),
    )

    assert package.experiments[0].result_kind == "auxiliary"
