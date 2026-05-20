from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.staged_cli import read_staged_source
from src.reader.staged_reader import StagedPaperReader
from src.survey.topic_ingest import ingest_topic_papers, plan_topic_ingest
from src.survey.topic_update import load_topic_update_context, update_topic_artifacts


async def cmd_topic_ingest(args):
    topic_path = Path(args.topic)
    manifest_path = Path(args.manifest)
    readings_dir = Path(args.readings_dir) if args.readings_dir else None

    try:
        plan = plan_topic_ingest(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=readings_dir,
            force=args.force,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    reader = _build_staged_reader(args.config) if plan.to_read else None

    async def read_service(**kwargs):
        if reader is None:
            raise ValueError("staged reader is required when papers need reading")
        return await read_staged_source(reader=reader, **kwargs)

    update_service = None
    if args.update:
        async def update_service(*, topic_path, readings_dir, no_llm_normalize):
            return await _run_topic_update(
                config_path=args.config,
                topic_path=topic_path,
                readings_dir=readings_dir,
                no_llm_normalize=no_llm_normalize,
            )

    try:
        report = await ingest_topic_papers(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=readings_dir,
            force=args.force,
            update=args.update,
            no_llm_normalize=args.no_llm_normalize,
            read_service=read_service,
            update_service=update_service,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    report_path = plan.topic_dir / "state" / "ingest_report.json"
    print(f"Report: {report_path}")
    print(f"Total: {report.total}")
    print(f"Read: {len(report.read)}")
    print(f"Skipped existing: {len(report.skipped_existing)}")
    print(f"Update: {report.update.status}")
    return report


def run_topic_ingest(args) -> None:
    asyncio.run(cmd_topic_ingest(args))


def _build_staged_reader(config_path: str) -> StagedPaperReader:
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for topic ingest. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    load_dotenv()
    app_config = load_config(config_path)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set for topic ingest.")
        sys.exit(1)

    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    return StagedPaperReader(GeminiClient(llm_config), model=llm_config.reader_model)


async def _run_topic_update(
    *,
    config_path: str,
    topic_path: Path,
    readings_dir: Path,
    no_llm_normalize: bool,
) -> Path:
    from src.survey.topic_cli import _build_llm

    context = load_topic_update_context(topic_path, readings_dir)
    survey_llm, survey_model = _build_llm(config_path, purpose="topic ingest update")
    sota_llm = None
    sota_model = None
    if not no_llm_normalize and context.sota_needs_llm:
        sota_llm, sota_model = _build_llm(
            config_path,
            purpose="SOTA setting normalization",
        )

    await update_topic_artifacts(
        context=context,
        survey_llm=survey_llm,
        survey_model=survey_model,
        sota_llm=sota_llm,
        sota_model=sota_model,
        skip_survey=False,
        skip_sota=False,
        use_sota_llm=not no_llm_normalize,
    )
    return context.topic_dir / "state" / "topic_update_report.json"
