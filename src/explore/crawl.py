"""ArXiv search wrapper for Explorer.

Thin wrapper over arxiv.Client, tailored for Explorer's needs:
  - No date cutoff (Explorer searches classic + recent)
  - No SearchTopic coupling
  - Flexible categories, max_results, date_range, sort_by

Separate from src.crawl.ArxivScraper which is tied to the main pipeline's
SearchTopic + config-based filtering.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

import arxiv


logger = logging.getLogger(__name__)


class ExplorerSearcher:
    """Explorer-facing ArXiv search. Returns raw dicts (no Paper / SearchTopic coupling)."""

    def __init__(self, delay_seconds: float = 3.0, num_retries: int = 3):
        self._client = arxiv.Client(
            page_size=100,
            delay_seconds=delay_seconds,
            num_retries=num_retries,
        )

    async def search(
        self,
        *,
        query: str,
        categories: Optional[list[str]] = None,
        max_results: int = 20,
        date_range: Optional[tuple[date, date]] = None,
        sort_by: str = "relevance",
    ) -> list[dict]:
        """Run a single ArXiv query.

        Returns a list of dicts with: arxiv_id, title, abstract, authors,
        published (date), categories, pdf_url.
        """
        categories = categories or []

        # Build full query with category filter
        if categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in categories)
            full_query = f"({cat_filter}) AND ({query})"
        else:
            full_query = query

        sort_map = {
            "relevance": arxiv.SortCriterion.Relevance,
            "date": arxiv.SortCriterion.SubmittedDate,
        }
        if sort_by not in sort_map:
            raise ValueError(f"sort_by must be 'relevance' or 'date', got {sort_by!r}")

        search = arxiv.Search(
            query=full_query,
            max_results=max_results,
            sort_by=sort_map[sort_by],
        )

        logger.info(
            "[explore] ArXiv search: query=%r cats=%s max=%d",
            query,
            categories,
            max_results,
        )

        try:
            results = await asyncio.to_thread(
                lambda: list(self._client.results(search))
            )
        except Exception as e:
            logger.error("[explore] ArXiv search failed: %s", e)
            return []

        out: list[dict] = []
        for r in results:
            pub = r.published.date() if hasattr(r.published, "date") else r.published

            if date_range is not None:
                lo, hi = date_range
                if not (lo <= pub <= hi):
                    continue

            arxiv_id_full = r.entry_id.split("/abs/")[-1]
            out.append(
                {
                    "arxiv_id": arxiv_id_full,
                    "title": r.title.strip(),
                    "abstract": r.summary.strip(),
                    "authors": [a.name for a in r.authors],
                    "published": pub,
                    "categories": list(r.categories),
                    "pdf_url": r.pdf_url,
                }
            )

        logger.info("[explore] ArXiv returned %d (post-filter)", len(out))
        return out
