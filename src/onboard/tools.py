"""Tool functions for the onboarding research advisor.

These functions are called by Gemini Pro via AFC (Automatic Function Calling)
during the interactive onboarding conversation. They wrap existing pipeline
components to provide search, reading, and configuration capabilities.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import arxiv
import yaml

from src.config import AppConfig, LLMConfig, ScraperConfig
from src.crawl.pdf_downloader import PDFDownloader
from src.crawl.scraper import ArxivScraper
from src.models import SearchTopic
from src.reader.deep_reader import DeepReader
from src.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class OnboardTools:
    """Tool implementations for the research advisor.

    Each public method can be registered as a Gemini AFC tool function.
    The methods are sync wrappers that run async code internally,
    because google-genai AFC expects regular functions.
    """

    def __init__(
        self,
        llm: GeminiClient,
        llm_config: LLMConfig,
        pdf_dir: Path = Path("data/pdfs"),
        config_path: str = "config.yaml",
        sota_dir: Path = Path("data/sota"),
    ):
        self.llm = llm
        self.llm_config = llm_config
        self.pdf_downloader = PDFDownloader(pdf_dir)
        self.config_path = config_path
        self.sota_dir = sota_dir
        self._reader: Optional[DeepReader] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def reader(self) -> DeepReader:
        if self._reader is None:
            self._reader = DeepReader(self.llm, self.llm_config)
        return self._reader

    def _run_async(self, coro):
        """Run an async coroutine from a sync context.

        AFC tool functions must be synchronous, but our components are async.
        We use the existing event loop if available.
        """
        try:
            loop = asyncio.get_running_loop()
            # We're inside an async context; create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            # No running loop, safe to use asyncio.run
            return asyncio.run(coro)

    def search_arxiv(
        self,
        query: str,
        categories: list[str],
        max_results: int = 10,
    ) -> list[dict]:
        """Search ArXiv for papers matching query within given categories.

        Args:
            query: Search query string (e.g., "zero-shot object navigation")
            categories: ArXiv categories to search within (e.g., ["cs.RO", "cs.CV"])
            max_results: Maximum number of results to return (default 10)

        Returns:
            List of paper dicts with keys: arxiv_id, title, abstract, authors, published
        """
        logger.info(f"[onboard] Searching ArXiv: query={query!r}, categories={categories}")

        # Build category-filtered query
        if categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in categories)
            full_query = f"({cat_filter}) AND ({query})"
        else:
            full_query = query

        search = arxiv.Search(
            query=full_query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        client = arxiv.Client(
            page_size=100,
            delay_seconds=3.0,
            num_retries=3,
        )

        results = list(client.results(search))

        papers = []
        for r in results:
            papers.append({
                "arxiv_id": r.entry_id.split("/abs/")[-1],
                "title": r.title.strip(),
                "abstract": r.summary.strip()[:500],  # Truncate for readability
                "authors": [a.name for a in r.authors[:5]],  # Top 5 authors
                "published": r.published.strftime("%Y-%m-%d"),
            })

        logger.info(f"[onboard] Found {len(papers)} papers")
        return papers

    def fetch_paper(self, arxiv_id: str) -> dict:
        """Fetch full metadata for a specific ArXiv paper by ID.

        Args:
            arxiv_id: ArXiv paper ID (e.g., "2401.12345")

        Returns:
            Dict with keys: arxiv_id, title, abstract, authors, published,
            categories, pdf_url
        """
        logger.info(f"[onboard] Fetching paper: {arxiv_id}")

        search = arxiv.Search(id_list=[arxiv_id])
        client = arxiv.Client(delay_seconds=3.0, num_retries=3)
        results = list(client.results(search))

        if not results:
            return {"error": f"Paper {arxiv_id} not found"}

        r = results[0]
        return {
            "arxiv_id": r.entry_id.split("/abs/")[-1],
            "title": r.title.strip(),
            "abstract": r.summary.strip(),
            "authors": [a.name for a in r.authors],
            "published": r.published.strftime("%Y-%m-%d"),
            "categories": r.categories,
            "pdf_url": r.pdf_url,
        }

    def read_paper_experiments(self, arxiv_id: str) -> dict:
        """Deep-read a paper and extract experimental results.

        Downloads the PDF, extracts text, and uses LLM to analyze experiments.

        Args:
            arxiv_id: ArXiv paper ID (e.g., "2401.12345")

        Returns:
            Dict with keys: benchmarks (list of benchmark results), method_summary
        """
        logger.info(f"[onboard] Deep-reading paper experiments: {arxiv_id}")

        async def _read():
            # First fetch paper metadata for PDF URL
            paper_info = self.fetch_paper(arxiv_id)
            if "error" in paper_info:
                return paper_info

            pdf_url = paper_info.get("pdf_url")
            if not pdf_url:
                return {"error": f"No PDF URL for {arxiv_id}"}

            # Download and extract text
            full_text = await self.pdf_downloader.extract_text(arxiv_id, pdf_url)

            # Deep read
            reading = await self.reader.read_paper(
                arxiv_id, paper_info["title"], full_text
            )

            if not reading:
                return {"error": "Failed to extract experiment data"}

            # Format experiment results for Gemini
            benchmarks = []
            if reading.experiment_table and reading.experiment_table.entries:
                for entry in reading.experiment_table.entries:
                    arrow = "higher" if entry.higher_is_better else "lower"
                    results = []
                    for r in entry.results:
                        results.append({
                            "method": r.method_name,
                            "value": r.value,
                            "is_paper_method": r.is_paper_method,
                        })
                    benchmarks.append({
                        "benchmark": entry.benchmark,
                        "setting": entry.setting,
                        "metric": entry.metric,
                        "better": arrow,
                        "results": results,
                    })

            return {
                "benchmarks": benchmarks,
                "method_summary": reading.proposed_method,
                "experimental_setup": reading.experimental_setup,
                "main_results": reading.main_results,
            }

        return self._run_async(_read())

    def save_onboard_result(
        self,
        research_profile: str,
        topics: list[dict],
        relevance_threshold: int,
        anchor_paper_ids: list[str],
        classic_baselines: list[dict],
    ) -> str:
        """Save the finalized research profile and topics to config.yaml.

        Also seeds the SOTA knowledge base by deep-reading anchor papers.

        Args:
            research_profile: Detailed description of research interests (150-250 words)
            topics: List of topic dicts, each with keys:
                - name: Topic display name
                - query: ArXiv search query
                - categories: List of ArXiv categories
            relevance_threshold: Score threshold for paper filtering (4-8)
            anchor_paper_ids: List of ArXiv IDs for key papers to deep-read
            classic_baselines: List of dicts with keys:
                - arxiv_id: ArXiv paper ID
                - title: Paper title
                - why_classic: Why this paper is a classic baseline

        Returns:
            Summary of what was saved
        """
        logger.info("[onboard] Saving onboarding results")

        # Build config YAML structure
        yaml_topics = []
        for t in topics:
            # Build category-enhanced query
            cats = t.get("categories", [])
            raw_query = t.get("query", "")

            # If query doesn't already have category filters, add them
            if cats and "cat:" not in raw_query:
                cat_filter = " OR ".join(f"cat:{c}" for c in cats)
                full_query = f"({cat_filter}) AND ({raw_query})"
            else:
                full_query = raw_query

            yaml_topics.append({
                "name": t["name"],
                "query": full_query,
                "categories": cats,
                "research_profile": research_profile,
            })

        # Load existing config or create new one
        config_data = {}
        config_path = Path(self.config_path)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}

        # Update config
        config_data["topics"] = yaml_topics
        config_data.setdefault("llm", {})
        config_data["llm"].setdefault("filter_model", "gemini-2.5-flash")
        config_data["llm"].setdefault("reader_model", "gemini-2.5-pro")
        config_data["llm"].setdefault("embedding_model", "gemini-embedding-001")
        config_data["llm"].setdefault("max_concurrent", 5)
        config_data["llm"].setdefault("temperature", 0.3)

        config_data.setdefault("scraper", {})
        config_data["scraper"].setdefault("max_results_per_topic", 20)
        config_data["scraper"].setdefault("delay_seconds", 3.0)
        config_data["scraper"].setdefault("days_lookback", 30)

        config_data.setdefault("filter", {})
        config_data["filter"]["relevance_threshold"] = relevance_threshold
        config_data["filter"].setdefault("borderline_min", max(relevance_threshold - 2, 2))

        config_data.setdefault("db_path", "data/papers.db")
        config_data.setdefault("chroma_path", "data/chroma")
        config_data.setdefault("pdf_dir", "data/pdfs")
        config_data.setdefault("sota_dir", "data/sota")

        # Write config
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False, width=120)

        summary_parts = [
            f"config.yaml updated with {len(yaml_topics)} topics",
            f"relevance_threshold set to {relevance_threshold}",
        ]

        # Seed SOTA by reading anchor papers
        if anchor_paper_ids:
            async def _seed_sota():
                seeded = []
                for aid in anchor_paper_ids:
                    try:
                        result = self.read_paper_experiments(aid)
                        if "error" not in result and result.get("benchmarks"):
                            seeded.append(aid)
                    except Exception as e:
                        logger.warning(f"Failed to seed SOTA from {aid}: {e}")
                return seeded

            seeded = self._run_async(_seed_sota())
            if seeded:
                summary_parts.append(
                    f"Deep-read {len(seeded)} anchor papers for SOTA seeding"
                )

        # Save classic baselines info as a reference file
        if classic_baselines:
            baselines_path = Path(config_data.get("sota_dir", "data/sota")) / "classic_baselines.md"
            baselines_path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["# Classic Baselines\n"]
            for b in classic_baselines:
                lines.append(f"## {b.get('title', 'Unknown')}")
                lines.append(f"- ArXiv ID: {b.get('arxiv_id', 'N/A')}")
                lines.append(f"- Why classic: {b.get('why_classic', 'N/A')}")
                lines.append("")
            baselines_path.write_text("\n".join(lines), encoding="utf-8")
            summary_parts.append(f"Saved {len(classic_baselines)} classic baselines")

        summary = "\n".join(f"- {s}" for s in summary_parts)
        logger.info(f"[onboard] Save complete:\n{summary}")
        return f"Setup complete!\n{summary}"
