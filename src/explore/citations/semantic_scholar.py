"""Semantic Scholar implementation of CitationProvider.

Per docs/onboard-redesign/11-citation-provider.md:
  - Run-scoped memoization (no cross-run cache in v1)
  - Token bucket rate limiting (1 req/s without key, 100/s with key)
  - Graceful degradation: 3 consecutive errors → degraded for the rest of
    the run (all subsequent calls return empty/None instead of erroring)
  - ArXiv ID format: SS expects "arXiv:2401.12345" (without version suffix);
    Explorer state stores raw "2401.12345v1". We strip the version locally.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import httpx

from src.explore.citations.provider import (
    CitationProvider,
    PaperCitationInfo,
    RelatedPaper,
)
from src.explore.citations.rate_limiter import AsyncRateLimiter


logger = logging.getLogger(__name__)


SS_BASE_URL = "https://api.semanticscholar.org"
DEGRADE_AFTER_CONSECUTIVE_ERRORS = 3
RATE_LIMIT_NO_KEY = 1.0   # req / sec
RATE_LIMIT_WITH_KEY = 100.0
DEFAULT_TIMEOUT_SECONDS = 15.0


def normalize_arxiv_id(arxiv_id: str) -> str:
    """Strip version suffix. '2401.12345v2' -> '2401.12345'."""
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def _ss_id(arxiv_id: str) -> str:
    """SS lookup format for an ArXiv paper."""
    return f"arXiv:{normalize_arxiv_id(arxiv_id)}"


class SemanticScholarProvider(CitationProvider):
    """Real SS provider. Free public tier without API key works (1 req/s)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = SS_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        rate = RATE_LIMIT_WITH_KEY if api_key else RATE_LIMIT_NO_KEY
        self._limiter = AsyncRateLimiter(rate=rate, period=1.0)

        # Run-scoped caches keyed by canonical SS id ("arXiv:XXXX.XXXXX")
        self._paper_cache: dict[str, Optional[PaperCitationInfo]] = {}
        self._references_cache: dict[tuple[str, int], list[RelatedPaper]] = {}
        self._citations_cache: dict[tuple[str, int], list[RelatedPaper]] = {}
        self._related_cache: dict[tuple[str, int], list[RelatedPaper]] = {}

        self._consecutive_errors = 0
        self._degraded = False

    # —— Public CitationProvider API ——————————————————————————

    async def get_paper(self, arxiv_id: str) -> Optional[PaperCitationInfo]:
        if self._degraded:
            return None
        ssid = _ss_id(arxiv_id)
        if ssid in self._paper_cache:
            return self._paper_cache[ssid]
        try:
            data = await self._request(
                f"/graph/v1/paper/{ssid}",
                params={"fields": "citationCount,referenceCount"},
            )
        except _SSError:
            return None
        info = PaperCitationInfo(
            arxiv_id=normalize_arxiv_id(arxiv_id),
            citation_count=int(data.get("citationCount") or 0),
            reference_count=int(data.get("referenceCount") or 0),
            fetched_at=datetime.now(),
        )
        self._paper_cache[ssid] = info
        return info

    async def get_references(
        self, arxiv_id: str, limit: int = 20
    ) -> list[RelatedPaper]:
        if self._degraded:
            return []
        key = (_ss_id(arxiv_id), limit)
        if key in self._references_cache:
            return self._references_cache[key]
        try:
            data = await self._request(
                f"/graph/v1/paper/{_ss_id(arxiv_id)}/references",
                params={
                    "limit": min(max(limit, 1), 100),
                    "fields": "title,abstract,authors,year,citationCount,externalIds",
                },
            )
        except _SSError:
            return []
        result = self._parse_paper_list(data.get("data") or [], key="citedPaper")
        self._references_cache[key] = result
        return result

    async def get_citations(
        self, arxiv_id: str, limit: int = 20
    ) -> list[RelatedPaper]:
        if self._degraded:
            return []
        key = (_ss_id(arxiv_id), limit)
        if key in self._citations_cache:
            return self._citations_cache[key]
        try:
            data = await self._request(
                f"/graph/v1/paper/{_ss_id(arxiv_id)}/citations",
                params={
                    "limit": min(max(limit, 1), 100),
                    "fields": "title,abstract,authors,year,citationCount,externalIds",
                },
            )
        except _SSError:
            return []
        result = self._parse_paper_list(data.get("data") or [], key="citingPaper")
        self._citations_cache[key] = result
        return result

    async def get_related(
        self, arxiv_id: str, limit: int = 10
    ) -> list[RelatedPaper]:
        if self._degraded:
            return []
        key = (_ss_id(arxiv_id), limit)
        if key in self._related_cache:
            return self._related_cache[key]
        try:
            data = await self._request(
                f"/recommendations/v1/papers/forpaper/{_ss_id(arxiv_id)}",
                params={
                    "limit": min(max(limit, 1), 100),
                    "fields": "title,abstract,authors,year,citationCount,externalIds",
                },
            )
        except _SSError:
            return []
        # /recommendations endpoint returns recommendedPapers list directly
        items = data.get("recommendedPapers") or []
        result = self._parse_paper_list_flat(items)
        self._related_cache[key] = result
        return result

    def is_available(self) -> bool:
        return not self._degraded

    # —— HTTP machinery ——————————————————————————————

    async def _request(self, path: str, *, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        async with self._limiter:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params, headers=headers)
                    resp.raise_for_status()
                    self._on_success()
                    return resp.json()
            except (httpx.HTTPError, ValueError) as e:
                self._on_error(e, url)
                raise _SSError(str(e)) from e

    def _on_success(self) -> None:
        if self._consecutive_errors:
            self._consecutive_errors = 0

    def _on_error(self, e: Exception, url: str) -> None:
        self._consecutive_errors += 1
        logger.warning(
            "[citations.ss] request failed (%d/%d) — %s — url=%s",
            self._consecutive_errors,
            DEGRADE_AFTER_CONSECUTIVE_ERRORS,
            str(e)[:120],
            url,
        )
        if self._consecutive_errors >= DEGRADE_AFTER_CONSECUTIVE_ERRORS:
            self._degraded = True
            logger.error(
                "[citations.ss] degraded for the rest of this run after "
                "%d consecutive errors",
                self._consecutive_errors,
            )

    # —— Parsing ——————————————————————————————

    def _parse_paper_list(self, items: list[dict], *, key: str) -> list[RelatedPaper]:
        """Parse SS list responses where each entry wraps a paper under `key`.

        Used by /references (key='citedPaper') and /citations (key='citingPaper').
        """
        out: list[RelatedPaper] = []
        for entry in items:
            paper = entry.get(key) or {}
            rp = self._parse_paper(paper)
            if rp is not None:
                out.append(rp)
        return out

    def _parse_paper_list_flat(self, items: list[dict]) -> list[RelatedPaper]:
        """Parse a flat list of paper objects (used by /recommendations)."""
        out: list[RelatedPaper] = []
        for paper in items:
            rp = self._parse_paper(paper)
            if rp is not None:
                out.append(rp)
        return out

    def _parse_paper(self, paper: dict) -> Optional[RelatedPaper]:
        title = (paper.get("title") or "").strip()
        if not title:
            return None
        external = paper.get("externalIds") or {}
        arxiv_id = external.get("ArXiv")
        # SS returns authors as [{"authorId": ..., "name": ...}, ...]
        author_list = paper.get("authors") or []
        authors: list[str] = []
        for a in author_list:
            name = (a.get("name") or "").strip()
            if name:
                authors.append(name)
        abstract = paper.get("abstract") or None
        if abstract is not None:
            abstract = abstract.strip() or None
        return RelatedPaper(
            arxiv_id=normalize_arxiv_id(arxiv_id) if arxiv_id else None,
            title=title,
            abstract=abstract,
            authors=authors,
            ss_paper_id=paper.get("paperId"),
            year=paper.get("year"),
            citation_count=paper.get("citationCount"),
        )


class _SSError(RuntimeError):
    """Internal marker for SS HTTP failures so per-method handlers can return empty."""


def make_provider_from_env(env: dict[str, str]) -> CitationProvider:
    """Factory: read env vars and build the provider.

    Recognized:
      EXPLORE_CITATION_PROVIDER = "semantic_scholar" | "none"  (default: semantic_scholar)
      SEMANTIC_SCHOLAR_API_KEY = "<key>"                       (optional; raises rate limit)

    Returns NullProvider when set to "none" or when explicitly disabled.
    """
    from src.explore.citations.provider import NullProvider

    kind = (env.get("EXPLORE_CITATION_PROVIDER") or "semantic_scholar").lower()
    if kind == "none":
        return NullProvider()
    if kind == "semantic_scholar":
        return SemanticScholarProvider(
            api_key=env.get("SEMANTIC_SCHOLAR_API_KEY") or None
        )
    raise ValueError(f"Unknown citation provider: {kind!r}")


__all__ = [
    "SemanticScholarProvider",
    "make_provider_from_env",
    "normalize_arxiv_id",
    "DEGRADE_AFTER_CONSECUTIVE_ERRORS",
]
