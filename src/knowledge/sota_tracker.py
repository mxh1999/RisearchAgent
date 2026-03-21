import logging

from src.models import BenchmarkResult, SOTAEntry
from src.storage.database import Database

logger = logging.getLogger(__name__)


class SOTATracker:
    """Maintains and updates SOTA benchmark entries."""

    def __init__(self, db: Database):
        self.db = db

    async def update_from_benchmarks(
        self, arxiv_id: str, method_name: str, benchmarks: list[BenchmarkResult],
        field: str = ""
    ) -> list[SOTAEntry]:
        """Check benchmarks against SOTA and update if new records found.

        Returns list of updated SOTA entries.
        """
        updated = []

        for b in benchmarks:
            if not b.is_sota:
                continue

            existing = await self.db.get_sota_entry(
                field=field or "general",
                benchmark=b.benchmark_name,
                metric=b.metric_name,
            )

            if existing is None:
                # New SOTA entry
                entry = SOTAEntry(
                    field=field or "general",
                    benchmark=b.benchmark_name,
                    metric=b.metric_name,
                    best_value=b.value,
                    best_method=method_name,
                    best_paper_id=arxiv_id,
                )
                await self.db.upsert_sota_entry(entry)
                updated.append(entry)
                logger.info(
                    f"New SOTA: {b.benchmark_name}/{b.metric_name} = {b.value} by {method_name}"
                )

            elif b.value > existing.best_value:
                # Beats existing SOTA (assumes higher is better)
                entry = SOTAEntry(
                    field=field or "general",
                    benchmark=b.benchmark_name,
                    metric=b.metric_name,
                    best_value=b.value,
                    best_method=method_name,
                    best_paper_id=arxiv_id,
                    previous_best_value=existing.best_value,
                    previous_best_method=existing.best_method,
                )
                await self.db.upsert_sota_entry(entry)
                updated.append(entry)
                logger.info(
                    f"SOTA updated: {b.benchmark_name}/{b.metric_name} "
                    f"{existing.best_value} -> {b.value} by {method_name}"
                )

        return updated
