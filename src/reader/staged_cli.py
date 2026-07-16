from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from src.config import load_config
from src.llm.client import create_llm_client, normalize_llm_config
from src.reader.latex_source_extractor import extract_tables_from_latex_source
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
    source_archive_path: Path | None = None,
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

    source_tables = []
    if source_archive_path is not None and source_archive_path.exists():
        try:
            source_tables = extract_tables_from_latex_source(source_archive_path)
        except Exception:
            source_tables = []

    package = await reader.read(
        paper_id=paper_id,
        title=title,
        source_path=str(source_path),
        pages=pages,
        topic=topic,
        source_tables=source_tables,
    )
    return write_reading_package(package, output_dir)


async def cmd_read_staged(args) -> None:
    try:
        validate_safe_paper_id(args.paper_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    load_dotenv()
    app_config = load_config(args.config)
    llm_config = normalize_llm_config(app_config.llm)
    if not llm_config.api_key:
        raise SystemExit(f"Error: {llm_config.api_key_env} environment variable not set.")

    topic_path = Path(args.topic) if args.topic else None
    topic = _load_topic(topic_path) if topic_path else None
    output_dir = _resolve_output_dir(
        args,
        topic_path=topic_path,
    )

    reader = StagedPaperReader(
        create_llm_client(llm_config), model=llm_config.reader_model
    )
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
