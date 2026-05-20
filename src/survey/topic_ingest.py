from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Union

import yaml

from src.reader.reading_renderer import validate_safe_paper_id
from src.survey.models import TopicProfile

MetadataValue = Union[int, str]
ReadService = Callable[..., Awaitable[tuple[Path, Path]]]
UpdateService = Callable[..., Awaitable[Path]]


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


@dataclass(frozen=True)
class PlannedIngestEntry:
    paper_id: str
    title: str
    source_kind: str
    source_path: Path
    output_json_path: Path
    output_markdown_path: Path
    metadata: dict[str, MetadataValue] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicIngestPlan:
    topic_path: Path
    topic_dir: Path
    topic: TopicProfile
    manifest: IngestManifest
    readings_dir: Path
    to_read: list[PlannedIngestEntry]
    skipped_existing: list[PlannedIngestEntry]


@dataclass
class IngestUpdateReport:
    status: str
    report_path: str | Path | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "status": self.status,
            "report_path": (
                str(self.report_path) if self.report_path is not None else None
            ),
        }
        if self.error:
            raw["error"] = self.error
        return raw


@dataclass
class TopicIngestReport:
    topic_id: str
    topic_name: str
    manifest_path: str | Path
    readings_dir: str | Path
    total: int
    read: list[str]
    skipped_existing: list[str]
    failed: list[str]
    artifacts: dict[str, dict[str, str]] = field(default_factory=dict)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    update: IngestUpdateReport = field(
        default_factory=lambda: IngestUpdateReport(status="pending")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "manifest_path": str(self.manifest_path),
            "readings_dir": str(self.readings_dir),
            "total": self.total,
            "read": list(self.read),
            "skipped_existing": list(self.skipped_existing),
            "failed": list(self.failed),
            "artifacts": {
                paper_id: dict(paths) for paper_id, paths in self.artifacts.items()
            },
            "metadata": {
                paper_id: dict(metadata)
                for paper_id, metadata in self.metadata.items()
            },
            "update": self.update.to_dict(),
        }


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


def plan_topic_ingest(
    topic_path: Path,
    manifest_path: Path,
    readings_dir: Path | None,
    force: bool,
) -> TopicIngestPlan:
    from src.survey.cli import _load_topic, _validate_topic_path

    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    manifest = load_ingest_manifest(manifest_path)
    resolved_readings_dir = (
        readings_dir if readings_dir is not None else topic_dir / "papers"
    )

    to_read: list[PlannedIngestEntry] = []
    skipped_existing: list[PlannedIngestEntry] = []
    for paper in manifest.papers:
        planned = PlannedIngestEntry(
            paper_id=paper.paper_id,
            title=paper.title,
            source_kind=paper.source_kind,
            source_path=paper.source_path,
            output_json_path=resolved_readings_dir / f"{paper.paper_id}.json",
            output_markdown_path=resolved_readings_dir
            / f"{paper.paper_id}.reading.md",
            metadata=dict(paper.metadata),
        )
        if planned.output_json_path.exists() and not force:
            skipped_existing.append(planned)
        else:
            to_read.append(planned)

    return TopicIngestPlan(
        topic_path=topic_path,
        topic_dir=topic_dir,
        topic=topic,
        manifest=manifest,
        readings_dir=resolved_readings_dir,
        to_read=to_read,
        skipped_existing=skipped_existing,
    )


def write_topic_ingest_report(topic_dir: Path, report: TopicIngestReport) -> Path:
    report_path = topic_dir / "state" / "ingest_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return report_path


async def ingest_topic_papers(
    topic_path: Path,
    manifest_path: Path,
    readings_dir: Path | None,
    force: bool,
    update: bool,
    no_llm_normalize: bool,
    read_service: ReadService,
    update_service: UpdateService | None,
) -> TopicIngestReport:
    plan = plan_topic_ingest(
        topic_path=topic_path,
        manifest_path=manifest_path,
        readings_dir=readings_dir,
        force=force,
    )
    report = TopicIngestReport(
        topic_id=plan.topic.topic_id,
        topic_name=plan.topic.name,
        manifest_path=plan.manifest.manifest_path,
        readings_dir=plan.readings_dir,
        total=len(plan.manifest.papers),
        read=[],
        skipped_existing=[entry.paper_id for entry in plan.skipped_existing],
        failed=[],
        metadata={
            entry.paper_id: dict(entry.metadata)
            for entry in [*plan.to_read, *plan.skipped_existing]
            if entry.metadata
        },
        update=IngestUpdateReport(status="pending"),
    )

    for entry in plan.to_read:
        try:
            json_path, markdown_path = await read_service(
                paper_id=entry.paper_id,
                title=entry.title,
                source_path=entry.source_path,
                source_kind=entry.source_kind,
                output_dir=plan.readings_dir,
                topic=plan.topic,
            )
        except Exception:
            report.failed.append(entry.paper_id)
            report.update = IngestUpdateReport(status="skipped")
            write_topic_ingest_report(plan.topic_dir, report)
            raise

        report.read.append(entry.paper_id)
        report.artifacts[entry.paper_id] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }
    if not update:
        report.update = IngestUpdateReport(status="skipped")
        write_topic_ingest_report(plan.topic_dir, report)
        return report

    if update_service is None:
        report.update = IngestUpdateReport(
            status="failed",
            error="update_service is required when update=True",
        )
        write_topic_ingest_report(plan.topic_dir, report)
        raise ValueError("update_service is required when update=True")

    try:
        update_report_path = await update_service(
            topic_path=plan.topic_path,
            readings_dir=plan.readings_dir,
            no_llm_normalize=no_llm_normalize,
        )
    except SystemExit as exc:
        report.update = IngestUpdateReport(status="failed", error=str(exc))
        write_topic_ingest_report(plan.topic_dir, report)
        raise
    except Exception as exc:
        report.update = IngestUpdateReport(status="failed", error=str(exc))
        write_topic_ingest_report(plan.topic_dir, report)
        raise

    report.update = IngestUpdateReport(
        status="updated",
        report_path=str(update_report_path),
    )
    write_topic_ingest_report(plan.topic_dir, report)
    return report


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
