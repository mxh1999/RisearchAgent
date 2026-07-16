from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.llm.client import create_llm_client, normalize_llm_config
from src.survey.relevance import (
    RelevanceLLM,
    screen_discovery_candidates,
    validate_reading_packages,
)


async def cmd_topic_screen(args, llm: RelevanceLLM | None = None):
    topic_path = Path(args.topic)
    candidates_path = (
        Path(args.candidates)
        if args.candidates
        else topic_path.parent / "state" / "discovery_candidates.json"
    )
    client, model = _resolve_llm(args, llm)
    try:
        report = await screen_discovery_candidates(
            topic_path=topic_path,
            candidates_path=candidates_path,
            threshold=args.threshold,
            limit=args.limit,
            dry_run=args.dry_run,
            llm=client,
            model=model,
        )
    except ValueError as exc:
        raise SystemExit(f"Error screening discovery candidates: {exc}") from exc
    report_path = topic_path.parent / "state" / "screening_report.json"
    print(f"Report: {report_path}")
    print(f"Accepted: {len(report.accepted)}")
    print(f"Rejected: {len(report.rejected)}")
    print(f"Dry run: {report.dry_run}")
    return report


async def cmd_topic_validate(args, llm: RelevanceLLM | None = None):
    topic_path = Path(args.topic)
    readings_dir = Path(args.readings_dir) if args.readings_dir else None
    client, model = _resolve_llm(args, llm)
    try:
        report = await validate_reading_packages(
            topic_path=topic_path,
            readings_dir=readings_dir,
            threshold=args.threshold,
            limit=args.limit,
            dry_run=args.dry_run,
            llm=client,
            model=model,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error validating reading packages: {exc}") from exc
    report_name = (
        "relevance_validations.dry_run.json"
        if args.dry_run
        else "relevance_validations.json"
    )
    report_path = topic_path.parent / "state" / report_name
    print(f"Report: {report_path}")
    print(f"Included: {len(report.included)}")
    print(f"Excluded: {len(report.excluded)}")
    print(f"Dry run: {report.dry_run}")
    return report


def run_topic_screen(args) -> None:
    asyncio.run(cmd_topic_screen(args))


def run_topic_validate(args) -> None:
    asyncio.run(cmd_topic_validate(args))


def _resolve_llm(args, injected: RelevanceLLM | None) -> tuple[RelevanceLLM, str | None]:
    if injected is not None:
        return injected, args.model

    load_dotenv()
    app_config = load_config(args.config)
    llm_config = normalize_llm_config(app_config.llm)
    if not llm_config.api_key:
        raise SystemExit(
            "Error: "
            f"{llm_config.api_key_env} environment variable not set "
            "for topic relevance screening."
        )
    return create_llm_client(llm_config), args.model or llm_config.filter_model
