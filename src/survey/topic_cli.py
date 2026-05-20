from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.survey.topic_update import load_topic_update_context, update_topic_artifacts


async def cmd_topic_update(args) -> None:
    topic_path = Path(args.topic)
    readings_dir = Path(args.readings_dir) if args.readings_dir else None
    context = load_topic_update_context(topic_path, readings_dir)
    topic_dir = context.topic_dir

    survey_llm = None
    survey_model = None
    sota_llm = None
    sota_model = None
    use_sota_llm = not args.no_llm_normalize
    if not args.skip_sota and not context.sota_records:
        raise SystemExit("No experiment records found in reading packages.")

    if not args.skip_survey:
        survey_llm, survey_model = _build_llm(args.config, purpose="topic update")

    if not args.skip_sota and use_sota_llm and context.sota_needs_llm:
        sota_llm, sota_model = _build_llm(args.config, purpose="SOTA setting normalization")

    report = await update_topic_artifacts(
        context=context,
        survey_llm=survey_llm,
        survey_model=survey_model,
        sota_llm=sota_llm,
        sota_model=sota_model,
        skip_survey=args.skip_survey,
        skip_sota=args.skip_sota,
        use_sota_llm=use_sota_llm,
    )

    report_path = topic_dir / "state" / "topic_update_report.json"
    print(f"Report: {report_path}")
    print(f"Survey: {report.survey.status}")
    print(f"SOTA: {report.sota.status}")
    print(f"Papers: {report.paper_count}")


def _build_llm(config_path: str, purpose: str):
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                f"Error: google-genai is required for {purpose}. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    load_dotenv()
    app_config = load_config(config_path)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        print(f"Error: GEMINI_API_KEY environment variable not set for {purpose}.")
        sys.exit(1)

    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    return GeminiClient(llm_config), llm_config.reader_model


def run_topic_command(args) -> None:
    if args.topic_command == "discover":
        from src.survey.discover_cli import run_topic_discover

        run_topic_discover(args)
        return
    if args.topic_command == "ingest":
        from src.survey.ingest_cli import run_topic_ingest

        run_topic_ingest(args)
        return
    if args.topic_command == "update":
        asyncio.run(cmd_topic_update(args))
        return
    raise SystemExit(f"Unknown topic command: {args.topic_command}")
