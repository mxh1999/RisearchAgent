from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_PAPER_ROLES = {"core", "adjacent", "collision", "background"}


@dataclass(frozen=True)
class TaxonomyGroup:
    name: str
    description: str
    paper_ids: list[str] = field(default_factory=list)
    key_distinction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str = "taxonomy[]") -> "TaxonomyGroup":
        mapping = _require_mapping(raw, path)
        return cls(
            name=_require_string(_required(mapping, "name", f"{path}.name"), f"{path}.name"),
            description=_require_string(
                _required(mapping, "description", f"{path}.description"),
                f"{path}.description",
            ),
            paper_ids=_string_list(mapping.get("paper_ids", []), f"{path}.paper_ids"),
            key_distinction=_require_string(
                _required(mapping, "key_distinction", f"{path}.key_distinction"),
                f"{path}.key_distinction",
            ),
        )


@dataclass(frozen=True)
class PaperClassification:
    paper_id: str
    title: str
    role: str
    rationale: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], path: str = "paper_map[]"
    ) -> "PaperClassification":
        mapping = _require_mapping(raw, path)
        role = _require_string(_required(mapping, "role", f"{path}.role"), f"{path}.role")
        if role not in ALLOWED_PAPER_ROLES:
            raise ValueError(f"{path}.role must be one of {sorted(ALLOWED_PAPER_ROLES)}")
        return cls(
            paper_id=_require_string(
                _required(mapping, "paper_id", f"{path}.paper_id"), f"{path}.paper_id"
            ),
            title=_require_string(_required(mapping, "title", f"{path}.title"), f"{path}.title"),
            role=role,
            rationale=_require_string(
                _required(mapping, "rationale", f"{path}.rationale"), f"{path}.rationale"
            ),
            evidence=_optional_string(mapping.get("evidence", ""), f"{path}.evidence"),
        )


@dataclass(frozen=True)
class PositioningSynthesis:
    thesis_gap: str
    novelty_claim: str
    collision_risks: list[str] = field(default_factory=list)
    recommended_positioning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], path: str = "positioning"
    ) -> "PositioningSynthesis":
        mapping = _require_mapping(raw, path)
        return cls(
            thesis_gap=_require_string(
                _required(mapping, "thesis_gap", f"{path}.thesis_gap"),
                f"{path}.thesis_gap",
            ),
            novelty_claim=_require_string(
                _required(mapping, "novelty_claim", f"{path}.novelty_claim"),
                f"{path}.novelty_claim",
            ),
            collision_risks=_string_list(
                mapping.get("collision_risks", []), f"{path}.collision_risks"
            ),
            recommended_positioning=_require_string(
                _required(
                    mapping,
                    "recommended_positioning",
                    f"{path}.recommended_positioning",
                ),
                f"{path}.recommended_positioning",
            ),
        )


@dataclass(frozen=True)
class ReferenceEntry:
    paper_id: str
    title: str
    why_relevant: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str = "references[]") -> "ReferenceEntry":
        mapping = _require_mapping(raw, path)
        return cls(
            paper_id=_require_string(
                _required(mapping, "paper_id", f"{path}.paper_id"), f"{path}.paper_id"
            ),
            title=_require_string(_required(mapping, "title", f"{path}.title"), f"{path}.title"),
            why_relevant=_require_string(
                _required(mapping, "why_relevant", f"{path}.why_relevant"),
                f"{path}.why_relevant",
            ),
            evidence=_optional_string(mapping.get("evidence", ""), f"{path}.evidence"),
        )


@dataclass(frozen=True)
class SurveySynthesis:
    taxonomy: list[TaxonomyGroup] = field(default_factory=list)
    paper_map: list[PaperClassification] = field(default_factory=list)
    positioning: PositioningSynthesis = field(
        default_factory=lambda: PositioningSynthesis(
            thesis_gap="",
            novelty_claim="",
            collision_risks=[],
            recommended_positioning="",
        )
    )
    references: list[ReferenceEntry] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxonomy": [group.to_dict() for group in self.taxonomy],
            "paper_map": [item.to_dict() for item in self.paper_map],
            "positioning": self.positioning.to_dict(),
            "references": [entry.to_dict() for entry in self.references],
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SurveySynthesis":
        mapping = _require_mapping(raw, "survey_synthesis")
        taxonomy_raw = _require_list(_required(mapping, "taxonomy", "taxonomy"), "taxonomy")
        paper_map_raw = _require_list(_required(mapping, "paper_map", "paper_map"), "paper_map")
        references_raw = _require_list(
            _required(mapping, "references", "references"), "references"
        )
        return cls(
            taxonomy=[
                TaxonomyGroup.from_dict(item, f"taxonomy[{index}]")
                for index, item in enumerate(taxonomy_raw)
            ],
            paper_map=[
                PaperClassification.from_dict(item, f"paper_map[{index}]")
                for index, item in enumerate(paper_map_raw)
            ],
            positioning=PositioningSynthesis.from_dict(
                _required(mapping, "positioning", "positioning")
            ),
            references=[
                ReferenceEntry.from_dict(item, f"references[{index}]")
                for index, item in enumerate(references_raw)
            ],
            open_questions=_string_list(mapping.get("open_questions", []), "open_questions"),
        )


def _required(raw: dict[str, Any], key: str, path: str) -> Any:
    if key not in raw:
        raise ValueError(f"{path} is required")
    return raw[key]


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    return raw


def _require_list(raw: Any, path: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ValueError(f"{path} must be a list")
    return raw


def _require_string(raw: Any, path: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{path} must be a string")
    return raw


def _optional_string(raw: Any, path: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"{path} must be a string")
    return raw


def _string_list(raw: Any, path: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    items = _require_list(raw, path)
    for index, item in enumerate(items):
        _require_string(item, f"{path}[{index}]")
    return items
