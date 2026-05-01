"""FieldMap pydantic types — the structured output of M5 synthesize.

See docs/onboard-redesign/10-synthesize.md. The FieldMap is produced by a
single Pro LLM call (Stage 1) from a frozen ExplorationState, then rendered
deterministically to Markdown (Stage 2).

All references to specific papers are arxiv_id strings; the synthesizer
validates these against state.paper_pool to catch hallucinated IDs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Header(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_snippet: str = Field(..., min_length=1, max_length=200)
    generated_at: datetime
    n_papers_surveyed: int = Field(..., ge=0)
    n_queries: int = Field(..., ge=0)
    elapsed_seconds: float = Field(..., ge=0.0)


class PaperRef(BaseModel):
    """Lightweight reference: arxiv_id + (cached) title for rendering."""
    model_config = ConfigDict(extra="forbid")

    arxiv_id: str
    title: str


class SubArea(BaseModel):
    """One sub-area of the field — corresponds to one cluster."""
    model_config = ConfigDict(extra="forbid")

    slug: str
    display_label: str
    description: str = Field(..., min_length=20)
    representative_papers: list[PaperRef] = Field(..., min_length=1)
    shared_benchmarks: list[str] = Field(default_factory=list)
    active_authors: list[str] = Field(default_factory=list)
    year_range: tuple[int, int]


class BenchmarkEntry(BaseModel):
    """A benchmark prevalent in the surveyed papers."""
    model_config = ConfigDict(extra="forbid")

    name: str
    task: str = ""  # short task description; LLM may leave empty if unknown
    n_papers: int = Field(..., ge=1)
    associated_subarea_slugs: list[str] = Field(default_factory=list)


class SchoolOfThought(BaseModel):
    """A methodological school across multiple papers."""
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = Field(..., min_length=10)
    representative_papers: list[PaperRef] = Field(..., min_length=1)


class ClassicPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arxiv_id: str
    title: str
    year: int
    why_classic: str = Field(..., min_length=10)


class ActiveGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # author or lab
    n_papers: int = Field(..., ge=1)
    associated_subarea_slugs: list[str] = Field(default_factory=list)


class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=10)
    evidence_papers: list[PaperRef] = Field(default_factory=list)


class AnchorPaper(BaseModel):
    """Paper recommended for SOTA seeding."""
    model_config = ConfigDict(extra="forbid")

    arxiv_id: str
    title: str
    cluster_slug: str
    rationale: str = Field(..., min_length=10)


class FieldMap(BaseModel):
    """Top-level synthesizer output. Persisted as JSON; rendered to Markdown."""
    model_config = ConfigDict(extra="forbid")

    header: Header
    sub_areas: list[SubArea] = Field(default_factory=list)
    dominant_benchmarks: list[BenchmarkEntry] = Field(default_factory=list)
    schools_of_thought: list[SchoolOfThought] = Field(default_factory=list)
    classic_baselines: list[ClassicPaper] = Field(default_factory=list)
    active_groups: list[ActiveGroup] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    anchor_papers: list[AnchorPaper] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "Header",
    "PaperRef",
    "SubArea",
    "BenchmarkEntry",
    "SchoolOfThought",
    "ClassicPaper",
    "ActiveGroup",
    "OpenQuestion",
    "AnchorPaper",
    "FieldMap",
]
