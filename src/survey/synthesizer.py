from __future__ import annotations

import json
from typing import Any, Optional, Protocol, Sequence

from src.reader.staged_models import PaperReadingPackage
from src.survey.models import TopicProfile
from src.survey.synthesis_models import SurveySynthesis


class SurveySynthesisLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        ...


class SurveySynthesizer:
    def __init__(self, llm: SurveySynthesisLLM, model: Optional[str]) -> None:
        self.llm = llm
        self.model = model

    async def synthesize(
        self,
        topic: TopicProfile,
        packages: Sequence[PaperReadingPackage],
    ) -> SurveySynthesis:
        if not packages:
            raise ValueError("At least one reading package is required for synthesis")

        prompt = _build_prompt(topic, packages)
        raw = await self.llm.generate_json(prompt, model=self.model, temperature=0.1)
        synthesis = SurveySynthesis.from_dict(raw)
        _validate_known_paper_ids(synthesis, {package.paper_id for package in packages})
        return synthesis


def _build_prompt(topic: TopicProfile, packages: Sequence[PaperReadingPackage]) -> str:
    topic_payload = {
        "topic_id": topic.topic_id,
        "name": topic.name,
        "description": topic.description,
        "intent": topic.intent,
        "concept_axes": [axis.__dict__ for axis in topic.concept_axes],
        "scope": topic.scope.__dict__,
        "anchor_papers": topic.anchor_papers,
        "benchmark_hints": topic.benchmark_hints,
        "open_questions": topic.open_questions,
    }
    reading_payload = [_reading_package_payload(package) for package in packages]

    return "\n".join(
        [
            "You synthesize a research survey from staged paper readings.",
            "Use only the provided reading packages. Do not invent paper ids.",
            "",
            "## Topic",
            json.dumps(topic_payload, ensure_ascii=False, indent=2),
            "",
            "## Reading Packages",
            json.dumps(reading_payload, ensure_ascii=False, indent=2),
            "",
            "## Output Schema",
            (
                "Return JSON with keys taxonomy, paper_map, positioning, references, "
                "open_questions. paper_map.role must be one of core, adjacent, "
                "collision, background. Every paper_id must come from Reading Packages."
            ),
        ]
    )


def _reading_package_payload(package: PaperReadingPackage) -> dict[str, Any]:
    return {
        "paper_id": package.paper_id,
        "title": package.title,
        "summary": package.summary.to_dict() if package.summary else None,
        "claims": [claim.to_dict() for claim in package.claims[:8]],
        "method_modules": [module.to_dict() for module in package.method_modules[:8]],
        "experiments": [record.to_dict() for record in package.experiments[:8]],
        "topic_relation": (
            package.topic_relation.to_dict() if package.topic_relation else None
        ),
        "critique": package.critique[:8],
        "follow_up_questions": package.follow_up_questions[:8],
    }


def _validate_known_paper_ids(synthesis: SurveySynthesis, known_ids: set[str]) -> None:
    referenced_ids = set()
    for group in synthesis.taxonomy:
        referenced_ids.update(group.paper_ids)
    for item in synthesis.paper_map:
        referenced_ids.add(item.paper_id)
    for entry in synthesis.references:
        referenced_ids.add(entry.paper_id)

    unknown_ids = sorted(referenced_ids - known_ids)
    if unknown_ids:
        raise ValueError(f"Synthesis referenced unknown paper_id values: {unknown_ids}")
