"""Deterministic tests for SemanticScholarProvider.

Uses httpx.MockTransport to inject canned responses so we test parsing,
caching, degradation, and error handling without hitting the network.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import httpx
import pytest

from src.explore.citations.semantic_scholar import (
    DEGRADE_AFTER_CONSECUTIVE_ERRORS,
    SemanticScholarProvider,
)


# —————————————————————————————————————————————————————————————
# Helpers
# —————————————————————————————————————————————————————————————


def _patch_client(provider: SemanticScholarProvider, handler: Callable):
    """Monkey-patch SS provider's _request to use a MockTransport client."""
    transport = httpx.MockTransport(handler)
    original_request = provider._request

    async def patched_request(path, *, params=None):
        url = f"{provider.base_url}{path}"
        async with provider._limiter:
            try:
                async with httpx.AsyncClient(transport=transport, timeout=provider.timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    provider._on_success()
                    return resp.json()
            except (httpx.HTTPError, ValueError) as e:
                provider._on_error(e, url)
                from src.explore.citations.semantic_scholar import _SSError
                raise _SSError(str(e)) from e

    provider._request = patched_request  # type: ignore[method-assign]


def _paper_response(arxiv_id: str = "1706.03762", *, citations: int = 100, refs: int = 30):
    """Mock the /graph/v1/paper/arXiv:{id} response shape."""
    return {
        "paperId": "ss-paper-id",
        "title": "Attention Is All You Need",
        "citationCount": citations,
        "referenceCount": refs,
        "externalIds": {"ArXiv": arxiv_id},
    }


def _related_payload(*, key: str = "citedPaper", n: int = 3):
    """Mock /references or /citations response shape."""
    return {
        "data": [
            {
                key: {
                    "paperId": f"ss-{i}",
                    "title": f"Cited paper {i}",
                    "abstract": f"Abstract for paper {i}",
                    "authors": [{"name": f"Author {i}"}],
                    "year": 2020 + i,
                    "citationCount": 10 + i,
                    "externalIds": {"ArXiv": f"24{i:02d}.{i:05d}"},
                }
            }
            for i in range(n)
        ]
    }


# —————————————————————————————————————————————————————————————
# get_paper
# —————————————————————————————————————————————————————————————


async def test_get_paper_parses_response():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        assert "arXiv:1706.03762" in req.url.path
        return httpx.Response(200, json=_paper_response("1706.03762", citations=42, refs=15))

    _patch_client(p, handler)
    info = await p.get_paper("1706.03762v1")  # version stripped
    assert info is not None
    assert info.arxiv_id == "1706.03762"
    assert info.citation_count == 42
    assert info.reference_count == 15


async def test_get_paper_cache_dedupes_calls():
    p = SemanticScholarProvider()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_paper_response())

    _patch_client(p, handler)
    a = await p.get_paper("1706.03762")
    b = await p.get_paper("1706.03762")  # second call should be cached
    c = await p.get_paper("1706.03762v2")  # version stripped → same canonical id
    assert calls["n"] == 1
    assert a == b == c


async def test_get_paper_returns_none_on_404():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    _patch_client(p, handler)
    assert await p.get_paper("9999.99999") is None
    assert p._consecutive_errors == 1


# —————————————————————————————————————————————————————————————
# Degradation
# —————————————————————————————————————————————————————————————


async def test_degrades_after_consecutive_errors():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    _patch_client(p, handler)
    for _ in range(DEGRADE_AFTER_CONSECUTIVE_ERRORS):
        await p.get_paper("1706.03762")  # different IDs -> bypass cache
    # After threshold, provider is degraded:
    assert p.is_available() is False
    # Subsequent calls return None without HTTP
    assert await p.get_paper("1706.03762") is None
    assert await p.get_references("1706.03762") == []
    assert await p.get_citations("1706.03762") == []
    assert await p.get_related("1706.03762") == []


async def test_success_resets_consecutive_error_counter():
    p = SemanticScholarProvider()
    state = {"call": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["call"] += 1
        # First two calls fail, then succeed
        if state["call"] <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json=_paper_response())

    _patch_client(p, handler)
    # 2 errors — under threshold
    await p.get_paper("9999.00001")
    await p.get_paper("9999.00002")
    assert p._consecutive_errors == 2
    assert p.is_available() is True
    # Success
    await p.get_paper("1706.03762")
    assert p._consecutive_errors == 0


# —————————————————————————————————————————————————————————————
# get_references / get_citations parsing
# —————————————————————————————————————————————————————————————


async def test_get_references_parses_papers_with_full_metadata():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_related_payload(key="citedPaper", n=3))

    _patch_client(p, handler)
    refs = await p.get_references("1706.03762", limit=20)
    assert len(refs) == 3
    r = refs[0]
    assert r.arxiv_id == "2400.00000"
    assert r.title == "Cited paper 0"
    assert r.abstract == "Abstract for paper 0"
    assert r.authors == ["Author 0"]
    assert r.year == 2020
    assert r.citation_count == 10
    assert r.ss_paper_id == "ss-0"


async def test_get_citations_uses_citingPaper_key():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_related_payload(key="citingPaper", n=2))

    _patch_client(p, handler)
    cits = await p.get_citations("1706.03762")
    assert len(cits) == 2
    assert all(c.title.startswith("Cited paper ") for c in cits)


async def test_parser_filters_papers_without_title():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"citedPaper": {"title": "", "externalIds": {"ArXiv": "2401.00001"}}},
            {"citedPaper": {"title": "OK paper", "externalIds": {"ArXiv": "2401.00002"}}},
        ]})

    _patch_client(p, handler)
    refs = await p.get_references("1706.03762")
    assert len(refs) == 1
    assert refs[0].title == "OK paper"


async def test_parser_handles_paper_without_arxiv_id():
    p = SemanticScholarProvider()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [
            {"citedPaper": {
                "title": "Off-arxiv paper",
                "externalIds": {"DOI": "10.1234/foo"},  # no ArXiv key
                "year": 2020,
            }},
        ]})

    _patch_client(p, handler)
    refs = await p.get_references("1706.03762")
    assert len(refs) == 1
    assert refs[0].arxiv_id is None
    assert refs[0].title == "Off-arxiv paper"


# —————————————————————————————————————————————————————————————
# get_related
# —————————————————————————————————————————————————————————————


async def test_get_related_uses_recommendations_endpoint():
    p = SemanticScholarProvider()
    seen_paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_paths.append(req.url.path)
        return httpx.Response(200, json={
            "recommendedPapers": [
                {
                    "paperId": "ss-r1",
                    "title": "Related paper",
                    "abstract": "Related abstract",
                    "authors": [{"name": "Recommender"}],
                    "year": 2024,
                    "externalIds": {"ArXiv": "2404.99999"},
                },
            ]
        })

    _patch_client(p, handler)
    rel = await p.get_related("1706.03762")
    assert len(seen_paths) == 1
    assert "/recommendations/v1/papers/forpaper/" in seen_paths[0]
    assert len(rel) == 1
    assert rel[0].arxiv_id == "2404.99999"


# —————————————————————————————————————————————————————————————
# Caching across endpoint methods
# —————————————————————————————————————————————————————————————


async def test_references_cache_distinguishes_by_limit():
    p = SemanticScholarProvider()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_related_payload(n=5))

    _patch_client(p, handler)
    await p.get_references("1706.03762", limit=10)
    await p.get_references("1706.03762", limit=10)  # cached
    await p.get_references("1706.03762", limit=20)  # different limit → not cached
    assert calls["n"] == 2
