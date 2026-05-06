"""Integration tests for executor's fetch_citations + fetch_related handlers.

Uses a mock CitationProvider (not real Semantic Scholar) so these tests are
deterministic. Live SS tests live in test_semantic_scholar_live.py.
"""

from __future__ import annotations

from typing import Optional

import pytest

from src.explore.actions import (
    FetchCitationsAction,
    FetchRelatedAction,
)
from src.explore.citations import CitationProvider, NullProvider, RelatedPaper
from src.explore.executor import ActionExecutor
from tests.explore.conftest import make_state


class MockCitationProvider(CitationProvider):
    """Returns predetermined RelatedPaper lists; tracks calls for assertions."""

    def __init__(
        self,
        paper=None,
        references: Optional[list[RelatedPaper]] = None,
        citations: Optional[list[RelatedPaper]] = None,
        related: Optional[list[RelatedPaper]] = None,
    ):
        self.paper = paper
        self.references = references or []
        self.citations = citations or []
        self.related = related or []
        self.calls: list[tuple[str, str]] = []

    async def get_paper(self, arxiv_id):
        self.calls.append(("get_paper", arxiv_id))
        return self.paper

    async def get_references(self, arxiv_id, limit=20):
        self.calls.append(("get_references", arxiv_id))
        return self.references

    async def get_citations(self, arxiv_id, limit=20):
        self.calls.append(("get_citations", arxiv_id))
        return self.citations

    async def get_related(self, arxiv_id, limit=10):
        self.calls.append(("get_related", arxiv_id))
        return self.related

    def is_available(self):
        return True


def _rp(arxiv_id: str, *, abstract: str = "abs", authors=("A",), year: int = 2024):
    return RelatedPaper(
        arxiv_id=arxiv_id,
        title=f"Title {arxiv_id}",
        abstract=abstract,
        authors=list(authors),
        year=year,
        citation_count=10,
    )


# —————————————————————————————————————————————————————————————
# fetch_citations
# —————————————————————————————————————————————————————————————


async def test_fetch_citations_with_null_provider_returns_stub():
    state = make_state()
    executor = ActionExecutor(citations=NullProvider())
    action = FetchCitationsAction(
        arxiv_id="1706.03762", direction="references",
        reasoning="test: provider unavailable should yield stub",
    )
    result = await executor.execute(action, state)
    assert result.success is True
    assert "stub" in result.summary
    assert state.paper_pool == {}


async def test_fetch_citations_references_populates_pool():
    provider = MockCitationProvider(
        references=[_rp("2401.00001"), _rp("2401.00002")]
    )
    state = make_state()
    executor = ActionExecutor(citations=provider)
    action = FetchCitationsAction(
        arxiv_id="1706.03762", direction="references",
        reasoning="test: references should populate pool",
    )
    result = await executor.execute(action, state)
    assert result.success is True
    assert result.details["n_new"] == 2
    assert result.details["direction"] == "references"
    assert "2401.00001" in state.paper_pool
    p = state.paper_pool["2401.00001"]
    assert p.source == "citation_expansion"
    assert p.source_paper_id == "1706.03762"
    assert p.citation_count == 10
    # author counter populated
    assert "A" in state.counters.author_counter
    # query_log entry recorded with citation_seeded
    assert len(state.query_log) == 1
    assert state.query_log[0].source == "citation_seeded"
    # Provider called only references, not citations
    assert ("get_references", "1706.03762") in provider.calls
    assert ("get_citations", "1706.03762") not in provider.calls


async def test_fetch_citations_both_calls_both_endpoints():
    provider = MockCitationProvider(
        references=[_rp("2401.00001")],
        citations=[_rp("2401.00002")],
    )
    state = make_state()
    executor = ActionExecutor(citations=provider)
    action = FetchCitationsAction(
        arxiv_id="1706.03762", direction="both",
        reasoning="test: both directions",
    )
    result = await executor.execute(action, state)
    assert result.success is True
    assert result.details["n_new"] == 2
    assert ("get_references", "1706.03762") in provider.calls
    assert ("get_citations", "1706.03762") in provider.calls


async def test_fetch_citations_skips_papers_without_arxiv_id_or_abstract():
    """Papers from SS that lack arxiv_id or abstract are unusable for our pipeline."""
    provider = MockCitationProvider(references=[
        _rp("2401.00001", abstract="ok"),                  # usable
        RelatedPaper(arxiv_id=None, title="No arxiv", abstract="x"),  # no arxiv_id → skip
        RelatedPaper(arxiv_id="2401.00003", title="No abs"),          # no abstract → skip
    ])
    state = make_state()
    executor = ActionExecutor(citations=provider)
    action = FetchCitationsAction(
        arxiv_id="1706.03762", direction="references",
        reasoning="test: filter unusable entries",
    )
    result = await executor.execute(action, state)
    assert result.details["n_returned"] == 3
    assert result.details["n_new"] == 1
    assert "2401.00001" in state.paper_pool
    assert "2401.00003" not in state.paper_pool


async def test_fetch_citations_dedupes_against_pool():
    """Papers already in pool should NOT be re-added."""
    provider = MockCitationProvider(references=[_rp("2401.00001"), _rp("2401.00002")])
    state = make_state()
    # Pre-populate pool with one of them
    from datetime import date
    from src.explore.state import PaperRecord

    state.paper_pool["2401.00001"] = PaperRecord(
        arxiv_id="2401.00001",
        title="already",
        abstract="present",
        authors=["X"],
        published=date(2024, 1, 1),
        categories=[],
        pdf_url="",
        first_seen_turn=1,
        source="search",
    )
    executor = ActionExecutor(citations=provider)
    action = FetchCitationsAction(
        arxiv_id="1706.03762", direction="references",
        reasoning="test: dedupe against pool",
    )
    result = await executor.execute(action, state)
    assert result.details["n_new"] == 1
    assert "2401.00002" in state.paper_pool


# —————————————————————————————————————————————————————————————
# fetch_related
# —————————————————————————————————————————————————————————————


async def test_fetch_related_populates_pool_with_source_related():
    provider = MockCitationProvider(related=[_rp("2401.00001")])
    state = make_state()
    executor = ActionExecutor(citations=provider)
    action = FetchRelatedAction(
        arxiv_id="1706.03762",
        reasoning="test: related papers populate with source=related",
    )
    result = await executor.execute(action, state)
    assert result.success is True
    assert state.paper_pool["2401.00001"].source == "related"
    assert state.paper_pool["2401.00001"].source_paper_id == "1706.03762"
    assert ("get_related", "1706.03762") in provider.calls


async def test_fetch_related_with_null_provider_returns_stub():
    state = make_state()
    executor = ActionExecutor(citations=NullProvider())
    action = FetchRelatedAction(
        arxiv_id="1706.03762",
        reasoning="test: null provider yields stub",
    )
    result = await executor.execute(action, state)
    assert "stub" in result.summary
    assert state.paper_pool == {}
