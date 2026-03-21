import logging

from src.config import AppConfig
from src.crawl.pdf_downloader import PDFDownloader
from src.crawl.scraper import ArxivScraper
from src.filter.relevance_judge import RelevanceJudge
from src.knowledge.contribution_analyzer import ContributionAnalyzer
from src.knowledge.knowledge_base import KnowledgeBase
from src.knowledge.sota_tracker import SOTAKnowledgeBase
from src.llm.gemini_client import GeminiClient
from src.reader.deep_reader import DeepReader
from src.storage.database import Database

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Five-stage pipeline: Crawl → Filter → Read → Analyze → SOTA Update."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(config.db_path)
        self.llm = GeminiClient(config.llm)
        self.scraper = ArxivScraper(config.scraper)
        self.pdf_downloader = PDFDownloader(config.pdf_dir)
        self.judge = RelevanceJudge(self.llm, config.llm)
        self.reader = DeepReader(self.llm, config.llm)
        self.kb = KnowledgeBase(config.chroma_path, self.llm)
        self.sota_kb = SOTAKnowledgeBase(config.sota_dir, self.llm, config.llm)
        self.analyzer = ContributionAnalyzer(self.llm, config.llm, self.kb)

    async def run_all(self) -> dict:
        """Run the complete 5-stage pipeline."""
        await self.db.initialize()
        run_id = await self.db.start_pipeline_run()

        stats = {"crawled": 0, "filtered": 0, "read": 0, "sota_updated": 0}

        try:
            # Stage 1: Crawl
            logger.info("=" * 60)
            logger.info("Stage 1: Crawling ArXiv")
            stats["crawled"] = await self.stage_crawl()

            # Stage 2: Filter
            logger.info("=" * 60)
            logger.info("Stage 2: Filtering by relevance")
            stats["filtered"] = await self.stage_filter()

            # Stage 3: Deep Read
            logger.info("=" * 60)
            logger.info("Stage 3: Deep reading")
            stats["read"] = await self.stage_read()

            # Stage 4+5: Analyze + SOTA
            logger.info("=" * 60)
            logger.info("Stage 4+5: Contribution analysis & SOTA update")
            stats["sota_updated"] = await self.stage_analyze_and_sota()

            await self.db.finish_pipeline_run(
                run_id, stats["crawled"], stats["filtered"], stats["read"]
            )
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            raise

        logger.info("=" * 60)
        logger.info(f"Pipeline complete: {stats}")
        return stats

    async def stage_crawl(self) -> int:
        """Stage 1: Crawl ArXiv and store papers."""
        papers = await self.scraper.fetch_all(self.config.topics)
        for paper in papers:
            await self.db.upsert_paper(paper)
        logger.info(f"Stored {len(papers)} papers")
        return len(papers)

    async def stage_filter(self) -> int:
        """Stage 2: Score unfiltered papers for relevance."""
        unfiltered_ids = await self.db.get_unfiltered_paper_ids()
        if not unfiltered_ids:
            logger.info("No unfiltered papers found")
            return 0

        papers = await self.db.get_papers_by_ids(unfiltered_ids)
        logger.info(f"Filtering {len(papers)} papers")

        # Build topic lookup
        topic_map = {t.name: t for t in self.config.topics}
        count = 0

        for paper in papers:
            topic = topic_map.get(paper.source_topic)
            if not topic or not topic.research_profile:
                continue

            verdict = await self.judge.judge(paper, topic)
            if verdict:
                await self.db.upsert_verdict(verdict)
                count += 1
                level = "RELEVANT" if verdict.score >= self.config.filter.relevance_threshold else "skip"
                logger.info(
                    f"  [{level}] {verdict.score}/10 - {paper.title[:60]}..."
                )

        logger.info(f"Filtered {count} papers")
        return count

    async def stage_read(self) -> int:
        """Stage 3: Deep-read papers that passed the relevance filter."""
        unread_ids = await self.db.get_unread_relevant_paper_ids(
            self.config.filter.relevance_threshold
        )
        if not unread_ids:
            logger.info("No unread relevant papers")
            return 0

        papers = await self.db.get_papers_by_ids(unread_ids)
        logger.info(f"Deep reading {len(papers)} papers")
        count = 0

        for paper in papers:
            logger.info(f"  Reading: {paper.title[:60]}...")
            try:
                full_text = await self.pdf_downloader.extract_text(
                    paper.arxiv_id, paper.pdf_url
                )
                reading = await self.reader.read_paper(
                    paper.arxiv_id, paper.title, full_text
                )
                if reading:
                    await self.db.upsert_deep_reading(reading)
                    count += 1
            except Exception as e:
                logger.error(f"  Failed to read {paper.arxiv_id}: {e}")

        logger.info(f"Deep read {count} papers")
        return count

    async def stage_analyze_and_sota(self) -> int:
        """Stage 4+5: Contribution analysis and SOTA tracking."""
        unanalyzed_ids = await self.db.get_unanalyzed_read_paper_ids()
        if not unanalyzed_ids:
            logger.info("No unanalyzed papers")
            return 0

        papers = await self.db.get_papers_by_ids(unanalyzed_ids)
        paper_map = {p.arxiv_id: p for p in papers}
        sota_count = 0

        for arxiv_id in unanalyzed_ids:
            paper = paper_map.get(arxiv_id)
            if not paper:
                continue

            reading = await self.db.get_deep_reading(arxiv_id)
            if not reading:
                continue

            # Stage 4: Contribution analysis
            delta = await self.analyzer.analyze(paper.title, reading)
            if delta:
                await self.db.upsert_contribution_delta(delta)
                logger.info(
                    f"  [{delta.overall_significance.upper()}] {paper.title[:50]}..."
                )

            # Stage 5: SOTA update via markdown knowledge base
            if reading.experiment_table and reading.experiment_table.entries:
                report = await self.sota_kb.update_from_experiment(
                    arxiv_id, paper.title, reading.experiment_table,
                )
                sota_count += len(report.actions)

                # Log to database audit trail
                for action in report.actions:
                    await self.db.log_sota_update(
                        arxiv_id, action.benchmark,
                        action.action, action.summary,
                    )

            # Store in knowledge base
            await self.kb.store_reading(
                arxiv_id, paper.title, reading.key_contributions,
                reading.proposed_method, reading.comparison_to_prior_work,
            )

        return sota_count

    async def read_single_paper(self, arxiv_id: str) -> dict | None:
        """Run full pipeline on a single paper (by arxiv_id)."""
        await self.db.initialize()

        paper = await self.db.get_paper(arxiv_id)
        if not paper:
            logger.error(f"Paper {arxiv_id} not found in database. Run 'crawl' first.")
            return None

        # Download and read
        full_text = await self.pdf_downloader.extract_text(
            paper.arxiv_id, paper.pdf_url
        )
        reading = await self.reader.read_paper(arxiv_id, paper.title, full_text)
        if not reading:
            logger.error("Deep reading failed")
            return None

        await self.db.upsert_deep_reading(reading)

        # Analyze contribution
        delta = await self.analyzer.analyze(paper.title, reading)
        if delta:
            await self.db.upsert_contribution_delta(delta)

        # SOTA update
        sota_report = None
        if reading.experiment_table and reading.experiment_table.entries:
            sota_report = await self.sota_kb.update_from_experiment(
                arxiv_id, paper.title, reading.experiment_table,
            )
            for action in sota_report.actions:
                await self.db.log_sota_update(
                    arxiv_id, action.benchmark,
                    action.action, action.summary,
                )

        # Store knowledge
        await self.kb.store_reading(
            arxiv_id, paper.title, reading.key_contributions,
            reading.proposed_method, reading.comparison_to_prior_work,
        )

        return {
            "reading": reading,
            "contribution": delta,
            "sota_report": sota_report,
        }
