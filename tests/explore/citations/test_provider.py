"""Deterministic tests for the provider layer (NullProvider + factory + helpers)."""

from __future__ import annotations

import pytest

from src.explore.citations import (
    CitationProvider,
    NullProvider,
    SemanticScholarProvider,
    make_provider_from_env,
    normalize_arxiv_id,
)


# —— NullProvider ——————————————————————————————


async def test_null_provider_returns_empty_for_all_methods():
    p = NullProvider()
    assert await p.get_paper("2401.00001") is None
    assert await p.get_references("2401.00001") == []
    assert await p.get_citations("2401.00001") == []
    assert await p.get_related("2401.00001") == []
    assert p.is_available() is False


def test_null_provider_is_a_citation_provider():
    assert isinstance(NullProvider(), CitationProvider)


# —— normalize_arxiv_id ——————————————————————————


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2401.12345", "2401.12345"),
        ("2401.12345v1", "2401.12345"),
        ("2401.12345v3", "2401.12345"),
        ("  2401.12345v2  ", "2401.12345"),
        ("1706.03762v5", "1706.03762"),
    ],
)
def test_normalize_arxiv_id_strips_version_and_whitespace(raw, expected):
    assert normalize_arxiv_id(raw) == expected


# —— make_provider_from_env ——————————————————————


def test_factory_default_is_semantic_scholar():
    p = make_provider_from_env({})
    assert isinstance(p, SemanticScholarProvider)


def test_factory_with_explicit_none_returns_null():
    p = make_provider_from_env({"EXPLORE_CITATION_PROVIDER": "none"})
    assert isinstance(p, NullProvider)


def test_factory_with_explicit_semantic_scholar():
    p = make_provider_from_env({
        "EXPLORE_CITATION_PROVIDER": "semantic_scholar",
        "SEMANTIC_SCHOLAR_API_KEY": "test-key",
    })
    assert isinstance(p, SemanticScholarProvider)
    assert p.api_key == "test-key"


def test_factory_unknown_kind_raises():
    with pytest.raises(ValueError):
        make_provider_from_env({"EXPLORE_CITATION_PROVIDER": "openalex"})  # M6 v1 not supported
