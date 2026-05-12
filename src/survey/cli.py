from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.llm.gemini_client import GeminiClient
from src.survey.artifacts import TopicArtifactManager
from src.survey.models import SurveyEvent
from src.survey.refiner import TopicRefiner


async def cmd_survey_refine(args) -> None:
    load_dotenv()
    app_config = load_config(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    llm = GeminiClient(llm_config)
    refiner = TopicRefiner(llm, model=llm_config.reader_model)

    if args.from_note:
        source = f"note {args.from_note}"
        profile = await refiner.refine_note(Path(args.from_note))
    else:
        source = "topic text"
        profile = await refiner.refine_text(args.topic_text)

    manager = TopicArtifactManager(Path(args.topics_root))
    paths = manager.create_or_update_topic(profile)
    manager.append_event(
        paths.topic_dir,
        SurveyEvent(
            event_type="refine",
            message=f"Refined topic profile from {source}.",
        ),
    )

    print(f"Topic YAML: {paths.topic_yaml}")
    print(f"Topic dir: {paths.topic_dir}")


def run_survey_command(args) -> None:
    if args.survey_command == "refine":
        asyncio.run(cmd_survey_refine(args))
        return

    raise SystemExit(f"Unknown survey command: {args.survey_command}")
