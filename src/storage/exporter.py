"""Export and import knowledge data as JSON."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.models import (
    ContributionDelta,
    DeepReading,
    ExperimentTable,
    Paper,
    RelevanceVerdict,
)
from src.storage.database import Database

logger = logging.getLogger(__name__)

EXPORT_VERSION = 1


async def export_knowledge(
    db: Database, config_path: str, sota_dir: Path
) -> dict:
    """Read all knowledge tables + SOTA markdown files, return JSON-serializable dict."""
    papers = await db.get_all_papers()
    verdicts = await db.get_all_verdicts()
    readings = await db.get_all_deep_readings()
    deltas = await db.get_all_contribution_deltas()

    # Load config for topics/filter settings
    config_data = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        config_data = {
            "topics": raw.get("topics", []),
            "filter": raw.get("filter", {}),
        }

    # Load SOTA markdown files
    sota_tables = {}
    if sota_dir.exists():
        for md_file in sorted(sota_dir.glob("*.md")):
            sota_tables[md_file.name] = md_file.read_text(encoding="utf-8")

    # Separate classic_baselines.md if present
    classic_baselines_md = sota_tables.pop("classic_baselines.md", "")

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "config": config_data,
        "papers": [_paper_to_dict(p) for p in papers],
        "relevance_verdicts": [_verdict_to_dict(v) for v in verdicts],
        "deep_readings": [_reading_to_dict(r, db) for r in readings],
        "contribution_deltas": [_delta_to_dict(d) for d in deltas],
        "sota_tables": sota_tables,
        "classic_baselines_md": classic_baselines_md,
    }


async def import_knowledge(
    db: Database, data: dict, sota_dir: Path, merge: bool
) -> dict:
    """Import knowledge data into the database.

    Args:
        db: Database instance (must be initialized).
        data: Parsed JSON export data.
        sota_dir: Directory for SOTA markdown files.
        merge: If True, upsert (keep existing data). If False, clear tables first.

    Returns:
        Summary dict with counts of imported items.
    """
    version = data.get("version", 0)
    if version != EXPORT_VERSION:
        raise ValueError(
            f"Unsupported export version {version} (expected {EXPORT_VERSION})"
        )

    if not merge:
        await _clear_knowledge_tables(db)

    # Import papers
    papers_count = 0
    for p in data.get("papers", []):
        paper = _dict_to_paper(p)
        await db.upsert_paper(paper)
        papers_count += 1

    # Import verdicts
    verdicts_count = 0
    for v in data.get("relevance_verdicts", []):
        verdict = _dict_to_verdict(v)
        await db.upsert_verdict(verdict)
        verdicts_count += 1

    # Import deep readings
    readings_count = 0
    for r in data.get("deep_readings", []):
        reading = _dict_to_reading(r)
        await db.upsert_deep_reading(reading)
        readings_count += 1

    # Import contribution deltas
    deltas_count = 0
    for d in data.get("contribution_deltas", []):
        delta = _dict_to_delta(d)
        await db.upsert_contribution_delta(delta)
        deltas_count += 1

    # Import SOTA markdown files
    sota_count = 0
    sota_dir.mkdir(parents=True, exist_ok=True)
    if not merge:
        # Clear existing SOTA files
        for md_file in sota_dir.glob("*.md"):
            md_file.unlink()

    for filename, content in data.get("sota_tables", {}).items():
        (sota_dir / filename).write_text(content, encoding="utf-8")
        sota_count += 1

    classic_md = data.get("classic_baselines_md", "")
    if classic_md:
        (sota_dir / "classic_baselines.md").write_text(classic_md, encoding="utf-8")
        sota_count += 1

    summary = {
        "papers": papers_count,
        "verdicts": verdicts_count,
        "deep_readings": readings_count,
        "contribution_deltas": deltas_count,
        "sota_files": sota_count,
    }
    logger.info(f"Import complete: {summary}")
    return summary


async def _clear_knowledge_tables(db: Database) -> None:
    """Delete all rows from knowledge tables (not pipeline_runs)."""
    import aiosqlite

    async with aiosqlite.connect(db.db_path) as conn:
        for table in [
            "contribution_deltas",
            "deep_readings",
            "relevance_verdicts",
            "sota_updates",
            "papers",
        ]:
            await conn.execute(f"DELETE FROM {table}")
        await conn.commit()
    logger.info("Cleared all knowledge tables")


# ── Serialization helpers ────────────────────────────────


def _paper_to_dict(paper: Paper) -> dict:
    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": paper.authors,
        "pdf_url": paper.pdf_url,
        "published": paper.published.isoformat(),
        "categories": paper.categories,
        "source_topic": paper.source_topic,
    }


def _verdict_to_dict(verdict: RelevanceVerdict) -> dict:
    return {
        "arxiv_id": verdict.arxiv_id,
        "score": verdict.score,
        "justification": verdict.justification,
        "key_topics": verdict.key_topics,
    }


def _reading_to_dict(reading: DeepReading, db: Database) -> dict:
    result = {
        "arxiv_id": reading.arxiv_id,
        "problem_statement": reading.problem_statement,
        "proposed_method": reading.proposed_method,
        "key_contributions": reading.key_contributions,
        "experimental_setup": reading.experimental_setup,
        "main_results": reading.main_results,
        "limitations": reading.limitations,
        "comparison_to_prior_work": reading.comparison_to_prior_work,
        "experiment_table": db._serialize_experiment_table(reading.experiment_table),
    }
    return result


def _delta_to_dict(delta: ContributionDelta) -> dict:
    return {
        "arxiv_id": delta.arxiv_id,
        "novel_contributions": delta.novel_contributions,
        "incremental_improvements": delta.incremental_improvements,
        "contradicts_prior": delta.contradicts_prior,
        "overall_significance": delta.overall_significance,
    }


def _dict_to_paper(d: dict) -> Paper:
    return Paper(
        arxiv_id=d["arxiv_id"],
        title=d["title"],
        abstract=d["abstract"],
        authors=d["authors"],
        pdf_url=d["pdf_url"],
        published=datetime.fromisoformat(d["published"]),
        categories=d["categories"],
        source_topic=d["source_topic"],
    )


def _dict_to_verdict(d: dict) -> RelevanceVerdict:
    return RelevanceVerdict(
        arxiv_id=d["arxiv_id"],
        score=d["score"],
        justification=d["justification"],
        key_topics=d["key_topics"],
    )


def _dict_to_reading(d: dict) -> DeepReading:
    exp_raw = d.get("experiment_table", {})
    experiment_table = None
    if exp_raw and exp_raw.get("entries"):
        from src.models import ExperimentEntry, MethodResult

        entries = []
        for e in exp_raw["entries"]:
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
        experiment_table = ExperimentTable(
            arxiv_id=exp_raw.get("arxiv_id", d["arxiv_id"]),
            entries=entries,
            details=exp_raw.get("details", ""),
        )

    return DeepReading(
        arxiv_id=d["arxiv_id"],
        problem_statement=d["problem_statement"],
        proposed_method=d["proposed_method"],
        key_contributions=d["key_contributions"],
        experimental_setup=d["experimental_setup"],
        main_results=d["main_results"],
        limitations=d["limitations"],
        comparison_to_prior_work=d["comparison_to_prior_work"],
        experiment_table=experiment_table,
    )


def _dict_to_delta(d: dict) -> ContributionDelta:
    return ContributionDelta(
        arxiv_id=d["arxiv_id"],
        novel_contributions=d["novel_contributions"],
        incremental_improvements=d["incremental_improvements"],
        contradicts_prior=d["contradicts_prior"],
        overall_significance=d["overall_significance"],
    )
