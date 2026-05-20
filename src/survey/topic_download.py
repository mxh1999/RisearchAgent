from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from src.reader.reading_renderer import validate_safe_paper_id
from src.survey.cli import _load_topic, _validate_topic_path

DownloadOne = Callable[[str, Path], Awaitable[None]]


@dataclass(frozen=True)
class DownloadCandidate:
    paper_id: str
    title: str
    pdf_url: str
    source_url: str
    year: int | None
    status: str


@dataclass(frozen=True)
class DownloadOutcome:
    paper_id: str
    title: str
    pdf_path: Path
    source_url: str
    year: int | None


@dataclass
class DownloadReport:
    topic_id: str
    topic_name: str
    candidates_path: Path
    manifest_path: Path
    downloaded: list[DownloadOutcome]
    reused: list[DownloadOutcome]
    skipped: list[dict[str, str]]
    failed: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "candidates_path": str(self.candidates_path),
            "manifest_path": str(self.manifest_path),
            "downloaded": [outcome.paper_id for outcome in self.downloaded],
            "reused": [outcome.paper_id for outcome in self.reused],
            "skipped": [dict(item) for item in self.skipped],
            "failed": [dict(item) for item in self.failed],
            "total_materialized": len(self.downloaded) + len(self.reused),
        }


async def default_download_pdf(pdf_url: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(None, _download_bytes, pdf_url)
        if not content:
            raise ValueError(f"Empty PDF response: {pdf_url}")
        tmp_path.write_bytes(content)
        tmp_path.replace(target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _download_bytes(pdf_url: str) -> bytes:
    import urllib.request

    request = urllib.request.Request(
        pdf_url,
        headers={"User-Agent": "RisearchAgent topic download"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def load_download_candidates(candidates_path: Path, topic_id: str) -> list[DownloadCandidate]:
    try:
        raw = json.loads(candidates_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Error loading discovery candidates {candidates_path}: not found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid discovery candidates JSON: {candidates_path}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Discovery candidates must be a mapping")
    raw_topic_id = raw.get("topic_id")
    if raw_topic_id != topic_id:
        raise ValueError(
            "Discovery candidates topic_id does not match topic YAML "
            f"(topic_id={raw_topic_id!r}, expected={topic_id!r})"
        )
    raw_candidates = raw.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("Discovery candidates must contain a candidates list")

    candidates: list[DownloadCandidate] = []
    for index, raw_candidate in enumerate(raw_candidates):
        if not isinstance(raw_candidate, dict):
            raise ValueError(f"Discovery candidate at index {index} must be a mapping")
        candidates.append(_load_candidate(raw_candidate, index))
    return candidates


async def materialize_topic_downloads(
    *,
    topic_path: Path,
    candidates_path: Path,
    manifest_path: Path,
    limit: int | None,
    include_existing: bool,
    force: bool,
    download_one: DownloadOne | None = None,
) -> DownloadReport:
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")

    candidates = load_download_candidates(candidates_path, topic.topic_id)
    selected: list[DownloadCandidate] = []
    skipped: list[dict[str, str]] = []
    existing_papers = _existing_paper_ids(topic_dir)
    for candidate in candidates:
        if candidate.status != "candidate":
            skipped.append(
                {"paper_id": candidate.paper_id, "reason": f"status: {candidate.status}"}
            )
            continue
        if candidate.paper_id in existing_papers and not include_existing:
            skipped.append(
                {"paper_id": candidate.paper_id, "reason": "existing reading package"}
            )
            continue
        if limit is not None and len(selected) >= limit:
            skipped.append({"paper_id": candidate.paper_id, "reason": "limit"})
            continue
        selected.append(candidate)

    pdf_dir = topic_dir / "pdfs"
    downloader = download_one or default_download_pdf
    downloaded: list[DownloadOutcome] = []
    reused: list[DownloadOutcome] = []
    materialized: list[DownloadOutcome] = []
    failed: list[dict[str, str]] = []

    for candidate in selected:
        pdf_path = pdf_dir / f"{candidate.paper_id}.pdf"
        outcome = DownloadOutcome(
            paper_id=candidate.paper_id,
            title=candidate.title,
            pdf_path=pdf_path,
            source_url=candidate.source_url,
            year=candidate.year,
        )
        if pdf_path.exists() and not force:
            reused.append(outcome)
            materialized.append(outcome)
            continue
        try:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            await downloader(candidate.pdf_url, pdf_path)
        except Exception as exc:
            failed.append({"paper_id": candidate.paper_id, "error": str(exc)})
            continue
        downloaded.append(outcome)
        materialized.append(outcome)

    write_ingest_manifest(manifest_path, materialized)
    report = DownloadReport(
        topic_id=topic.topic_id,
        topic_name=topic.name,
        candidates_path=candidates_path,
        manifest_path=manifest_path,
        downloaded=downloaded,
        reused=reused,
        skipped=skipped,
        failed=failed,
    )
    write_download_report(topic_dir, report)
    return report


def write_ingest_manifest(manifest_path: Path, outcomes: list[DownloadOutcome]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    raw = {"papers": [_manifest_entry(manifest_path, outcome) for outcome in outcomes]}
    manifest_path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def write_download_report(topic_dir: Path, report: DownloadReport) -> Path:
    report_path = topic_dir / "state" / "download_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return report_path


def _load_candidate(raw: dict[str, Any], index: int) -> DownloadCandidate:
    paper_id = _required_str(raw, "paper_id", index)
    validate_safe_paper_id(paper_id)
    status = str(raw.get("status", "candidate"))
    pdf_url = _required_str(raw, "pdf_url", index)
    year = raw.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise ValueError(f"Discovery candidate {paper_id!r} year must be an integer")
    return DownloadCandidate(
        paper_id=paper_id,
        title=_required_str(raw, "title", index),
        pdf_url=pdf_url,
        source_url=_required_str(raw, "source_url", index),
        year=year,
        status=status,
    )


def _required_str(raw: dict[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Discovery candidate at index {index} requires {key}")
    return value.strip()


def _manifest_entry(manifest_path: Path, outcome: DownloadOutcome) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "paper_id": outcome.paper_id,
        "title": outcome.title,
        "pdf": _relative_path(outcome.pdf_path, manifest_path.parent),
        "source_url": outcome.source_url,
        "venue": "arXiv",
    }
    if outcome.year is not None:
        entry["year"] = outcome.year
    return entry


def _relative_path(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _existing_paper_ids(topic_dir: Path) -> set[str]:
    papers_dir = topic_dir / "papers"
    if not papers_dir.exists():
        return set()
    return {path.stem for path in papers_dir.glob("*.json")}
