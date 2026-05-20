from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.survey.arxiv_provider import ArxivDiscoveryProvider
from src.survey.cli import _load_topic, _validate_topic_path
from src.survey.topic_discover import (
    DiscoveryReport,
    RawDiscoveryPaper,
    build_discovery_report,
    write_discovery_artifacts,
)


async def cmd_topic_discover(args, provider=None) -> DiscoveryReport:
    topic_path = Path(args.topic)
    topic_dir = topic_path.parent
    topic = _load_topic(topic_path)
    _validate_topic_path(topic, topic_dir)
    if not topic.search_queries:
        raise SystemExit("Topic search_queries must contain at least one query.")

    discovery_provider = provider or ArxivDiscoveryProvider()
    now_utc = datetime.now(timezone.utc)
    min_published = now_utc - timedelta(days=args.days_lookback)
    raw_papers: list[RawDiscoveryPaper] = []

    for query in topic.search_queries:
        results = await discovery_provider.search(
            query.query,
            query.name,
            query.purpose,
            args.max_results_per_query,
            args.sort,
        )
        raw_papers.extend(
            paper
            for paper in results
            if _as_utc(paper.published) >= min_published
        )

    report = build_discovery_report(
        topic,
        raw_papers,
        topic_dir,
        args.include_existing,
        generated_at=now_utc,
    )
    paths = write_discovery_artifacts(topic_dir, report, topic)

    print(f"Report: {paths['json']}")
    print(f"Markdown: {paths['markdown']}")
    print(f"Manifest: {paths['manifest']}")
    print(f"Queries: {report.query_count}")
    print(f"Candidates: {report.candidate_count}")
    print(f"Excluded existing: {len(report.excluded_existing)}")
    return report


def run_topic_discover(args) -> None:
    asyncio.run(cmd_topic_discover(args))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
