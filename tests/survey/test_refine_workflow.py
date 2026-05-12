import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.survey.artifacts import TopicArtifactManager
from src.survey.models import SurveyEvent
from src.survey.refiner import TopicRefiner


class FakeLLM:
    async def generate_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
    ) -> dict[str, Any]:
        assert "task-conditioned utility learning" in prompt
        assert "RGB-only navigation" in prompt
        assert model == "gemini-2.5-pro"
        assert temperature == 0.2
        return {
            "name": "Decision-Aware 3D Navigation",
            "description": "Study how task context shapes decisions over 3D memory.",
            "intent": "Find papers that learn utility for embodied navigation decisions.",
            "concept_axes": [
                {
                    "name": "task_conditioned_utility",
                    "description": "Utility estimates conditioned on task goals.",
                }
            ],
            "scope": {
                "positive": ["Task-conditioned utility learning for 3D navigation"],
                "negative": ["RGB-only navigation without persistent 3D state"],
                "adjacent": ["Object goal navigation"],
                "collision": ["Pure visual navigation"],
            },
            "anchor_papers": ["MTU3D"],
            "benchmark_hints": ["GOAT-Bench"],
            "search_queries": [
                {
                    "name": "direct",
                    "query": '"task-conditioned" "3D navigation" utility',
                    "purpose": "Find utility-aware embodied navigation papers.",
                }
            ],
            "open_questions": ["How is utility supervision collected?"],
        }


@pytest.mark.asyncio
async def test_refine_note_creates_topic_directory(tmp_path: Path) -> None:
    note_path = tmp_path / "brainstorm.md"
    note_path.write_text(
        "Focus on task-conditioned utility learning rather than RGB-only navigation.",
        encoding="utf-8",
    )
    topics_root = tmp_path / "topics"

    profile = await TopicRefiner(
        llm=FakeLLM(),
        model="gemini-2.5-pro",
    ).refine_note(note_path)
    manager = TopicArtifactManager(topics_root)
    paths = manager.create_or_update_topic(profile)
    manager.append_event(
        paths.topic_dir,
        SurveyEvent(
            event_type="refine",
            message=f"Refined topic profile from {note_path}.",
        ),
    )

    topic = yaml.safe_load(paths.topic_yaml.read_text(encoding="utf-8"))
    assert topic["topic_id"] == "decision_aware_3d_navigation"
    assert (paths.topic_dir / "survey.md").exists()

    events = (paths.topic_dir / "state" / "survey_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    first_event = json.loads(events[0])
    assert first_event["message"].startswith("Refined topic profile")
