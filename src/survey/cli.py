from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.staged_models import PaperReadingPackage
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
    topic_path = Path(args.topic)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    readings_dir = Path(args.readings_dir) if args.readings_dir else topic_dir / "papers"

    from src.survey.reading_loader import load_reading_packages

    try:
        packages = load_reading_packages(readings_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error loading reading packages: {exc}") from exc

    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for survey synthesize. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    from src.survey.synthesizer import SurveySynthesizer

    load_dotenv()
    app_config = load_config(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY environment variable not set.")

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

    paths = await synthesize_survey_artifacts(
        topic=topic,
        topic_dir=topic_dir,
        packages=packages,
        synthesis=synthesis,
    )

    print(f"Survey: {paths['survey']}")
    print(f"Papers: {paths['papers']}")
    print(f"Positioning: {paths['positioning']}")
    print(f"References: {paths['references']}")


async def synthesize_survey_artifacts(
    topic: TopicProfile,
    topic_dir: Path,
    packages: list[PaperReadingPackage],
    synthesis,
) -> dict[str, Path]:
    from src.survey.survey_renderer import (
        render_paper_map_markdown,
        render_positioning_markdown,
        render_references_markdown,
        render_taxonomy_markdown,
    )

    manager = TopicArtifactManager(topic_dir.parent)
    manager.ensure_topic_artifacts(topic)
    paths = {
        "survey": topic_dir / "survey.md",
        "papers": topic_dir / "papers.md",
        "positioning": topic_dir / "positioning.md",
        "references": topic_dir / "references.md",
    }
    manager.update_auto_block(
        paths["survey"], "taxonomy", render_taxonomy_markdown(synthesis)
    )
    manager.update_auto_block(
        paths["papers"], "paper-map", render_paper_map_markdown(synthesis)
    )
    manager.update_auto_block(
        paths["positioning"],
        "positioning",
        render_positioning_markdown(synthesis),
    )
    manager.update_auto_block(
        paths["references"],
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
    return paths


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


def _validate_topic_path(topic: TopicProfile, topic_dir: Path) -> None:
    path_topic_id = topic_dir.name
    if topic.topic_id != path_topic_id:
        raise SystemExit(
            "Error loading topic YAML: topic_id does not match topic directory "
            f"(topic_id={topic.topic_id!r}, directory={path_topic_id!r})."
        )


def run_survey_command(args) -> None:
    if args.survey_command == "refine":
        asyncio.run(cmd_survey_refine(args))
        return

    if args.survey_command == "synthesize":
        asyncio.run(cmd_survey_synthesize(args))
        return

    raise SystemExit(f"Unknown survey command: {args.survey_command}")
