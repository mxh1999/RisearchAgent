from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def make_topic_id(name: str, max_length: int = 72) -> str:
    """Create a stable filesystem-safe topic id from a topic name."""
    normalized = name.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "untitled_topic"
    return normalized[:max_length].rstrip("_")


@dataclass(frozen=True)
class ConceptAxis:
    name: str
    description: str


@dataclass(frozen=True)
class TopicScope:
    positive: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    adjacent: list[str] = field(default_factory=list)
    collision: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TopicQuery:
    name: str
    query: str
    purpose: str


@dataclass(frozen=True)
class TopicProfile:
    topic_id: str
    name: str
    description: str
    intent: str
    concept_axes: list[ConceptAxis] = field(default_factory=list)
    scope: TopicScope = field(default_factory=TopicScope)
    anchor_papers: list[str] = field(default_factory=list)
    benchmark_hints: list[str] = field(default_factory=list)
    search_queries: list[TopicQuery] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TopicProfile":
        axes = [ConceptAxis(**item) for item in raw.get("concept_axes", [])]
        scope = TopicScope(**raw.get("scope", {}))
        queries = [TopicQuery(**item) for item in raw.get("search_queries", [])]
        return cls(
            topic_id=raw["topic_id"],
            name=raw["name"],
            description=raw["description"],
            intent=raw["intent"],
            concept_axes=axes,
            scope=scope,
            anchor_papers=list(raw.get("anchor_papers", [])),
            benchmark_hints=list(raw.get("benchmark_hints", [])),
            search_queries=queries,
            open_questions=list(raw.get("open_questions", [])),
        )


@dataclass(frozen=True)
class SurveyEvent:
    event_type: str
    message: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
