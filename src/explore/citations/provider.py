"""CitationProvider abstract base + NullProvider.

See docs/onboard-redesign/11-citation-provider.md.

Public API:
  CitationProvider (ABC)
    .get_paper(arxiv_id) -> PaperCitationInfo | None
    .get_references(arxiv_id, limit) -> list[RelatedPaper]
    .get_citations(arxiv_id, limit) -> list[RelatedPaper]
    .get_related(arxiv_id, limit) -> list[RelatedPaper]
    .is_available() -> bool

  NullProvider: returns empty values for everything (used when user
  configures citation_provider: none, or as a default during testing).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PaperCitationInfo:
    """Subset of a paper's citation metadata we care about."""
    arxiv_id: str
    citation_count: int
    reference_count: int
    fetched_at: datetime


@dataclass
class RelatedPaper:
    """Reference to a paper found via citation/recommendation lookup.

    Includes fields needed to materialize a PaperRecord directly without
    a follow-up ArXiv fetch (abstract, authors, year). Some papers won't
    have an arxiv_id (off-arxiv venues) or won't have an abstract; the
    executor filters these out before inserting into paper_pool.
    """
    arxiv_id: Optional[str]
    title: str
    abstract: Optional[str] = None
    authors: list[str] = None  # type: ignore[assignment]
    ss_paper_id: Optional[str] = None
    year: Optional[int] = None
    citation_count: Optional[int] = None

    def __post_init__(self):
        if self.authors is None:
            self.authors = []


class CitationProvider(ABC):
    """Abstract base. Concrete impls: SemanticScholarProvider, NullProvider, OpenAlexProvider (v2)."""

    @abstractmethod
    async def get_paper(self, arxiv_id: str) -> Optional[PaperCitationInfo]:
        """Return citation_count + reference_count metadata, or None on failure/unavailable."""

    @abstractmethod
    async def get_references(
        self, arxiv_id: str, limit: int = 20
    ) -> list[RelatedPaper]:
        """Return papers this paper cites (backward expansion)."""

    @abstractmethod
    async def get_citations(
        self, arxiv_id: str, limit: int = 20
    ) -> list[RelatedPaper]:
        """Return papers that cite this paper (forward expansion)."""

    @abstractmethod
    async def get_related(self, arxiv_id: str, limit: int = 10) -> list[RelatedPaper]:
        """Return semantically similar papers (recommendations)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider is currently usable (False after degradation)."""


class NullProvider(CitationProvider):
    """Returns empty values for everything. Used when citation_provider: none."""

    async def get_paper(self, arxiv_id: str) -> Optional[PaperCitationInfo]:
        return None

    async def get_references(self, arxiv_id: str, limit: int = 20) -> list[RelatedPaper]:
        return []

    async def get_citations(self, arxiv_id: str, limit: int = 20) -> list[RelatedPaper]:
        return []

    async def get_related(self, arxiv_id: str, limit: int = 10) -> list[RelatedPaper]:
        return []

    def is_available(self) -> bool:
        return False


__all__ = [
    "CitationProvider",
    "NullProvider",
    "PaperCitationInfo",
    "RelatedPaper",
]
