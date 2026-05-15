from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.reader.staged_models import PaperReadingPackage, PaperSummary, TopicRelation
from src.survey.artifacts import TopicArtifactManager
from src.survey.models import ConceptAxis, TopicProfile, TopicScope
from src.survey.reading_loader import load_reading_packages
from src.survey.survey_renderer import (
    render_paper_map_markdown,
    render_positioning_markdown,
    render_references_markdown,
    render_taxonomy_markdown,
)
from src.survey.synthesizer import SurveySynthesizer


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Find a thesis gap.",
        concept_axes=[ConceptAxis(name="utility", description="Candidate scoring.")],
        scope=TopicScope(positive=["ObjectNav"], collision=["MTU3D"]),
    )


def _package(paper_id: str, title: str, relevance: str) -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation requires decisions.",
            method="Scores candidates.",
            takeaway=f"{title} is relevant.",
            contributions=["Candidate scoring"],
        ),
        topic_relation=TopicRelation(
            relevance=relevance,
            concept_axes=["utility"],
            collision_risk="medium",
            differentiation="Uses explicit scoring.",
        ),
    )


def _write_package(topic_dir: Path, package: PaperReadingPackage) -> None:
    (topic_dir / "papers" / f"{package.paper_id}.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )


class FakeLLM:
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        return {
            "taxonomy": [
                {
                    "name": "Explicit utility models",
                    "description": "Score candidate actions.",
                    "paper_ids": ["mtu3d", "vlfm"],
                    "key_distinction": "Exposes decision scores.",
                }
            ],
            "paper_map": [
                {
                    "paper_id": "mtu3d",
                    "title": "MTU3D",
                    "role": "collision",
                    "rationale": "Closest overlap.",
                    "evidence": "Candidate scoring.",
                },
                {
                    "paper_id": "vlfm",
                    "title": "VLFM",
                    "role": "adjacent",
                    "rationale": "Provides frontier-map context.",
                    "evidence": "Language-guided frontiers.",
                },
            ],
            "positioning": {
                "thesis_gap": "General utility over 3D memory.",
                "novelty_claim": "Beyond object/frontier scoring.",
                "collision_risks": ["MTU3D overlap."],
                "recommended_positioning": "Emphasize task-conditioned utility.",
            },
            "references": [
                {
                    "paper_id": "mtu3d",
                    "title": "MTU3D",
                    "why_relevant": "Collision paper.",
                    "evidence": "Candidate scoring.",
                },
                {
                    "paper_id": "vlfm",
                    "title": "VLFM",
                    "why_relevant": "Adjacent frontier baseline.",
                    "evidence": "Language-guided frontiers.",
                },
            ],
            "open_questions": ["How is utility supervised?"],
        }


async def _run_workflow(topic_dir: Path) -> None:
    topic = _topic()
    manager = TopicArtifactManager(topic_dir.parent)
    paths = manager.create_or_update_topic(topic)
    _write_package(paths.topic_dir, _package("mtu3d", "MTU3D", "collision"))
    _write_package(paths.topic_dir, _package("vlfm", "VLFM", "adjacent"))
    (paths.topic_dir / "survey.md").write_text(
        "# Utility Navigation Survey\n\n"
        "Manual survey text.\n\n"
        "<!-- BEGIN AUTO:taxonomy -->\nOld taxonomy\n<!-- END AUTO:taxonomy -->\n",
        encoding="utf-8",
    )

    packages = load_reading_packages(paths.topic_dir / "papers")
    synthesis = await SurveySynthesizer(FakeLLM(), model="test-model").synthesize(
        topic, packages
    )
    manager.update_auto_block(
        paths.topic_dir / "survey.md",
        "taxonomy",
        render_taxonomy_markdown(synthesis),
    )
    manager.update_auto_block(
        paths.topic_dir / "papers.md",
        "paper-map",
        render_paper_map_markdown(synthesis),
    )
    manager.update_auto_block(
        paths.topic_dir / "positioning.md",
        "positioning",
        render_positioning_markdown(synthesis),
    )
    manager.update_auto_block(
        paths.topic_dir / "references.md",
        "references",
        render_references_markdown(synthesis),
    )


def test_fake_synthesize_workflow_updates_artifacts(tmp_path: Path) -> None:
    import asyncio

    asyncio.run(_run_workflow(tmp_path / "utility_nav"))

    topic_dir = tmp_path / "utility_nav"
    survey = (topic_dir / "survey.md").read_text(encoding="utf-8")
    papers = (topic_dir / "papers.md").read_text(encoding="utf-8")
    positioning = (topic_dir / "positioning.md").read_text(encoding="utf-8")
    references = (topic_dir / "references.md").read_text(encoding="utf-8")

    assert "Manual survey text." in survey
    assert "Explicit utility models" in survey
    assert "Old taxonomy" not in survey
    assert "MTU3D" in papers
    assert "VLFM" in papers
    assert "General utility over 3D memory." in positioning
    assert "Collision paper." in references
