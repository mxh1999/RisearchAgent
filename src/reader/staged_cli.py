from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.page_extractor import extract_pages_from_pdf, extract_pages_from_text_file
from src.reader.reading_renderer import write_reading_package
from src.reader.staged_reader import StagedPaperReader
from src.survey.models import TopicProfile


async def cmd_read_staged(args) -> None:
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

    source_path = Path(args.pdf or args.text_file)
    if args.pdf:
        pages = extract_pages_from_pdf(source_path)
    else:
        pages = extract_pages_from_text_file(source_path)

    topic = _load_topic_profile(Path(args.topic)) if args.topic else None
    output_dir = _resolve_output_dir(
        args,
        topic_path=Path(args.topic) if args.topic else None,
    )

    reader = StagedPaperReader(GeminiClient(llm_config), model=llm_config.reader_model)
    package = await reader.read(
        paper_id=args.paper_id,
        title=args.title,
        source_path=str(source_path),
        pages=pages,
        topic=topic,
    )
    json_path, markdown_path = write_reading_package(package, output_dir)

    print(f"Reading JSON: {json_path}")
    print(f"Reading Markdown: {markdown_path}")


def run_read_staged(args) -> None:
    asyncio.run(cmd_read_staged(args))


def _load_topic_profile(path: Path) -> TopicProfile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Topic YAML must contain an object: {path}")
    return TopicProfile.from_dict(raw)


def _resolve_output_dir(args, topic_path: Optional[Path]) -> Path:
    if topic_path is not None:
        return topic_path.parent / "papers"
    return Path(args.output_root or "data/readings")
