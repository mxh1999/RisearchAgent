import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from src.models import (
    BenchmarkResult,
    ContributionDelta,
    DeepReading,
    Paper,
    RelevanceVerdict,
    SOTAEntry,
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
    extracted_benchmarks TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (arxiv_id) REFERENCES papers(arxiv_id)
);

CREATE TABLE IF NOT EXISTS sota_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    metric TEXT NOT NULL,
    best_value REAL NOT NULL,
    best_method TEXT NOT NULL,
    best_paper_id TEXT NOT NULL,
    previous_best_value REAL,
    previous_best_method TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(field, benchmark, metric)
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
CREATE INDEX IF NOT EXISTS idx_sota_field ON sota_entries(field, benchmark);
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

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

    # ── Deep Readings ─────────────────────────────────────

    async def upsert_deep_reading(self, reading: DeepReading) -> None:
        benchmarks = [
            {
                "benchmark_name": b.benchmark_name,
                "metric_name": b.metric_name,
                "value": b.value,
                "unit": b.unit,
                "is_sota": b.is_sota,
            }
            for b in reading.extracted_benchmarks
        ]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO deep_readings
                   (arxiv_id, problem_statement, proposed_method, key_contributions,
                    experimental_setup, main_results, limitations,
                    comparison_to_prior_work, extracted_benchmarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(arxiv_id) DO UPDATE SET
                       problem_statement=excluded.problem_statement,
                       proposed_method=excluded.proposed_method,
                       key_contributions=excluded.key_contributions,
                       experimental_setup=excluded.experimental_setup,
                       main_results=excluded.main_results,
                       limitations=excluded.limitations,
                       comparison_to_prior_work=excluded.comparison_to_prior_work,
                       extracted_benchmarks=excluded.extracted_benchmarks""",
                (
                    reading.arxiv_id, reading.problem_statement,
                    reading.proposed_method, json.dumps(reading.key_contributions),
                    reading.experimental_setup, reading.main_results,
                    reading.limitations, reading.comparison_to_prior_work,
                    json.dumps(benchmarks),
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
                benchmarks_raw = json.loads(row[8])
                return DeepReading(
                    arxiv_id=row[0],
                    problem_statement=row[1],
                    proposed_method=row[2],
                    key_contributions=json.loads(row[3]),
                    experimental_setup=row[4],
                    main_results=row[5],
                    limitations=row[6],
                    comparison_to_prior_work=row[7],
                    extracted_benchmarks=[
                        BenchmarkResult(**b) for b in benchmarks_raw
                    ],
                )

    # ── SOTA Entries ──────────────────────────────────────

    async def get_sota_entry(self, field: str, benchmark: str, metric: str) -> SOTAEntry | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT field, benchmark, metric, best_value, best_method,
                          best_paper_id, previous_best_value, previous_best_method
                   FROM sota_entries WHERE field=? AND benchmark=? AND metric=?""",
                (field, benchmark, metric),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return SOTAEntry(
                    field=row[0], benchmark=row[1], metric=row[2],
                    best_value=row[3], best_method=row[4], best_paper_id=row[5],
                    previous_best_value=row[6], previous_best_method=row[7],
                )

    async def upsert_sota_entry(self, entry: SOTAEntry) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO sota_entries
                   (field, benchmark, metric, best_value, best_method,
                    best_paper_id, previous_best_value, previous_best_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(field, benchmark, metric) DO UPDATE SET
                       best_value=excluded.best_value,
                       best_method=excluded.best_method,
                       best_paper_id=excluded.best_paper_id,
                       previous_best_value=excluded.previous_best_value,
                       previous_best_method=excluded.previous_best_method,
                       updated_at=datetime('now')""",
                (
                    entry.field, entry.benchmark, entry.metric,
                    entry.best_value, entry.best_method, entry.best_paper_id,
                    entry.previous_best_value, entry.previous_best_method,
                ),
            )
            await db.commit()

    async def get_all_sota_entries(self) -> list[SOTAEntry]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT field, benchmark, metric, best_value, best_method,
                          best_paper_id, previous_best_value, previous_best_method
                   FROM sota_entries ORDER BY field, benchmark"""
            ) as cursor:
                return [
                    SOTAEntry(
                        field=row[0], benchmark=row[1], metric=row[2],
                        best_value=row[3], best_method=row[4], best_paper_id=row[5],
                        previous_best_value=row[6], previous_best_method=row[7],
                    )
                    async for row in cursor
                ]

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
            sota = (await (await db.execute("SELECT COUNT(*) FROM sota_entries")).fetchone())[0]
            return {
                "total_papers": total,
                "filtered": filtered,
                "deep_read": read,
                "sota_entries": sota,
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
