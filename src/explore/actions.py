"""Action types proposed by Planner and executed by Executor.

See docs/onboard-redesign/06-action-system.md for the full contract.

All actions are pydantic BaseModel subclasses; Gemini's response_schema
binds to the Action discriminated union (on action_type field).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _ActionBase(BaseModel):
    """Base class. Never instantiated directly — use one of the concrete subclasses."""
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(
        ...,
        min_length=1,
        description=(
            "Planner's rationale. Should cite specific state evidence (slug, "
            "arxiv_id, benchmark, numeric value). Quality is enforced at the "
            "prompt/test layer, not via pydantic length — a 30-char vapid "
            "string wouldn't pass semantic review anyway."
        ),
    )


class SearchAction(_ActionBase):
    action_type: Literal["search"] = "search"
    query: str = Field(..., min_length=1, max_length=500)
    categories: list[str] = Field(default_factory=list)
    max_results: int = Field(default=20, ge=1, le=50)
    date_range: Optional[tuple[date, date]] = None
    sort_by: Literal["relevance", "date"] = "relevance"
    source_tag: Literal[
        "user_intent_rewrite",
        "llm_generated",
        "cluster_targeted",
        "benchmark_seeded",
        "classic_lookup",
    ] = "llm_generated"
    targeted_cluster_slug: Optional[str] = None

    @field_validator("date_range")
    @classmethod
    def _check_date_range(cls, v):
        if v is not None and v[0] > v[1]:
            raise ValueError("date_range start must be <= end")
        return v


class SearchByAuthorAction(_ActionBase):
    action_type: Literal["search_by_author"] = "search_by_author"
    author_name: str = Field(..., min_length=1, max_length=100)
    max_results: int = Field(default=15, ge=1, le=30)
    date_range: Optional[tuple[date, date]] = None


class FetchCitationsAction(_ActionBase):
    action_type: Literal["fetch_citations"] = "fetch_citations"
    arxiv_id: str = Field(..., pattern=r"^\d{4}\.\d{4,5}(v\d+)?$")
    direction: Literal["cited_by", "references", "both"] = "references"
    max_results: int = Field(default=20, ge=1, le=50)


class FetchRelatedAction(_ActionBase):
    action_type: Literal["fetch_related"] = "fetch_related"
    arxiv_id: str = Field(..., pattern=r"^\d{4}\.\d{4,5}(v\d+)?$")
    max_results: int = Field(default=10, ge=1, le=30)


class ClusterRefreshAction(_ActionBase):
    action_type: Literal["cluster_refresh"] = "cluster_refresh"
    force: bool = False


class SkimAbstractAction(_ActionBase):
    action_type: Literal["skim_abstract"] = "skim_abstract"
    arxiv_id: str = Field(..., pattern=r"^\d{4}\.\d{4,5}(v\d+)?$")


class ReadPaperAction(_ActionBase):
    action_type: Literal["read_paper"] = "read_paper"
    arxiv_id: str = Field(..., pattern=r"^\d{4}\.\d{4,5}(v\d+)?$")


class CoverageAuditAction(_ActionBase):
    action_type: Literal["coverage_audit"] = "coverage_audit"


class StopAction(_ActionBase):
    action_type: Literal["stop"] = "stop"
    claimed_reason: Literal[
        "saturated", "coverage_complete", "budget_exhausted"
    ]


Action = Annotated[
    Union[
        SearchAction,
        SearchByAuthorAction,
        FetchCitationsAction,
        FetchRelatedAction,
        ClusterRefreshAction,
        SkimAbstractAction,
        ReadPaperAction,
        CoverageAuditAction,
        StopAction,
    ],
    Field(discriminator="action_type"),
]


ACTION_TYPES: dict[str, type[_ActionBase]] = {
    "search": SearchAction,
    "search_by_author": SearchByAuthorAction,
    "fetch_citations": FetchCitationsAction,
    "fetch_related": FetchRelatedAction,
    "cluster_refresh": ClusterRefreshAction,
    "skim_abstract": SkimAbstractAction,
    "read_paper": ReadPaperAction,
    "coverage_audit": CoverageAuditAction,
    "stop": StopAction,
}


def action_signature(action: _ActionBase) -> str:
    """Canonical signature for structural equality (ignores reasoning).

    Used by RULE_NO_REPEATED_EXACT_ACTION to detect identical consecutive actions.
    """
    data = action.model_dump(exclude={"reasoning"})
    # pydantic dumps dicts with insertion order; normalize via sorted json
    import json
    return f"{type(action).__name__}:{json.dumps(data, sort_keys=True, default=str)}"


def action_equal(a: _ActionBase, b: _ActionBase) -> bool:
    return action_signature(a) == action_signature(b)
