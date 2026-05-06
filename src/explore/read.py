"""Bridge: src.reader.DeepReader (main pipeline) → ExploreReading (state).

Per docs/onboard-redesign/06-action-system.md, Explorer's read_paper reuses
the existing 3-pass DeepReader rather than writing a separate reader. The
result is converted to a pydantic ExploreReading and stored in
state.paper_pool[id].explore_reading — NOT to the main DB's deep_readings
table (those are authoritative pipeline outputs; Explorer's are exploratory).

This module is just the conversion layer plus a thin runner that ties
PDFDownloader + DeepReader together. Kept separate from executor.py so
M7 changes (e.g. adding a lightweight 1-pass reader) only touch this file.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.crawl.pdf_downloader import PDFDownloader
from src.explore.state import (
    ExperimentEntry,
    ExperimentMethodResult,
    ExploreReading,
)
from src.reader.deep_reader import DeepReader

if TYPE_CHECKING:
    from src.config import LLMConfig
    from src.explore.state import PaperRecord
    from src.llm.gemini_client import GeminiClient
    from src.models import DeepReading


logger = logging.getLogger(__name__)


def deep_reading_to_explore_reading(
    arxiv_id: str, deep: "DeepReading"
) -> ExploreReading:
    """Convert main-pipeline DeepReading (stdlib dataclass) to ExploreReading.

    Drops fields the Explorer doesn't need (problem_statement,
    key_contributions, comparison_to_prior_work, limitations) — they're
    available in the main DB if a future caller wants them.
    """
    benchmarks: list[ExperimentEntry] = []
    if deep.experiment_table is not None:
        for entry in deep.experiment_table.entries:
            results = [
                ExperimentMethodResult(
                    method_name=r.method_name,
                    value=float(r.value),
                    is_paper_method=bool(r.is_paper_method),
                )
                for r in entry.results
            ]
            benchmarks.append(
                ExperimentEntry(
                    benchmark=entry.benchmark,
                    setting=entry.setting,
                    metric=entry.metric,
                    higher_is_better=bool(entry.higher_is_better),
                    results=results,
                )
            )

    return ExploreReading(
        arxiv_id=arxiv_id,
        proposed_method=deep.proposed_method or "",
        experimental_setup=deep.experimental_setup or "",
        main_results=deep.main_results or "",
        benchmarks=benchmarks,
        read_at=datetime.now(),
    )


class ExploreReader:
    """Pulls a PDF, runs 3-pass deep read, returns an ExploreReading.

    Wraps the existing DeepReader + PDFDownloader so the Explorer doesn't
    have to know about LLMConfig vs GeminiClient construction details.
    """

    def __init__(
        self,
        llm: "GeminiClient",
        config: "LLMConfig",
        pdf_dir: Path = Path("data/explore/pdfs"),
    ):
        self.llm = llm
        self.config = config
        self.pdf_dir = pdf_dir
        self._downloader: Optional[PDFDownloader] = None
        self._reader: Optional[DeepReader] = None

    @property
    def downloader(self) -> PDFDownloader:
        if self._downloader is None:
            self.pdf_dir.mkdir(parents=True, exist_ok=True)
            self._downloader = PDFDownloader(self.pdf_dir)
        return self._downloader

    @property
    def reader(self) -> DeepReader:
        if self._reader is None:
            self._reader = DeepReader(self.llm, self.config)
        return self._reader

    async def read(self, paper: "PaperRecord") -> Optional[ExploreReading]:
        """Returns an ExploreReading or None on failure (download / parse / LLM).

        Failure is non-fatal: caller (Executor) records a failed ActionResult
        but the Explorer run continues. Budget is consumed regardless to
        prevent retry storms.
        """
        if not paper.pdf_url:
            logger.warning("[explore.read] no pdf_url for %s", paper.arxiv_id)
            return None
        try:
            full_text = await self.downloader.extract_text(
                paper.arxiv_id, paper.pdf_url
            )
        except Exception as e:
            logger.warning("[explore.read] PDF extract failed for %s: %s", paper.arxiv_id, e)
            return None
        if not full_text or len(full_text.strip()) < 500:
            logger.warning(
                "[explore.read] PDF text too short for %s (%d chars)",
                paper.arxiv_id,
                len(full_text or ""),
            )
            return None

        try:
            deep = await self.reader.read_paper(
                paper.arxiv_id, paper.title, full_text
            )
        except Exception as e:
            logger.warning("[explore.read] DeepReader failed for %s: %s", paper.arxiv_id, e)
            return None
        if deep is None:
            return None
        return deep_reading_to_explore_reading(paper.arxiv_id, deep)


__all__ = ["ExploreReader", "deep_reading_to_explore_reading"]
