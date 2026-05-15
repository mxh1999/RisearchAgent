from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reader.staged_models import PaperReadingPackage, PaperSummary, TopicRelation
from src.survey.models import ConceptAxis, TopicProfile, TopicScope
from src.survey.synthesizer import SurveySynthesizer


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Find a thesis gap.",
        concept_axes=[ConceptAxis(name="utility", description="Candidate scoring.")],
        scope=TopicScope(positive=["ObjectNav"], collision=["MTU3D"]),
        anchor_papers=["Move to Understand a 3D Scene"],
        benchmark_hints=["HM3D"],
        open_questions=["How should utility be supervised?"],
    )


def _package(paper_id: str = "mtu3d", title: str = "MTU3D") -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"papers/{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation agents need decision models.",
            method="Scores object and frontier candidates.",
            takeaway=f"{title} is relevant to utility-based navigation.",
            contributions=["Candidate scoring"],
        ),
        topic_relation=TopicRelation(
            relevance="collision",
            concept_axes=["utility"],
            collision_risk="high",
            differentiation="Scores candidates with explicit utility.",
        ),
        critique=["Limited to fixed candidate types."],
        follow_up_questions=["Can the scoring function generalize?"],
    )


def _raw_synthesis(paper_id: str = "mtu3d") -> dict[str, Any]:
    return {
        "taxonomy": [
            {
                "name": "Explicit utility models",
                "description": "Methods that score action candidates.",
                "paper_ids": [paper_id],
                "key_distinction": "They expose a decision score.",
            }
        ],
        "paper_map": [
            {
                "paper_id": paper_id,
                "title": "MTU3D",
                "role": "collision",
                "rationale": "It already scores objects and frontiers.",
                "evidence": "Scores object/frontier candidates.",
            }
        ],
        "positioning": {
            "thesis_gap": "Learn task-conditioned utility over 3D memory.",
            "novelty_claim": "Generalize beyond object/frontier scoring.",
            "collision_risks": ["MTU3D may overlap."],
            "recommended_positioning": "Focus on explicit utility learning.",
        },
        "references": [
            {
                "paper_id": paper_id,
                "title": "MTU3D",
                "why_relevant": "Closest collision paper.",
                "evidence": "Candidate scoring.",
            }
        ],
        "open_questions": ["How is utility supervised?"],
    }


class FakeLLM:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.prompts: list[str] = []
        self.models: list[Optional[str]] = []
        self.temperatures: list[Optional[float]] = []

    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.prompts.append(prompt)
        self.models.append(model)
        self.temperatures.append(temperature)
        return self.response


def test_synthesizer_builds_prompt_and_returns_synthesis() -> None:
    import asyncio

    llm = FakeLLM(_raw_synthesis())
    synthesis = asyncio.run(
        SurveySynthesizer(llm, model="gemini-test").synthesize(_topic(), [_package()])
    )

    assert synthesis.paper_map[0].paper_id == "mtu3d"
    assert llm.models == ["gemini-test"]
    assert llm.temperatures == [0.1]
    prompt = llm.prompts[0]
    assert "Utility Navigation" in prompt
    assert "Task-conditioned utility over 3D memory." in prompt
    assert "mtu3d" in prompt
    assert "Scores object and frontier candidates." in prompt
    assert "Do not invent paper ids." in prompt


def test_synthesizer_rejects_empty_packages_before_llm_call() -> None:
    import asyncio

    llm = FakeLLM(_raw_synthesis())

    with pytest.raises(ValueError, match="At least one reading package"):
        asyncio.run(SurveySynthesizer(llm, model=None).synthesize(_topic(), []))

    assert llm.prompts == []


def test_synthesizer_rejects_unknown_paper_ids_from_llm() -> None:
    import asyncio

    llm = FakeLLM(_raw_synthesis("invented"))

    with pytest.raises(ValueError, match="unknown paper_id"):
        asyncio.run(
            SurveySynthesizer(llm, model="gemini-test").synthesize(
                _topic(), [_package()]
            )
        )
