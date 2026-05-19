from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.staged_models import PaperReadingPackage
from src.survey.artifacts import TopicArtifactManager
from src.survey.cli import _load_topic, _validate_topic_path
from src.survey.models import SurveyEvent
from src.survey.reading_loader import load_reading_packages
from src.survey.sota_models import (
    SettingGroupRegistry,
    collect_sota_records,
    records_to_jsonl,
    setting_registry_from_json,
    setting_registry_to_json,
)
from src.survey.sota_normalizer import assign_setting_groups
from src.survey.sota_normalizer import has_unmatched_raw_settings
from src.survey.sota_renderer import render_sota_markdown


async def cmd_sota_update(args) -> None:
    topic_path = Path(args.topic)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    readings_dir = Path(args.readings_dir) if args.readings_dir else topic_dir / "papers"

    try:
        packages = load_reading_packages(readings_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error loading reading packages: {exc}") from exc

    groups_path = topic_dir / "state" / "sota_setting_groups.json"
    registry = _load_registry(groups_path)

    use_llm = not getattr(args, "no_llm_normalize", False)
    llm = None
    model = None
    records = collect_sota_records(packages)
    if not records:
        raise SystemExit("No experiment records found in reading packages.")
    needs_llm = use_llm and has_unmatched_raw_settings(records, registry)
    if needs_llm:
        llm, model = _build_llm(args.config)

    result = await update_sota_artifacts(
        topic=topic,
        topic_dir=topic_dir,
        packages=packages,
        registry=registry,
        llm=llm,
        model=model,
        use_llm=use_llm,
    )

    print(f"SOTA: {result['sota']}")
    print(f"Records: {result['records']}")
    print(f"Setting groups: {result['setting_groups']}")


async def update_sota_artifacts(
    topic,
    topic_dir: Path,
    packages: list[PaperReadingPackage],
    registry: SettingGroupRegistry,
    llm,
    model: str | None,
    use_llm: bool,
) -> dict[str, object]:
    records = collect_sota_records(packages)
    if not records:
        raise ValueError("No experiment records found in reading packages.")

    registry = await assign_setting_groups(
        records,
        registry,
        topic,
        llm=llm,
        model=model,
        use_llm=use_llm,
    )

    manager = TopicArtifactManager(topic_dir.parent)
    (topic_dir / "state").mkdir(parents=True, exist_ok=True)
    manager.ensure_sota_artifact(topic)
    records_path = topic_dir / "state" / "sota_records.jsonl"
    groups_path = topic_dir / "state" / "sota_setting_groups.json"
    records_path.write_text(records_to_jsonl(records), encoding="utf-8")
    groups_path.write_text(setting_registry_to_json(registry), encoding="utf-8")
    manager.update_auto_block(
        topic_dir / "sota.md",
        "sota",
        render_sota_markdown(records, registry),
    )
    manager.append_event(
        topic_dir,
        SurveyEvent(
            event_type="sota_update",
            message=f"Updated SOTA from {len(records)} experiment records.",
        ),
    )
    return {
        "sota": topic_dir / "sota.md",
        "records": records_path,
        "setting_groups": groups_path,
        "record_count": len(records),
        "setting_group_count": len(registry.groups),
    }


def _load_registry(path: Path) -> SettingGroupRegistry:
    if not path.exists():
        return SettingGroupRegistry(groups=[])
    try:
        return setting_registry_from_json(path.read_text(encoding="utf-8"))
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Error loading SOTA setting groups {path}: {exc}") from exc


def _build_llm(config_path: str):
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for SOTA setting normalization. "
                "Run pip install -r requirements.txt or pass --no-llm-normalize."
            ) from exc
        raise

    load_dotenv()
    app_config = load_config(config_path)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        print(
            "Error: GEMINI_API_KEY environment variable not set. "
            "Pass --no-llm-normalize to run conservative SOTA grouping."
        )
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
