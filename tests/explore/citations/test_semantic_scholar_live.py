"""Live tests against api.semanticscholar.org. @pytest.mark.network.

Free tier (no API key): 1 req/sec rate limit shared globally — so all
three tests share a single provider (module-scoped fixture) which has a
single rate limiter to space requests properly.

Hits a single canonical paper (Attention Is All You Need, arXiv:1706.03762).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src.explore.citations.semantic_scholar import SemanticScholarProvider


pytestmark = pytest.mark.network

CANONICAL_ARXIV_ID = "1706.03762"  # Vaswani et al., Attention Is All You Need


@pytest.fixture(scope="module")
def ss_provider():
    """One provider for the whole module so its rate limiter spans all tests."""
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY") or None
    return SemanticScholarProvider(api_key=api_key)


async def test_get_paper_returns_real_metadata(ss_provider):
    info = await ss_provider.get_paper(CANONICAL_ARXIV_ID)
    if info is None:
        # Transient 429 / SS unavailable — not a code defect.
        pytest.skip("SS returned no data (likely rate-limited or service issue)")
    assert info.arxiv_id == CANONICAL_ARXIV_ID
    # The paper has tens of thousands of citations as of 2024+
    assert info.citation_count > 1000
    assert info.reference_count > 0


async def test_get_references_returns_actual_papers(ss_provider):
    refs = await ss_provider.get_references(CANONICAL_ARXIV_ID, limit=5)
    if not refs:
        pytest.skip("SS returned empty references (likely rate-limited)")
    # Most refs should have a title
    assert all(r.title for r in refs)
    # At least one ref should have an arxiv_id (Transformer cites well-known arxiv work)
    assert any(r.arxiv_id is not None for r in refs)
    # Author parsing works
    populated = [r for r in refs if r.authors]
    assert len(populated) > 0, "Expected at least one ref with authors populated"


async def test_get_citations_returns_actual_papers(ss_provider):
    cits = await ss_provider.get_citations(CANONICAL_ARXIV_ID, limit=5)
    if not cits:
        pytest.skip("SS returned empty citations (likely rate-limited)")
    assert all(c.title for c in cits)
