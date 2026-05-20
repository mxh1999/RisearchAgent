from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.page_extractor import extract_pages_from_pdf, extract_pages_from_text_file
from src.reader.reading_renderer import validate_safe_paper_id, write_reading_package
from src.reader.staged_reader import StagedPaperReader
from src.survey.models import TopicProfile


async def read_staged_source(
    reader,
    paper_id: str,
    title: str,
    source_path: Path,
    source_kind: str,
    output_dir: Path,
    topic: Optional[TopicProfile],
) -> tuple[Path, Path]:
    try:
        validate_safe_paper_id(paper_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if source_kind == "pdf":
        pages = extract_pages_from_pdf(source_path)
    elif source_kind == "text_file":
        pages = extract_pages_from_text_file(source_path)
    else:
        raise ValueError(f"Unknown source_kind: {source_kind}")

    package = await reader.read(
        paper_id=paper_id,
        title=title,
        source_path=str(source_path),
        pages=pages,
        topic=topic,
    )
    return write_reading_package(package, output_dir)


async def cmd_read_staged(args) -> None:
    try:
        validate_safe_paper_id(args.paper_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for staged read. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

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

    topic_path = Path(args.topic) if args.topic else None
    topic = _load_topic(topic_path) if topic_path else None
    output_dir = _resolve_output_dir(
        args,
        topic_path=topic_path,
    )

    reader = StagedPaperReader(GeminiClient(llm_config), model=llm_config.reader_model)
    source_path = Path(args.pdf or args.text_file)
    json_path, markdown_path = await read_staged_source(
        reader=reader,
        paper_id=args.paper_id,
        title=args.title,
        source_path=source_path,
        source_kind="pdf" if args.pdf else "text_file",
        output_dir=output_dir,
        topic=topic,
    )

    print(f"Reading JSON: {json_path}")
    print(f"Reading Markdown: {markdown_path}")


def run_read_staged(args) -> None:
    asyncio.run(cmd_read_staged(args))


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


def _resolve_output_dir(args, topic_path: Optional[Path]) -> Path:
    if topic_path is not None:
        return topic_path.parent / "papers"
    return Path(args.output_root or "data/readings")
