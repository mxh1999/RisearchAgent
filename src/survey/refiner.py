from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from src.survey.models import (
    ConceptAxis,
    TopicProfile,
    TopicQuery,
    TopicScope,
    make_topic_id,
)


class TopicRefinerLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        *,
        model: str,
        temperature: float,
    ) -> dict[str, Any]:
        ...


REFINE_PROMPT = """Topic Refinement Task

Refine the supplied research note or free-form topic text into a structured topic
profile for a literature survey.

Source:
{source}

Material:
{material}

Return only JSON matching this schema:
{{
  "name": "short human-readable topic name",
  "description": "one or two sentence topic description",
  "intent": "what the survey should help the researcher decide or find",
  "concept_axes": [
    {{"name": "snake_case_axis_name", "description": "axis meaning"}}
  ],
  "scope": {{
    "positive": ["in-scope area"],
    "negative": ["out-of-scope area"],
    "adjacent": ["nearby but distinct area"],
    "collision": ["term or paper that may be confused with this topic"]
  }},
  "anchor_papers": ["paper title or short name"],
  "benchmark_hints": ["benchmark or dataset name"],
  "search_queries": [
    {{"name": "direct", "query": "search string", "purpose": "query purpose"}}
  ],
  "open_questions": ["question to resolve during survey"]
}}
"""


class TopicRefiner:
    def __init__(self, llm: TopicRefinerLLM, model: str) -> None:
        self.llm = llm
        self.model = model

    async def refine_text(self, text: str) -> TopicProfile:
        return await self._refine("inline text", text)

    async def refine_note(self, note_path: Path) -> TopicProfile:
        path = Path(note_path)
        material = path.read_text(encoding="utf-8")
        return await self._refine(f"note path: {path}", material)

    async def _refine(self, source: str, material: str) -> TopicProfile:
        prompt = REFINE_PROMPT.format(source=source, material=material)
        raw = await self.llm.generate_json(
            prompt,
            model=self.model,
            temperature=0.2,
        )
        return self._profile_from_llm(raw)

    def _profile_from_llm(self, raw: dict[str, Any]) -> TopicProfile:
        name = str(raw["name"])
        scope_raw = raw.get("scope", {})
        return TopicProfile(
            topic_id=make_topic_id(name),
            name=name,
            description=str(raw["description"]),
            intent=str(raw["intent"]),
            concept_axes=[
                ConceptAxis(
                    name=str(item["name"]),
                    description=str(item["description"]),
                )
                for item in raw.get("concept_axes", [])
            ],
            scope=TopicScope(
                positive=list(scope_raw.get("positive", [])),
                negative=list(scope_raw.get("negative", [])),
                adjacent=list(scope_raw.get("adjacent", [])),
                collision=list(scope_raw.get("collision", [])),
            ),
            anchor_papers=list(raw.get("anchor_papers", [])),
            benchmark_hints=list(raw.get("benchmark_hints", [])),
            search_queries=[
                TopicQuery(
                    name=str(item["name"]),
                    query=str(item["query"]),
                    purpose=str(item["purpose"]),
                )
                for item in raw.get("search_queries", [])
            ],
            open_questions=list(raw.get("open_questions", [])),
        )
