import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from src.models import (
    ContributionDelta,
    DeepReading,
    ExperimentEntry,
    ExperimentTable,
    MethodResult,
    Paper,
    RelevanceVerdict,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    authors TEXT NOT NULL,
    pdf_url TEXT NOT NULL,
    published TEXT NOT NULL,
    categories TEXT NOT NULL,
    source_topic TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS relevance_verdicts (
    arxiv_id TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    justification TEXT NOT NULL,
    key_topics TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS deep_readings (
    arxiv_id TEXT PRIMARY KEY,
    problem_statement TEXT NOT NULL,
    proposed_method TEXT NOT NULL,
    key_contributions TEXT NOT NULL,
    experimental_setup TEXT NOT NULL,
    main_results TEXT NOT NULL,
    limitations TEXT NOT NULL,
    comparison_to_prior_work TEXT NOT NULL,
    experiment_table TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS sota_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS contribution_deltas (
    arxiv_id TEXT PRIMARY KEY,
    novel_contributions TEXT NOT NULL,
    incremental_improvements TEXT NOT NULL,
    contradicts_prior TEXT NOT NULL,
    overall_significance TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    papers_crawled INTEGER DEFAULT 0,
    papers_filtered INTEGER DEFAULT 0,
    papers_read INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published);
CREATE INDEX IF NOT EXISTS idx_papers_topic ON papers(source_topic);
CREATE INDEX IF NOT EXISTS idx_verdicts_score ON relevance_verdicts(score);
CREATE INDEX IF NOT EXISTS idx_sota_updates_arxiv ON sota_updates(arxiv_id);
"""

_MIGRATION_SQL = """
-- Migration: rename extracted_benchmarks -> experiment_table if old schema exists
-- This is handled programmatically in _migrate_schema()
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._migrate_schema(db)
            await db.executescript(_SCHEMA)
            await db.commit()

    async def _migrate_schema(self, db: aiosqlite.Connection) -> None:
        """Handle schema migrations from old versions."""
        try:
            # Check if deep_readings table exists with old schema
            cursor = await db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='deep_readings'"
            )
            row = await cursor.fetchone()
            if row and "extracted_benchmarks" in row[0]:
                logger.info("Migrating deep_readings: extracted_benchmarks -> experiment_table")
                await db.execute(
                    "ALTER TABLE deep_readings RENAME COLUMN extracted_benchmarks TO experiment_table"
                )
                await db.commit()

            # Drop old sota_entries table if it exists
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sota_entries'"
            )
            if await cursor.fetchone():
                logger.info("Dropping old sota_entries table (SOTA data now in markdown)")
                await db.execute("DROP TABLE sota_entries")
                await db.commit()
        except Exception as e:
            # Table might not exist yet on first run
            logger.debug(f"Migration check: {e}")

    # ── Papers ────────────────────────────────────────────

    async def upsert_paper(self, paper: Paper) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO papers
                   (arxiv_id, title, abstract, authors, pdf_url, published, categories, source_topic)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(arxiv_id) DO UPDATE SET
                       title=excluded.title, abstract=excluded.abstract""",
                (
                    paper.arxiv_id, paper.title, paper.abstract,
                    json.dumps(paper.authors), paper.pdf_url,
                    paper.published.isoformat(), json.dumps(paper.categories),
                    paper.source_topic,
                ),
            )
            await db.commit()

    async def get_paper(self, arxiv_id: str) -> Paper | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return _row_to_paper(row) if row else None

    async def get_papers_by_ids(self, arxiv_ids: list[str]) -> list[Paper]:
        if not arxiv_ids:
            return []
        placeholders = ",".join("?" for _ in arxiv_ids)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"SELECT * FROM papers WHERE arxiv_id IN ({placeholders})",
                arxiv_ids,
            ) as cursor:
                return [_row_to_paper(row) async for row in cursor]

    async def get_all_papers(self) -> list[Paper]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM papers ORDER BY published DESC") as cursor:
                return [_row_to_paper(row) async for row in cursor]

    async def get_unfiltered_paper_ids(self) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT p.arxiv_id FROM papers p
                   LEFT JOIN relevance_verdicts v ON p.arxiv_id = v.arxiv_id
                   WHERE v.arxiv_id IS NULL"""
            ) as cursor:
                return [row[0] async for row in cursor]

    async def get_unread_relevant_paper_ids(self, threshold: int = 6) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT v.arxiv_id FROM relevance_verdicts v
                   LEFT JOIN deep_readings d ON v.arxiv_id = d.arxiv_id
                   WHERE v.score >= ? AND d.arxiv_id IS NULL""",
                (threshold,),
            ) as cursor:
                return [row[0] async for row in cursor]

    async def get_unanalyzed_read_paper_ids(self) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT d.arxiv_id FROM deep_readings d
                   LEFT JOIN contribution_deltas c ON d.arxiv_id = c.arxiv_id
                   WHERE c.arxiv_id IS NULL"""
            ) as cursor:
                return [row[0] async for row in cursor]

    # ── Relevance Verdicts ────────────────────────────────

    async def upsert_verdict(self, verdict: RelevanceVerdict) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO relevance_verdicts (arxiv_id, score, justification, key_topics)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(arxiv_id) DO UPDATE SET
                       score=excluded.score, justification=excluded.justification,
                       key_topics=excluded.key_topics""",
                (
                    verdict.arxiv_id, verdict.score, verdict.justification,
                    json.dumps(verdict.key_topics),
                ),
            )
            await db.commit()

    async def get_all_verdicts(self) -> list[RelevanceVerdict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM relevance_verdicts") as cursor:
                return [
                    RelevanceVerdict(
                        arxiv_id=row[0],
                        score=row[1],
                        justification=row[2],
                        key_topics=json.loads(row[3]),
                    )
                    async for row in cursor
                ]

    # ── Deep Readings ─────────────────────────────────────

    async def upsert_deep_reading(self, reading: DeepReading) -> None:
        experiment_table = self._serialize_experiment_table(reading.experiment_table)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO deep_readings
                   (arxiv_id, problem_statement, proposed_method, key_contributions,
                    experimental_setup, main_results, limitations,
                    comparison_to_prior_work, experiment_table)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(arxiv_id) DO UPDATE SET
                       problem_statement=excluded.problem_statement,
                       proposed_method=excluded.proposed_method,
                       key_contributions=excluded.key_contributions,
                       experimental_setup=excluded.experimental_setup,
                       main_results=excluded.main_results,
                       limitations=excluded.limitations,
                       comparison_to_prior_work=excluded.comparison_to_prior_work,
                       experiment_table=excluded.experiment_table""",
                (
                    reading.arxiv_id, reading.problem_statement,
                    reading.proposed_method, json.dumps(reading.key_contributions),
                    reading.experimental_setup, reading.main_results,
                    reading.limitations, reading.comparison_to_prior_work,
                    json.dumps(experiment_table),
                ),
            )
            await db.commit()

    async def get_deep_reading(self, arxiv_id: str) -> DeepReading | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM deep_readings WHERE arxiv_id = ?", (arxiv_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                experiment_raw = json.loads(row[8])
                return DeepReading(
                    arxiv_id=row[0],
                    problem_statement=row[1],
                    proposed_method=row[2],
                    key_contributions=json.loads(row[3]),
                    experimental_setup=row[4],
                    main_results=row[5],
                    limitations=row[6],
                    comparison_to_prior_work=row[7],
                    experiment_table=self._deserialize_experiment_table(
                        row[0], experiment_raw
                    ),
                )

    def _serialize_experiment_table(self, table: ExperimentTable | None) -> dict:
        """Convert ExperimentTable to JSON-serializable dict."""
        if table is None:
            return {}
        return {
            "arxiv_id": table.arxiv_id,
            "entries": [
                {
                    "benchmark": e.benchmark,
                    "setting": e.setting,
                    "metric": e.metric,
                    "higher_is_better": e.higher_is_better,
                    "results": [
                        {
                            "method_name": r.method_name,
                            "value": r.value,
                            "is_paper_method": r.is_paper_method,
                        }
                        for r in e.results
                    ],
                }
                for e in table.entries
            ],
            "details": table.details,
        }

    def _deserialize_experiment_table(
        self, arxiv_id: str, raw: dict
    ) -> ExperimentTable | None:
        """Convert JSON dict back to ExperimentTable."""
        if not raw or not raw.get("entries"):
            return None
        entries = []
        for e in raw["entries"]:
            results = [
                MethodResult(
                    method_name=r["method_name"],
                    value=r["value"],
                    is_paper_method=r["is_paper_method"],
                )
                for r in e.get("results", [])
            ]
            entries.append(ExperimentEntry(
                benchmark=e["benchmark"],
                setting=e.get("setting", "default"),
                metric=e["metric"],
                higher_is_better=e.get("higher_is_better", True),
                results=results,
            ))
        return ExperimentTable(
            arxiv_id=raw.get("arxiv_id", arxiv_id),
            entries=entries,
            details=raw.get("details", ""),
        )

    async def get_all_deep_readings(self) -> list[DeepReading]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM deep_readings") as cursor:
                results = []
                async for row in cursor:
                    experiment_raw = json.loads(row[8])
                    results.append(DeepReading(
                        arxiv_id=row[0],
                        problem_statement=row[1],
                        proposed_method=row[2],
                        key_contributions=json.loads(row[3]),
                        experimental_setup=row[4],
                        main_results=row[5],
                        limitations=row[6],
                        comparison_to_prior_work=row[7],
                        experiment_table=self._deserialize_experiment_table(
                            row[0], experiment_raw
                        ),
                    ))
                return results

    # ── SOTA Updates (audit log) ──────────────────────────

    async def log_sota_update(
        self, arxiv_id: str, benchmark: str, action: str, summary: str
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO sota_updates (arxiv_id, benchmark, action, summary)
                   VALUES (?, ?, ?, ?)""",
                (arxiv_id, benchmark, action, summary),
            )
            await db.commit()

    # ── Contribution Deltas ───────────────────────────────

    async def upsert_contribution_delta(self, delta: ContributionDelta) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO contribution_deltas
                   (arxiv_id, novel_contributions, incremental_improvements,
                    contradicts_prior, overall_significance)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(arxiv_id) DO UPDATE SET
                       novel_contributions=excluded.novel_contributions,
                       incremental_improvements=excluded.incremental_improvements,
                       contradicts_prior=excluded.contradicts_prior,
                       overall_significance=excluded.overall_significance""",
                (
                    delta.arxiv_id,
                    json.dumps(delta.novel_contributions),
                    json.dumps(delta.incremental_improvements),
                    json.dumps(delta.contradicts_prior),
                    delta.overall_significance,
                ),
            )
            await db.commit()

    async def get_all_contribution_deltas(self) -> list[ContributionDelta]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM contribution_deltas") as cursor:
                return [
                    ContributionDelta(
                        arxiv_id=row[0],
                        novel_contributions=json.loads(row[1]),
                        incremental_improvements=json.loads(row[2]),
                        contradicts_prior=json.loads(row[3]),
                        overall_significance=row[4],
                    )
                    async for row in cursor
                ]

    # ── Pipeline Runs ─────────────────────────────────────

    async def start_pipeline_run(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO pipeline_runs (started_at) VALUES (?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            await db.commit()
            return cursor.lastrowid

    async def finish_pipeline_run(
        self, run_id: int, papers_crawled: int, papers_filtered: int, papers_read: int
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE pipeline_runs SET
                       finished_at=?, papers_crawled=?, papers_filtered=?,
                       papers_read=?, status='completed'
                   WHERE id=?""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    papers_crawled, papers_filtered, papers_read, run_id,
                ),
            )
            await db.commit()

    # ── Stats ─────────────────────────────────────────────

    async def get_stats(self) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            total = (await (await db.execute("SELECT COUNT(*) FROM papers")).fetchone())[0]
            filtered = (await (await db.execute("SELECT COUNT(*) FROM relevance_verdicts")).fetchone())[0]
            read = (await (await db.execute("SELECT COUNT(*) FROM deep_readings")).fetchone())[0]
            sota = (await (await db.execute("SELECT COUNT(*) FROM sota_updates")).fetchone())[0]
            return {
                "total_papers": total,
                "filtered": filtered,
                "deep_read": read,
                "sota_updates": sota,
            }


def _row_to_paper(row) -> Paper:
    return Paper(
        arxiv_id=row[0],
        title=row[1],
        abstract=row[2],
        authors=json.loads(row[3]),
        pdf_url=row[4],
        published=datetime.fromisoformat(row[5]),
        categories=json.loads(row[6]),
        source_topic=row[7],
    )
