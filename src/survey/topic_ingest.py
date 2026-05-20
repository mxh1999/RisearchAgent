from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

import yaml

from src.reader.reading_renderer import validate_safe_paper_id

MetadataValue = Union[int, str]


@dataclass(frozen=True)
class IngestManifestEntry:
    paper_id: str
    title: str
    source_kind: str
    source_path: Path
    metadata: dict[str, MetadataValue] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestManifest:
    manifest_path: Path
    papers: list[IngestManifestEntry]


def load_ingest_manifest(path: Path) -> IngestManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Error loading ingest manifest {path}: not found") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid ingest manifest YAML: {path}") from exc

    if raw is None:
        raise ValueError("Ingest manifest is empty")
    if not isinstance(raw, dict):
        raise ValueError("Ingest manifest must be a mapping with papers")

    papers = raw.get("papers")
    if not isinstance(papers, list):
        raise ValueError("Ingest manifest papers must be a list")

    entries: list[IngestManifestEntry] = []
    seen_paper_ids: set[str] = set()
    base_dir = path.parent
    for index, paper in enumerate(papers):
        entries.append(_load_entry(paper, index, base_dir, seen_paper_ids))

    return IngestManifest(manifest_path=path, papers=entries)


def _load_entry(
    paper: Any,
    index: int,
    base_dir: Path,
    seen_paper_ids: set[str],
) -> IngestManifestEntry:
    if not isinstance(paper, dict):
        raise ValueError(f"Paper entry {index} must be a mapping")

    paper_id = _required_str(paper, "paper_id", index)
    try:
        validate_safe_paper_id(paper_id)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    if paper_id in seen_paper_ids:
        raise ValueError(f"Duplicate paper_id: {paper_id}")
    seen_paper_ids.add(paper_id)

    title = _required_str(paper, "title", index)
    source_keys = [key for key in ("pdf", "text_file") if key in paper]
    if len(source_keys) != 1:
        raise ValueError(f"Paper {paper_id} must specify exactly one of pdf or text_file")

    source_kind = source_keys[0]
    source_value = paper[source_kind]
    if not isinstance(source_value, str) or not source_value:
        raise ValueError(f"Paper {paper_id} {source_kind} must be a non-empty string")

    source_path = (base_dir / source_value).resolve()
    if not source_path.exists():
        raise ValueError(f"Source file does not exist: {source_path}")
    if source_path.is_dir():
        raise ValueError(f"Source path is a directory: {source_path}")

    return IngestManifestEntry(
        paper_id=paper_id,
        title=title,
        source_kind=source_kind,
        source_path=source_path,
        metadata=_load_metadata(paper, paper_id),
    )


def _required_str(paper: dict[str, Any], key: str, index: int) -> str:
    value = paper.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Paper entry {index} requires {key}")
    return value


def _load_metadata(paper: dict[str, Any], paper_id: str) -> dict[str, MetadataValue]:
    metadata: dict[str, MetadataValue] = {}
    if "year" in paper:
        year = paper["year"]
        if not isinstance(year, int) or isinstance(year, bool):
            raise ValueError(f"Paper {paper_id} metadata year must be an int")
        metadata["year"] = year
    for key in ("venue", "source_url", "notes"):
        if key in paper:
            value = paper[key]
            if not isinstance(value, str):
                raise ValueError(f"Paper {paper_id} metadata {key} must be a str")
            metadata[key] = value
    return metadata
