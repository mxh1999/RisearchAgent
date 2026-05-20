from __future__ import annotations

import asyncio
from pathlib import Path

from src.survey.topic_download import (
    DownloadOne,
    DownloadReport,
    materialize_topic_downloads,
)


async def cmd_topic_download(
    args,
    download_one: DownloadOne | None = None,
) -> DownloadReport:
    topic_path = Path(args.topic)
    topic_dir = topic_path.parent
    candidates_path = (
        Path(args.candidates)
        if args.candidates
        else topic_dir / "state" / "discovery_candidates.json"
    )
    manifest_path = (
        Path(args.manifest) if args.manifest else topic_dir / "ingest_manifest.yaml"
    )
    limit = None if args.all else args.limit

    try:
        report = await materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=candidates_path,
            manifest_path=manifest_path,
            limit=limit,
            include_existing=args.include_existing,
            force=args.force,
            download_one=download_one,
        )
    except ValueError as exc:
        raise SystemExit(f"Error loading discovery candidates: {exc}") from exc

    print(f"Report: {topic_dir / 'state' / 'download_report.json'}")
    print(f"Manifest: {manifest_path}")
    print(f"Downloaded: {len(report.downloaded)}")
    print(f"Reused: {len(report.reused)}")
    print(f"Skipped: {len(report.skipped)}")
    print(f"Failed: {len(report.failed)}")
    return report


def run_topic_download(args) -> None:
    asyncio.run(cmd_topic_download(args))

