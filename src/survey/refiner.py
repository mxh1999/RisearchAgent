from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn, Protocol

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

    def _profile_from_llm(self, raw: Any) -> TopicProfile:
        if not isinstance(raw, Mapping):
            self._schema_error("root must be a mapping")

        name = self._string_field(raw, "name")
        description = self._string_field(raw, "description")
        intent = self._string_field(raw, "intent")
        concept_axes = self._mapping_list_field(raw, "concept_axes")
        scope_raw = self._mapping_field(raw, "scope")
        search_queries = self._mapping_list_field(raw, "search_queries")
        return TopicProfile(
            topic_id=make_topic_id(name),
            name=name,
            description=description,
            intent=intent,
            concept_axes=[
                ConceptAxis(
                    name=self._string_field(item, "name", "concept_axes[]"),
                    description=self._string_field(
                        item,
                        "description",
                        "concept_axes[]",
                    ),
                )
                for item in concept_axes
            ],
            scope=TopicScope(
                positive=self._string_list_field(scope_raw, "positive", "scope"),
                negative=self._string_list_field(scope_raw, "negative", "scope"),
                adjacent=self._string_list_field(scope_raw, "adjacent", "scope"),
                collision=self._string_list_field(scope_raw, "collision", "scope"),
            ),
            anchor_papers=self._string_list_field(raw, "anchor_papers"),
            benchmark_hints=self._string_list_field(raw, "benchmark_hints"),
            search_queries=[
                TopicQuery(
                    name=self._string_field(item, "name", "search_queries[]"),
                    query=self._string_field(item, "query", "search_queries[]"),
                    purpose=self._string_field(item, "purpose", "search_queries[]"),
                )
                for item in search_queries
            ],
            open_questions=self._string_list_field(raw, "open_questions"),
        )

    @staticmethod
    def _schema_error(message: str) -> NoReturn:
        raise ValueError(f"Invalid topic profile schema: {message}")

    def _field_path(self, field: str, parent: str | None = None) -> str:
        if parent is None:
            return field
        return f"{parent}.{field}"

    def _string_field(
        self,
        raw: Mapping[str, Any],
        field: str,
        parent: str | None = None,
    ) -> str:
        value = raw.get(field)
        if not isinstance(value, str):
            self._schema_error(f"{self._field_path(field, parent)} must be a string")
        return value

    def _mapping_field(
        self,
        raw: Mapping[str, Any],
        field: str,
        parent: str | None = None,
    ) -> Mapping[str, Any]:
        value = raw.get(field)
        if not isinstance(value, Mapping):
            self._schema_error(f"{self._field_path(field, parent)} must be a mapping")
        return value

    def _string_list_field(
        self,
        raw: Mapping[str, Any],
        field: str,
        parent: str | None = None,
    ) -> list[str]:
        value = raw.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            self._schema_error(
                f"{self._field_path(field, parent)} must be a list of strings"
            )
        return value

    def _mapping_list_field(
        self,
        raw: Mapping[str, Any],
        field: str,
        parent: str | None = None,
    ) -> list[Mapping[str, Any]]:
        value = raw.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, Mapping) for item in value
        ):
            self._schema_error(
                f"{self._field_path(field, parent)} must be a list of mappings"
            )
        return value
