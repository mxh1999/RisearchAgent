import asyncio
import logging
from datetime import datetime, timedelta, timezone

import arxiv

from src.config import ScraperConfig
from src.models import Paper, SearchTopic

logger = logging.getLogger(__name__)


class ArxivScraper:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=config.delay_seconds,
            num_retries=3,
        )

    async def fetch_topic(self, topic: SearchTopic) -> list[Paper]:
        """Fetch latest papers for a single topic."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.days_lookback)

        search = arxiv.Search(
            query=topic.query,
            max_results=self.config.max_results_per_topic,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        results = await asyncio.to_thread(
            lambda: list(self.client.results(search))
        )

        papers = []
        for result in results:
            pub_date = result.published.replace(tzinfo=timezone.utc)
            if pub_date < cutoff:
                continue

            paper = Paper(
                arxiv_id=result.entry_id.split("/abs/")[-1],
                title=result.title.strip(),
                abstract=result.summary.strip(),
                authors=[a.name for a in result.authors],
                pdf_url=result.pdf_url,
                published=pub_date,
                categories=result.categories,
                source_topic=topic.name,
            )
            papers.append(paper)

        logger.info(f"[{topic.name}] Fetched {len(papers)} papers")
        return papers

    async def fetch_all(self, topics: list[SearchTopic]) -> list[Paper]:
        """Fetch all topics concurrently, deduplicate by arxiv_id."""
        tasks = [self.fetch_topic(topic) for topic in topics]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers = []
        for topic, result in zip(topics, results):
            if isinstance(result, Exception):
                logger.error(f"[{topic.name}] Fetch failed: {result}")
                continue
            all_papers.extend(result)

        seen: dict[str, Paper] = {}
        for paper in all_papers:
            if paper.arxiv_id not in seen:
                seen[paper.arxiv_id] = paper

        deduplicated = list(seen.values())
        logger.info(f"Total {len(deduplicated)} unique papers (from {len(all_papers)} raw)")
        return deduplicated
