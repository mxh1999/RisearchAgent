from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"Expected bool or 'true'/'false' string, got {raw!r}")


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    char_start: int
    char_end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PageText":
        return cls(
            page=int(raw["page"]),
            text=str(raw["text"]),
            char_start=int(raw["char_start"]),
            char_end=int(raw["char_end"]),
        )


@dataclass(frozen=True)
class Evidence:
    text: str
    page: int
    section: str
    quote: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Evidence":
        return cls(
            text=str(raw["text"]),
            page=int(raw["page"]),
            section=str(raw["section"]),
            quote=str(raw["quote"]),
            confidence=str(raw["confidence"]),
        )


@dataclass(frozen=True)
class PaperSummary:
    problem: str
    method: str
    takeaway: str
    contributions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PaperSummary":
        return cls(
            problem=str(raw["problem"]),
            method=str(raw["method"]),
            takeaway=str(raw["takeaway"]),
            contributions=[str(item) for item in raw.get("contributions", [])],
        )


@dataclass(frozen=True)
class MethodModule:
    name: str
    role: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MethodModule":
        return cls(
            name=str(raw["name"]),
            role=str(raw["role"]),
            inputs=[str(item) for item in raw.get("inputs", [])],
            outputs=[str(item) for item in raw.get("outputs", [])],
        )


@dataclass(frozen=True)
class ExperimentRecord:
    benchmark: str
    setting: str
    metric: str
    method: str
    value: float
    higher_is_better: bool
    source: Evidence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExperimentRecord":
        return cls(
            benchmark=str(raw["benchmark"]),
            setting=str(raw["setting"]),
            metric=str(raw["metric"]),
            method=str(raw["method"]),
            value=float(raw["value"]),
            higher_is_better=_parse_bool(raw["higher_is_better"]),
            source=Evidence.from_dict(raw["source"]),
        )


@dataclass(frozen=True)
class TopicRelation:
    relevance: str
    concept_axes: list[str] = field(default_factory=list)
    collision_risk: str = "unknown"
    differentiation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TopicRelation":
        return cls(
            relevance=str(raw["relevance"]),
            concept_axes=[str(item) for item in raw.get("concept_axes", [])],
            collision_risk=str(raw.get("collision_risk", "unknown")),
            differentiation=str(raw.get("differentiation", "")),
        )


@dataclass(frozen=True)
class PaperReadingPackage:
    paper_id: str
    title: str
    source_path: str
    pages: list[PageText] = field(default_factory=list)
    summary: Optional[PaperSummary] = None
    claims: list[Evidence] = field(default_factory=list)
    method_modules: list[MethodModule] = field(default_factory=list)
    experiments: list[ExperimentRecord] = field(default_factory=list)
    topic_relation: Optional[TopicRelation] = None
    critique: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "source_path": self.source_path,
            "pages": [page.to_dict() for page in self.pages],
            "summary": self.summary.to_dict() if self.summary else None,
            "claims": [claim.to_dict() for claim in self.claims],
            "method_modules": [module.to_dict() for module in self.method_modules],
            "experiments": [record.to_dict() for record in self.experiments],
            "topic_relation": self.topic_relation.to_dict() if self.topic_relation else None,
            "critique": list(self.critique),
            "follow_up_questions": list(self.follow_up_questions),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PaperReadingPackage":
        summary_raw = raw.get("summary")
        relation_raw = raw.get("topic_relation")
        return cls(
            paper_id=str(raw["paper_id"]),
            title=str(raw["title"]),
            source_path=str(raw["source_path"]),
            pages=[PageText.from_dict(item) for item in raw.get("pages", [])],
            summary=PaperSummary.from_dict(summary_raw) if summary_raw else None,
            claims=[Evidence.from_dict(item) for item in raw.get("claims", [])],
            method_modules=[
                MethodModule.from_dict(item)
                for item in raw.get("method_modules", [])
            ],
            experiments=[
                ExperimentRecord.from_dict(item)
                for item in raw.get("experiments", [])
            ],
            topic_relation=TopicRelation.from_dict(relation_raw) if relation_raw else None,
            critique=[str(item) for item in raw.get("critique", [])],
            follow_up_questions=[
                str(item) for item in raw.get("follow_up_questions", [])
            ],
        )
