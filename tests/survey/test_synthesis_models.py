from __future__ import annotations

import pytest

from src.survey.synthesis_models import (
    PaperClassification,
    PositioningSynthesis,
    ReferenceEntry,
    SurveySynthesis,
    TaxonomyGroup,
)


def _raw_synthesis() -> dict:
    return {
        "taxonomy": [
            {
                "name": "Explicit utility models",
                "description": "Methods that score action candidates.",
                "paper_ids": ["mtu3d"],
                "key_distinction": "They expose a decision score.",
            }
        ],
        "paper_map": [
            {
                "paper_id": "mtu3d",
                "title": "Move to Understand a 3D Scene",
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
                "paper_id": "mtu3d",
                "title": "Move to Understand a 3D Scene",
                "why_relevant": "Closest collision paper.",
                "evidence": "Candidate scoring.",
            }
        ],
        "open_questions": ["How is utility supervised?"],
    }


def test_survey_synthesis_round_trips() -> None:
    synthesis = SurveySynthesis.from_dict(_raw_synthesis())

    assert synthesis.taxonomy[0] == TaxonomyGroup(
        name="Explicit utility models",
        description="Methods that score action candidates.",
        paper_ids=["mtu3d"],
        key_distinction="They expose a decision score.",
    )
    assert synthesis.paper_map[0] == PaperClassification(
        paper_id="mtu3d",
        title="Move to Understand a 3D Scene",
        role="collision",
        rationale="It already scores objects and frontiers.",
        evidence="Scores object/frontier candidates.",
    )
    assert synthesis.positioning == PositioningSynthesis(
        thesis_gap="Learn task-conditioned utility over 3D memory.",
        novelty_claim="Generalize beyond object/frontier scoring.",
        collision_risks=["MTU3D may overlap."],
        recommended_positioning="Focus on explicit utility learning.",
    )
    assert synthesis.references[0] == ReferenceEntry(
        paper_id="mtu3d",
        title="Move to Understand a 3D Scene",
        why_relevant="Closest collision paper.",
        evidence="Candidate scoring.",
    )
    assert synthesis.to_dict()["open_questions"] == ["How is utility supervised?"]


def test_survey_synthesis_accepts_single_string_lists() -> None:
    raw = _raw_synthesis()
    raw["taxonomy"][0]["paper_ids"] = "mtu3d"
    raw["positioning"]["collision_risks"] = "MTU3D may overlap."
    raw["open_questions"] = "How is utility supervised?"

    synthesis = SurveySynthesis.from_dict(raw)

    assert synthesis.taxonomy[0].paper_ids == ["mtu3d"]
    assert synthesis.positioning.collision_risks == ["MTU3D may overlap."]
    assert synthesis.open_questions == ["How is utility supervised?"]


def test_survey_synthesis_rejects_unknown_role() -> None:
    raw = _raw_synthesis()
    raw["paper_map"][0]["role"] = "unrelated"

    with pytest.raises(ValueError, match="paper_map\\[0\\]\\.role"):
        SurveySynthesis.from_dict(raw)


def test_survey_synthesis_requires_top_level_sections() -> None:
    raw = _raw_synthesis()
    del raw["taxonomy"]

    with pytest.raises(ValueError, match="taxonomy is required"):
        SurveySynthesis.from_dict(raw)
