from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

import arxiv

from src.survey.topic_discover import RawDiscoveryPaper

SleepFunc = Callable[[float], Awaitable[None]]
RATE_LIMIT_STATUS_CODES = {429, 503}


class ArxivRateLimitError(RuntimeError):
    def __init__(
        self,
        *,
        query_name: str,
        status: int,
        attempts: int,
        message: str,
    ) -> None:
        super().__init__(message)
        self.query_name = query_name
        self.status = status
        self.attempts = attempts


def convert_arxiv_result(
    result: Any,
    query_name: str,
    query_purpose: str,
) -> RawDiscoveryPaper:
    arxiv_id = _normalize_arxiv_id(result.entry_id)
    return RawDiscoveryPaper(
        arxiv_id=arxiv_id,
        title=result.title.strip(),
        abstract=result.summary.strip(),
        authors=[author.name for author in result.authors],
        published=result.published,
        categories=list(result.categories),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        query_name=query_name,
        query_purpose=query_purpose,
    )


class ArxivDiscoveryProvider:
    def __init__(
        self,
        *,
        client: Any | None = None,
        page_size: int = 10,
        delay_seconds: float = 5.0,
        rate_limit_backoff_seconds: tuple[float, ...] = (30.0, 60.0, 120.0),
        sleep: SleepFunc | None = None,
    ) -> None:
        self.client = client or arxiv.Client(
            page_size=page_size,
            delay_seconds=delay_seconds,
            num_retries=0,
        )
        self.client.page_size = page_size
        self.client.delay_seconds = delay_seconds
        self.client.num_retries = 0
        self.max_page_size = page_size
        self.rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self.sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()

    async def search(
        self,
        query: str,
        query_name: str,
        query_purpose: str,
        max_results: int,
        sort: str,
    ) -> list[RawDiscoveryPaper]:
        sort_by = (
            arxiv.SortCriterion.Relevance
            if sort == "relevance"
            else arxiv.SortCriterion.SubmittedDate
        )
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=arxiv.SortOrder.Descending,
        )
        async with self._lock:
            self.client.page_size = min(max_results, self.max_page_size)
            results = await self._search_with_rate_limit_backoff(search, query_name)
        return [
            convert_arxiv_result(
                result,
                query_name=query_name,
                query_purpose=query_purpose,
            )
            for result in results
        ]

    async def _search_with_rate_limit_backoff(
        self,
        search: arxiv.Search,
        query_name: str,
    ) -> list[Any]:
        attempts = len(self.rate_limit_backoff_seconds) + 1
        last_error: arxiv.HTTPError | None = None
        for attempt_index in range(attempts):
            try:
                return await asyncio.to_thread(lambda: list(self.client.results(search)))
            except arxiv.HTTPError as exc:
                if exc.status not in RATE_LIMIT_STATUS_CODES:
                    raise
                last_error = exc
                if attempt_index >= len(self.rate_limit_backoff_seconds):
                    break
                await self.sleep(self.rate_limit_backoff_seconds[attempt_index])

        status = last_error.status if last_error is not None else 0
        raise ArxivRateLimitError(
            query_name=query_name,
            status=status,
            attempts=attempts,
            message=(
                f"arXiv API rate limited query {query_name} with HTTP {status} "
                f"after {attempts} attempts"
            ),
        )


def _normalize_arxiv_id(entry_id: str) -> str:
    raw_id = entry_id.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", raw_id)
