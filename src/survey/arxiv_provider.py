from __future__ import annotations

import asyncio
import re
from typing import Any

import arxiv

from src.survey.topic_discover import RawDiscoveryPaper


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
    def __init__(self) -> None:
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=3.0,
            num_retries=3,
        )

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
        results = await asyncio.to_thread(lambda: list(self.client.results(search)))
        return [
            convert_arxiv_result(
                result,
                query_name=query_name,
                query_purpose=query_purpose,
            )
            for result in results
        ]


def _normalize_arxiv_id(entry_id: str) -> str:
    raw_id = entry_id.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", raw_id)
