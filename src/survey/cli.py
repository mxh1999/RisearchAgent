from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.survey.artifacts import TopicArtifactManager
from src.survey.models import SurveyEvent, TopicProfile
from src.survey.refiner import TopicRefiner


async def cmd_survey_refine(args) -> None:
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for survey refine. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

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


async def cmd_survey_synthesize(args) -> None:
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for survey synthesize. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    load_dotenv()
    app_config = load_config(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY environment variable not set.")

    topic_path = Path(args.topic)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    readings_dir = Path(args.readings_dir) if args.readings_dir else topic_dir / "papers"

    from src.survey.reading_loader import load_reading_packages
    from src.survey.survey_renderer import (
        render_paper_map_markdown,
        render_positioning_markdown,
        render_references_markdown,
        render_taxonomy_markdown,
    )
    from src.survey.synthesizer import SurveySynthesizer

    try:
        packages = load_reading_packages(readings_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error loading reading packages: {exc}") from exc

    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )

    try:
        synthesis = await SurveySynthesizer(
            GeminiClient(llm_config), model=llm_config.reader_model
        ).synthesize(topic, packages)
    except ValueError as exc:
        raise SystemExit(f"Error synthesizing survey: {exc}") from exc

    manager = TopicArtifactManager(topic_dir.parent)
    manager.create_or_update_topic(topic)
    manager.update_auto_block(
        topic_dir / "survey.md", "taxonomy", render_taxonomy_markdown(synthesis)
    )
    manager.update_auto_block(
        topic_dir / "papers.md", "paper-map", render_paper_map_markdown(synthesis)
    )
    manager.update_auto_block(
        topic_dir / "positioning.md",
        "positioning",
        render_positioning_markdown(synthesis),
    )
    manager.update_auto_block(
        topic_dir / "references.md",
        "references",
        render_references_markdown(synthesis),
    )
    manager.append_event(
        topic_dir,
        SurveyEvent(
            event_type="synthesize",
            message=f"Synthesized survey from {len(packages)} reading packages.",
        ),
    )

    print(f"Survey: {topic_dir / 'survey.md'}")
    print(f"Papers: {topic_dir / 'papers.md'}")
    print(f"Positioning: {topic_dir / 'positioning.md'}")
    print(f"References: {topic_dir / 'references.md'}")


def _load_topic(path: Path) -> TopicProfile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Error loading topic YAML {path}: not found") from exc
    except yaml.YAMLError as exc:
        raise SystemExit(f"Error loading topic YAML {path}: invalid YAML: {exc}") from exc

    if raw is None:
        raise SystemExit(f"Error loading topic YAML {path}: empty YAML")
    if not isinstance(raw, dict):
        raise SystemExit(f"Error loading topic YAML {path}: expected mapping object")

    try:
        return TopicProfile.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(
            f"Error loading topic YAML {path}: malformed TopicProfile: {exc}"
        ) from exc


def run_survey_command(args) -> None:
    if args.survey_command == "refine":
        asyncio.run(cmd_survey_refine(args))
        return

    if args.survey_command == "synthesize":
        asyncio.run(cmd_survey_synthesize(args))
        return

    raise SystemExit(f"Unknown survey command: {args.survey_command}")
