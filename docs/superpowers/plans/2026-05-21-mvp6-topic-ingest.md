# MVP-6 Topic Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `python run.py topic ingest --topic ... --manifest ...`, a deterministic batch ingestion workflow that turns local PDF/text manifest entries into topic-scoped staged reading packages and an ingest report.

**Architecture:** Add a focused `src/survey/topic_ingest.py` service for manifest validation, ingestion planning, report models, and orchestration. Add `src/survey/ingest_cli.py` for CLI-facing LLM setup and console output. Refactor `src/reader/staged_cli.py` to expose a reusable staged-read service while keeping `read --staged` behavior unchanged.

**Tech Stack:** Python dataclasses, pathlib, PyYAML, pytest, existing staged reader models/rendering, existing topic update orchestration.

---

## File Structure

- Create `src/survey/topic_ingest.py`
  - `IngestManifestEntry`, `IngestManifest`, `PlannedIngestEntry`, `IngestUpdateReport`, `TopicIngestReport`
  - `load_ingest_manifest(path: Path) -> IngestManifest`
  - `plan_topic_ingest(topic_path: Path, manifest_path: Path, readings_dir: Path | None, force: bool) -> TopicIngestPlan`
  - `write_topic_ingest_report(topic_dir: Path, report: TopicIngestReport) -> Path`
  - `ingest_topic_papers(...) -> TopicIngestReport`
- Create `src/survey/ingest_cli.py`
  - `async cmd_topic_ingest(args) -> None`
  - small console summary
- Modify `src/reader/staged_cli.py`
  - add reusable `read_staged_source(...)` service using existing extractor, reader, renderer
  - update `cmd_read_staged` to call the service
- Modify `src/survey/topic_cli.py`
  - dispatch `topic ingest`
- Modify `run.py`
  - parse `topic ingest` arguments and validation
- Create `tests/survey/test_topic_ingest.py`
  - manifest validation, planning, reporting, orchestration with fake reader
- Modify `tests/reader/test_staged_cli.py`
  - cover reusable staged-read service
- Modify `tests/survey/test_topic_update.py` or create parser coverage inside `test_topic_ingest.py`
  - cover `topic ingest` parser

---

### Task 1: Manifest Models And Validation

**Files:**
- Create: `src/survey/topic_ingest.py`
- Test: `tests/survey/test_topic_ingest.py`

- [ ] **Step 1: Write failing manifest validation tests**

Add `tests/survey/test_topic_ingest.py`:

```python
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.survey.topic_ingest import load_ingest_manifest


def _write_manifest(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return path


def test_load_ingest_manifest_accepts_pdf_and_text_entries(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    text_path = tmp_path / "paper.txt"
    pdf_path.write_text("pdf bytes for path validation", encoding="utf-8")
    text_path.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        tmp_path / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample_pdf
            title: Sample PDF
            pdf: paper.pdf
            year: 2024
            venue: arXiv
            source_url: https://arxiv.org/abs/0000.00000
            notes: Important baseline
          - paper_id: sample_text
            title: Sample Text
            text_file: paper.txt
        """,
    )

    manifest = load_ingest_manifest(manifest_path)

    assert [entry.paper_id for entry in manifest.papers] == ["sample_pdf", "sample_text"]
    assert manifest.papers[0].source_path == pdf_path
    assert manifest.papers[0].source_kind == "pdf"
    assert manifest.papers[0].metadata == {
        "year": 2024,
        "venue": "arXiv",
        "source_url": "https://arxiv.org/abs/0000.00000",
        "notes": "Important baseline",
    }
    assert manifest.papers[1].source_path == text_path
    assert manifest.papers[1].source_kind == "text_file"


@pytest.mark.parametrize(
    "content, message",
    [
        ("", "empty"),
        ("papers: {}", "papers"),
        ("papers:\n  - title: Missing ID\n    text_file: paper.txt\n", "paper_id"),
        ("papers:\n  - paper_id: sample\n    text_file: paper.txt\n", "title"),
        (
            "papers:\n  - paper_id: sample\n    title: Sample\n    pdf: a.pdf\n    text_file: a.txt\n",
            "exactly one",
        ),
        ("papers:\n  - paper_id: sample\n    title: Sample\n", "exactly one"),
        ("papers:\n  - paper_id: ../escape\n    title: Sample\n    text_file: paper.txt\n", "Unsafe paper_id"),
        (
            "papers:\n  - paper_id: dup\n    title: One\n    text_file: a.txt\n"
            "  - paper_id: dup\n    title: Two\n    text_file: b.txt\n",
            "Duplicate paper_id",
        ),
    ],
)
def test_load_ingest_manifest_rejects_invalid_entries(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    manifest_path = _write_manifest(tmp_path / "ingest_manifest.yaml", content)

    with pytest.raises(ValueError, match=message):
        load_ingest_manifest(manifest_path)


def test_load_ingest_manifest_rejects_missing_source_file(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: missing.txt
        """,
    )

    with pytest.raises(ValueError, match="does not exist"):
        load_ingest_manifest(manifest_path)


def test_load_ingest_manifest_rejects_source_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "source_dir"
    source_dir.mkdir()
    manifest_path = _write_manifest(
        tmp_path / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: source_dir
        """,
    )

    with pytest.raises(ValueError, match="is a directory"):
        load_ingest_manifest(manifest_path)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.survey.topic_ingest'`.

- [ ] **Step 3: Implement manifest models and loader**

Create `src/survey/topic_ingest.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.reader.reading_renderer import validate_safe_paper_id


@dataclass(frozen=True)
class IngestManifestEntry:
    paper_id: str
    title: str
    source_kind: str
    source_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)


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
        raise ValueError(f"Error loading ingest manifest {path}: invalid YAML: {exc}") from exc

    if raw is None:
        raise ValueError(f"Error loading ingest manifest {path}: empty YAML")
    if not isinstance(raw, dict):
        raise ValueError(f"Error loading ingest manifest {path}: expected mapping object")
    papers_raw = raw.get("papers")
    if not isinstance(papers_raw, list):
        raise ValueError(f"Error loading ingest manifest {path}: papers must be a list")

    entries: list[IngestManifestEntry] = []
    seen: set[str] = set()
    base_dir = path.parent
    for index, item in enumerate(papers_raw):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest paper entry {index} must be a mapping")
        entry = _parse_manifest_entry(item, base_dir=base_dir, index=index)
        if entry.paper_id in seen:
            raise ValueError(f"Duplicate paper_id in ingest manifest: {entry.paper_id}")
        seen.add(entry.paper_id)
        entries.append(entry)
    return IngestManifest(manifest_path=path, papers=entries)


def _parse_manifest_entry(
    raw: dict[str, Any],
    base_dir: Path,
    index: int,
) -> IngestManifestEntry:
    paper_id = raw.get("paper_id")
    title = raw.get("title")
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError(f"Manifest paper entry {index} missing paper_id")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Manifest paper entry {index} missing title")
    validate_safe_paper_id(paper_id)

    has_pdf = raw.get("pdf") is not None
    has_text = raw.get("text_file") is not None
    if has_pdf == has_text:
        raise ValueError(
            f"Manifest paper entry {paper_id} must specify exactly one of pdf or text_file"
        )
    source_kind = "pdf" if has_pdf else "text_file"
    source_value = raw["pdf"] if has_pdf else raw["text_file"]
    if not isinstance(source_value, str) or not source_value.strip():
        raise ValueError(f"Manifest paper entry {paper_id} source path must be a string")
    source_path = (base_dir / source_value).resolve()
    if not source_path.exists():
        raise ValueError(f"Source file for {paper_id} does not exist: {source_path}")
    if source_path.is_dir():
        raise ValueError(f"Source file for {paper_id} is a directory: {source_path}")

    metadata = _extract_metadata(raw)
    return IngestManifestEntry(
        paper_id=paper_id.strip(),
        title=title.strip(),
        source_kind=source_kind,
        source_path=source_path,
        metadata=metadata,
    )


def _extract_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("year", "venue", "source_url", "notes"):
        value = raw.get(key)
        if value is None:
            continue
        if key == "year":
            if not isinstance(value, int):
                raise ValueError("Manifest metadata year must be an integer")
        elif not isinstance(value, str):
            raise ValueError(f"Manifest metadata {key} must be a string")
        metadata[key] = value
    return metadata
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py -q
```

Expected: all tests in the new file pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/topic_ingest.py tests/survey/test_topic_ingest.py
git commit -m "feat: add ingest manifest validation"
```

---

### Task 2: Ingest Planning And Report Models

**Files:**
- Modify: `src/survey/topic_ingest.py`
- Test: `tests/survey/test_topic_ingest.py`

- [ ] **Step 1: Write failing planning and report tests**

Append to `tests/survey/test_topic_ingest.py`:

```python
import json

from src.survey.topic_ingest import (
    IngestUpdateReport,
    TopicIngestReport,
    plan_topic_ingest,
    write_topic_ingest_report,
)


def _write_topic(topic_dir: Path) -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            """
            # Keep this user note.
            topic_id: utility_nav
            name: Utility Navigation
            description: Task-conditioned utility over 3D memory.
            intent: Maintain topic artifacts.
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


def test_plan_topic_ingest_skips_existing_package_without_force(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    source = tmp_path / "paper.txt"
    source.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        topic_dir / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: ../paper.txt
        """,
    )
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir()
    (papers_dir / "sample.json").write_text("{}", encoding="utf-8")

    plan = plan_topic_ingest(topic_path, manifest_path, readings_dir=None, force=False)

    assert plan.topic.topic_id == "utility_nav"
    assert [entry.paper_id for entry in plan.to_read] == []
    assert [entry.paper_id for entry in plan.skipped_existing] == ["sample"]
    assert plan.readings_dir == papers_dir


def test_plan_topic_ingest_reads_existing_package_with_force(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    source = tmp_path / "paper.txt"
    source.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        topic_dir / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: ../paper.txt
        """,
    )
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir()
    (papers_dir / "sample.json").write_text("{}", encoding="utf-8")

    plan = plan_topic_ingest(topic_path, manifest_path, readings_dir=None, force=True)

    assert [entry.paper_id for entry in plan.to_read] == ["sample"]
    assert plan.skipped_existing == []


def test_plan_topic_ingest_uses_readings_dir_override(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    source = tmp_path / "paper.txt"
    source.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        topic_dir / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: ../paper.txt
        """,
    )
    readings_dir = tmp_path / "custom_readings"

    plan = plan_topic_ingest(topic_path, manifest_path, readings_dir=readings_dir, force=False)

    assert plan.readings_dir == readings_dir
    assert [entry.output_json_path for entry in plan.to_read] == [
        readings_dir / "sample.json"
    ]


def test_write_topic_ingest_report_json(tmp_path: Path) -> None:
    report = TopicIngestReport(
        topic_id="utility_nav",
        topic_name="Utility Navigation",
        manifest_path="manifest.yaml",
        readings_dir="papers",
        total=1,
        read=["sample"],
        skipped_existing=[],
        failed=[],
        artifacts={"sample": {"json": "papers/sample.json", "markdown": "papers/sample.reading.md"}},
        metadata={"sample": {"year": 2024}},
        update=IngestUpdateReport(status="skipped", report_path=None),
    )

    path = write_topic_ingest_report(tmp_path / "utility_nav", report)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert path == tmp_path / "utility_nav" / "state" / "ingest_report.json"
    assert raw["topic_id"] == "utility_nav"
    assert raw["read"] == ["sample"]
    assert raw["update"]["status"] == "skipped"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py -q
```

Expected: fail with import errors for `plan_topic_ingest`, `TopicIngestReport`, or `write_topic_ingest_report`.

- [ ] **Step 3: Implement planning and report models**

Extend `src/survey/topic_ingest.py`:

```python
import json

from src.survey.cli import _load_topic, _validate_topic_path
from src.survey.models import TopicProfile


@dataclass(frozen=True)
class PlannedIngestEntry:
    paper_id: str
    title: str
    source_kind: str
    source_path: Path
    output_json_path: Path
    output_markdown_path: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicIngestPlan:
    topic_path: Path
    topic_dir: Path
    topic: TopicProfile
    manifest: IngestManifest
    readings_dir: Path
    to_read: list[PlannedIngestEntry]
    skipped_existing: list[PlannedIngestEntry]


@dataclass(frozen=True)
class IngestUpdateReport:
    status: str
    report_path: str | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        raw: dict[str, Any] = {"status": self.status, "report_path": self.report_path}
        if self.error:
            raw["error"] = self.error
        return raw


@dataclass(frozen=True)
class TopicIngestReport:
    topic_id: str
    topic_name: str
    manifest_path: str
    readings_dir: str
    total: int
    read: list[str]
    skipped_existing: list[str]
    failed: list[str]
    artifacts: dict[str, dict[str, str]]
    metadata: dict[str, dict[str, Any]]
    update: IngestUpdateReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "manifest_path": self.manifest_path,
            "readings_dir": self.readings_dir,
            "total": self.total,
            "read": list(self.read),
            "skipped_existing": list(self.skipped_existing),
            "failed": list(self.failed),
            "artifacts": self.artifacts,
            "metadata": self.metadata,
            "update": self.update.to_dict(),
        }


def plan_topic_ingest(
    topic_path: Path,
    manifest_path: Path,
    readings_dir: Path | None,
    force: bool,
) -> TopicIngestPlan:
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    manifest = load_ingest_manifest(manifest_path)
    output_dir = readings_dir if readings_dir is not None else topic_dir / "papers"
    to_read: list[PlannedIngestEntry] = []
    skipped_existing: list[PlannedIngestEntry] = []

    for entry in manifest.papers:
        planned = PlannedIngestEntry(
            paper_id=entry.paper_id,
            title=entry.title,
            source_kind=entry.source_kind,
            source_path=entry.source_path,
            output_json_path=output_dir / f"{entry.paper_id}.json",
            output_markdown_path=output_dir / f"{entry.paper_id}.reading.md",
            metadata=dict(entry.metadata),
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
        readings_dir=output_dir,
        to_read=to_read,
        skipped_existing=skipped_existing,
    )


def write_topic_ingest_report(topic_dir: Path, report: TopicIngestReport) -> Path:
    report_path = topic_dir / "state" / "ingest_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py -q
```

Expected: all `test_topic_ingest.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/topic_ingest.py tests/survey/test_topic_ingest.py
git commit -m "feat: add topic ingest planning"
```

---

### Task 3: Reusable Staged Read Service

**Files:**
- Modify: `src/reader/staged_cli.py`
- Test: `tests/reader/test_staged_cli.py`

- [ ] **Step 1: Write failing staged read service test**

Append to `tests/reader/test_staged_cli.py`:

```python
from pathlib import Path

from src.reader.staged_models import PaperReadingPackage


class FakeStagedReader:
    def __init__(self) -> None:
        self.calls = []

    async def read(self, paper_id, title, source_path, pages, topic):
        self.calls.append(
            {
                "paper_id": paper_id,
                "title": title,
                "source_path": source_path,
                "pages": pages,
                "topic": topic,
            }
        )
        return PaperReadingPackage(
            paper_id=paper_id,
            title=title,
            source_path=source_path,
            pages=pages,
        )


def test_read_staged_source_reads_text_and_writes_package(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("First page text", encoding="utf-8")
    output_dir = tmp_path / "papers"
    reader = FakeStagedReader()

    json_path, markdown_path = asyncio.run(
        staged_cli.read_staged_source(
            reader=reader,
            paper_id="sample",
            title="Sample Paper",
            source_path=source,
            source_kind="text_file",
            output_dir=output_dir,
            topic=None,
        )
    )

    assert json_path == output_dir / "sample.json"
    assert markdown_path == output_dir / "sample.reading.md"
    assert json_path.exists()
    assert markdown_path.exists()
    assert reader.calls[0]["paper_id"] == "sample"
    assert reader.calls[0]["pages"][0].text == "First page text"
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
python -m pytest tests/reader/test_staged_cli.py::test_read_staged_source_reads_text_and_writes_package -q
```

Expected: fail with `AttributeError: module 'src.reader.staged_cli' has no attribute 'read_staged_source'`.

- [ ] **Step 3: Implement reusable service and refactor CLI**

Modify `src/reader/staged_cli.py`:

```python
async def read_staged_source(
    reader: StagedPaperReader,
    paper_id: str,
    title: str,
    source_path: Path,
    source_kind: str,
    output_dir: Path,
    topic: TopicProfile | None,
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
        raise ValueError(f"Unsupported staged source kind: {source_kind}")
    package = await reader.read(
        paper_id=paper_id,
        title=title,
        source_path=str(source_path),
        pages=pages,
        topic=topic,
    )
    return write_reading_package(package, output_dir)
```

Then replace the extraction/read/write block in `cmd_read_staged` with:

```python
source_path = Path(args.pdf or args.text_file)
source_kind = "pdf" if args.pdf else "text_file"
reader = StagedPaperReader(GeminiClient(llm_config), model=llm_config.reader_model)
json_path, markdown_path = await read_staged_source(
    reader=reader,
    paper_id=args.paper_id,
    title=args.title,
    source_path=source_path,
    source_kind=source_kind,
    output_dir=output_dir,
    topic=topic,
)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/reader/test_staged_cli.py -q
```

Expected: all staged CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/reader/staged_cli.py tests/reader/test_staged_cli.py
git commit -m "feat: expose staged read service"
```

---

### Task 4: Topic Ingest Orchestration

**Files:**
- Modify: `src/survey/topic_ingest.py`
- Test: `tests/survey/test_topic_ingest.py`

- [ ] **Step 1: Write failing orchestration tests**

Append to `tests/survey/test_topic_ingest.py`:

```python
import asyncio
import json

from src.reader.staged_models import PaperReadingPackage
from src.survey.topic_ingest import ingest_topic_papers


class FakeReadService:
    def __init__(self) -> None:
        self.calls = []

    async def __call__(
        self,
        *,
        paper_id: str,
        title: str,
        source_path: Path,
        source_kind: str,
        output_dir: Path,
        topic,
    ):
        self.calls.append(
            {
                "paper_id": paper_id,
                "title": title,
                "source_path": source_path,
                "source_kind": source_kind,
                "output_dir": output_dir,
                "topic_id": topic.topic_id,
            }
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{paper_id}.json"
        markdown_path = output_dir / f"{paper_id}.reading.md"
        json_path.write_text(
            json.dumps(
                PaperReadingPackage(
                    paper_id=paper_id,
                    title=title,
                    source_path=str(source_path),
                ).to_dict()
            ),
            encoding="utf-8",
        )
        markdown_path.write_text(f"# {title}\n", encoding="utf-8")
        return json_path, markdown_path


class FakeTopicUpdater:
    def __init__(self) -> None:
        self.calls = []

    async def __call__(self, *, topic_path: Path, readings_dir: Path, no_llm_normalize: bool):
        self.calls.append(
            {
                "topic_path": topic_path,
                "readings_dir": readings_dir,
                "no_llm_normalize": no_llm_normalize,
            }
        )
        report_path = topic_path.parent / "state" / "topic_update_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        return report_path


def test_ingest_topic_papers_reads_missing_papers_and_writes_report(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    source = tmp_path / "paper.txt"
    source.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        topic_dir / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: ../paper.txt
            year: 2024
        """,
    )
    original_yaml = topic_path.read_text(encoding="utf-8")
    read_service = FakeReadService()

    report = asyncio.run(
        ingest_topic_papers(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=None,
            force=False,
            update=False,
            no_llm_normalize=False,
            read_service=read_service,
            update_service=None,
        )
    )

    assert topic_path.read_text(encoding="utf-8") == original_yaml
    assert [call["paper_id"] for call in read_service.calls] == ["sample"]
    assert report.read == ["sample"]
    assert report.skipped_existing == []
    assert report.metadata == {"sample": {"year": 2024}}
    assert (topic_dir / "state" / "ingest_report.json").exists()


def test_ingest_topic_papers_skips_existing_and_can_update(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    source = tmp_path / "paper.txt"
    source.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        topic_dir / "ingest_manifest.yaml",
        """
        papers:
          - paper_id: sample
            title: Sample
            text_file: ../paper.txt
        """,
    )
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir()
    (papers_dir / "sample.json").write_text("{}", encoding="utf-8")
    read_service = FakeReadService()
    update_service = FakeTopicUpdater()

    report = asyncio.run(
        ingest_topic_papers(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=None,
            force=False,
            update=True,
            no_llm_normalize=True,
            read_service=read_service,
            update_service=update_service,
        )
    )

    assert read_service.calls == []
    assert report.read == []
    assert report.skipped_existing == ["sample"]
    assert report.update.status == "updated"
    assert report.update.report_path == str(topic_dir / "state" / "topic_update_report.json")
    assert update_service.calls == [
        {
            "topic_path": topic_path,
            "readings_dir": papers_dir,
            "no_llm_normalize": True,
        }
    ]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py -q
```

Expected: fail with missing `ingest_topic_papers`.

- [ ] **Step 3: Implement orchestration**

Extend `src/survey/topic_ingest.py`:

```python
from collections.abc import Awaitable, Callable


ReadService = Callable[..., Awaitable[tuple[Path, Path]]]
UpdateService = Callable[..., Awaitable[Path]]


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
    read_ids: list[str] = []
    failed: list[str] = []
    artifacts: dict[str, dict[str, str]] = {}
    metadata: dict[str, dict[str, Any]] = {}

    try:
        for entry in plan.to_read:
            metadata[entry.paper_id] = dict(entry.metadata)
            json_path, markdown_path = await read_service(
                paper_id=entry.paper_id,
                title=entry.title,
                source_path=entry.source_path,
                source_kind=entry.source_kind,
                output_dir=plan.readings_dir,
                topic=plan.topic,
            )
            read_ids.append(entry.paper_id)
            artifacts[entry.paper_id] = {
                "json": str(json_path),
                "markdown": str(markdown_path),
            }
    except Exception:
        failed.append(entry.paper_id)
        report = _build_ingest_report(
            plan=plan,
            read_ids=read_ids,
            failed=failed,
            artifacts=artifacts,
            metadata=metadata,
            update_report=IngestUpdateReport(status="skipped", report_path=None),
        )
        write_topic_ingest_report(plan.topic_dir, report)
        raise

    update_report = IngestUpdateReport(status="skipped", report_path=None)
    if update:
        if update_service is None:
            raise ValueError("update_service is required when update is enabled")
        try:
            update_report_path = await update_service(
                topic_path=topic_path,
                readings_dir=plan.readings_dir,
                no_llm_normalize=no_llm_normalize,
            )
            update_report = IngestUpdateReport(
                status="updated",
                report_path=str(update_report_path),
            )
        except Exception as exc:
            update_report = IngestUpdateReport(
                status="failed",
                report_path=None,
                error=str(exc),
            )
            report = _build_ingest_report(
                plan=plan,
                read_ids=read_ids,
                failed=failed,
                artifacts=artifacts,
                metadata=metadata,
                update_report=update_report,
            )
            write_topic_ingest_report(plan.topic_dir, report)
            raise

    report = _build_ingest_report(
        plan=plan,
        read_ids=read_ids,
        failed=failed,
        artifacts=artifacts,
        metadata=metadata,
        update_report=update_report,
    )
    write_topic_ingest_report(plan.topic_dir, report)
    return report


def _build_ingest_report(
    plan: TopicIngestPlan,
    read_ids: list[str],
    failed: list[str],
    artifacts: dict[str, dict[str, str]],
    metadata: dict[str, dict[str, Any]],
    update_report: IngestUpdateReport,
) -> TopicIngestReport:
    for entry in plan.skipped_existing:
        if entry.metadata:
            metadata[entry.paper_id] = dict(entry.metadata)
    return TopicIngestReport(
        topic_id=plan.topic.topic_id,
        topic_name=plan.topic.name,
        manifest_path=str(plan.manifest.manifest_path),
        readings_dir=str(plan.readings_dir),
        total=len(plan.manifest.papers),
        read=read_ids,
        skipped_existing=[entry.paper_id for entry in plan.skipped_existing],
        failed=failed,
        artifacts=artifacts,
        metadata=metadata,
        update=update_report,
    )
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py -q
```

Expected: all ingest tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/topic_ingest.py tests/survey/test_topic_ingest.py
git commit -m "feat: add topic ingest orchestration"
```

---

### Task 5: CLI Integration

**Files:**
- Create: `src/survey/ingest_cli.py`
- Modify: `src/survey/topic_cli.py`
- Modify: `run.py`
- Test: `tests/survey/test_topic_ingest.py`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/survey/test_topic_ingest.py`:

```python
import types

from run import build_parser
from src.survey import ingest_cli


def test_topic_ingest_parser_accepts_options() -> None:
    args = build_parser().parse_args(
        [
            "topic",
            "ingest",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--manifest",
            "data/topics/utility_nav/ingest_manifest.yaml",
            "--readings-dir",
            "data/readings",
            "--force",
            "--update",
            "--no-llm-normalize",
        ]
    )

    assert args.command == "topic"
    assert args.topic_command == "ingest"
    assert args.topic == "data/topics/utility_nav/topic.yaml"
    assert args.manifest == "data/topics/utility_nav/ingest_manifest.yaml"
    assert args.readings_dir == "data/readings"
    assert args.force is True
    assert args.update is True
    assert args.no_llm_normalize is True


def test_cmd_topic_ingest_reports_local_manifest_error_before_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = topic_dir / "missing.yaml"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("src.survey.ingest_cli.load_dotenv", lambda: None)
    monkeypatch.setattr(
        "src.survey.ingest_cli.load_config",
        lambda path: pytest.fail("load_config should not run before local validation"),
    )

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(
            ingest_cli.cmd_topic_ingest(
                types.SimpleNamespace(
                    config="config.yaml",
                    topic=str(topic_path),
                    manifest=str(manifest_path),
                    readings_dir=None,
                    force=False,
                    update=False,
                    no_llm_normalize=False,
                )
            )
        )

    assert "ingest manifest" in str(exc_info.value)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py::test_topic_ingest_parser_accepts_options tests/survey/test_topic_ingest.py::test_cmd_topic_ingest_reports_local_manifest_error_before_api_key -q
```

Expected: parser test fails because `topic ingest` does not exist, or import fails because `src.survey.ingest_cli` does not exist.

- [ ] **Step 3: Implement CLI module**

Create `src/survey/ingest_cli.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.staged_cli import read_staged_source
from src.reader.staged_reader import StagedPaperReader
from src.survey.topic_ingest import ingest_topic_papers, plan_topic_ingest
from src.survey.topic_update import load_topic_update_context, update_topic_artifacts
from src.survey.topic_cli import _build_llm


async def cmd_topic_ingest(args) -> None:
    topic_path = Path(args.topic)
    manifest_path = Path(args.manifest)
    readings_dir = Path(args.readings_dir) if args.readings_dir else None

    try:
        plan = plan_topic_ingest(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=readings_dir,
            force=args.force,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    reader = _build_staged_reader(args.config) if plan.to_read else None

    async def read_service(**kwargs):
        if reader is None:
            raise ValueError("reader is required when there are papers to ingest")
        return await read_staged_source(reader=reader, **kwargs)

    async def update_service(
        *,
        topic_path: Path,
        readings_dir: Path,
        no_llm_normalize: bool,
    ) -> Path:
        context = load_topic_update_context(topic_path, readings_dir)
        survey_llm, survey_model = _build_llm(args.config, purpose="topic ingest update")
        sota_llm = None
        sota_model = None
        use_sota_llm = not no_llm_normalize
        if use_sota_llm and context.sota_needs_llm:
            sota_llm, sota_model = _build_llm(
                args.config,
                purpose="SOTA setting normalization",
            )
        await update_topic_artifacts(
            context=context,
            survey_llm=survey_llm,
            survey_model=survey_model,
            sota_llm=sota_llm,
            sota_model=sota_model,
            skip_survey=False,
            skip_sota=False,
            use_sota_llm=use_sota_llm,
        )
        return context.topic_dir / "state" / "topic_update_report.json"

    try:
        report = await ingest_topic_papers(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=readings_dir,
            force=args.force,
            update=args.update,
            no_llm_normalize=args.no_llm_normalize,
            read_service=read_service,
            update_service=update_service if args.update else None,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Report: {topic_path.parent / 'state' / 'ingest_report.json'}")
    print(f"Total: {report.total}")
    print(f"Read: {len(report.read)}")
    print(f"Skipped existing: {len(report.skipped_existing)}")
    print(f"Update: {report.update.status}")


def _build_staged_reader(config_path: str) -> StagedPaperReader:
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for topic ingest. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    import os

    load_dotenv()
    app_config = load_config(config_path)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY environment variable not set for topic ingest.")
    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    return StagedPaperReader(GeminiClient(llm_config), model=llm_config.reader_model)


def run_topic_ingest(args) -> None:
    asyncio.run(cmd_topic_ingest(args))
```

- [ ] **Step 4: Wire `topic ingest` dispatch**

Modify `src/survey/topic_cli.py`:

```python
def run_topic_command(args) -> None:
    if args.topic_command == "update":
        asyncio.run(cmd_topic_update(args))
        return
    if args.topic_command == "ingest":
        from src.survey.ingest_cli import run_topic_ingest

        run_topic_ingest(args)
        return
    raise SystemExit(f"Unknown topic command: {args.topic_command}")
```

- [ ] **Step 5: Add parser in `run.py`**

After the `topic update` parser block in `build_parser`, add:

```python
    topic_ingest_parser = topic_subparsers.add_parser(
        "ingest",
        help="Ingest local PDF or text papers into one topic",
    )
    topic_ingest_parser.add_argument(
        "--topic",
        required=True,
        help="Path to topic.yaml",
    )
    topic_ingest_parser.add_argument(
        "--manifest",
        required=True,
        help="Path to ingest_manifest.yaml",
    )
    topic_ingest_parser.add_argument(
        "--readings-dir",
        help="Directory for staged reading package JSON files",
    )
    topic_ingest_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-read papers even when reading packages already exist",
    )
    topic_ingest_parser.add_argument(
        "--update",
        action="store_true",
        help="Run topic update after ingestion",
    )
    topic_ingest_parser.add_argument(
        "--no-llm-normalize",
        action="store_true",
        help="Use conservative exact SOTA setting grouping during optional update",
    )
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_ingest.py tests/reader/test_staged_cli.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 7: Commit**

```bash
git add run.py src/survey/ingest_cli.py src/survey/topic_cli.py tests/survey/test_topic_ingest.py
git commit -m "feat: add topic ingest CLI"
```

---

### Task 6: Workflow Verification And Smoke

**Files:**
- Modify if needed: `src/survey/ingest_cli.py`, `src/survey/topic_ingest.py`, tests
- Local ignored smoke artifact: `data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/ingest_manifest.yaml`

- [ ] **Step 1: Run full test suite**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

Run:

```bash
python -m compileall src run.py
```

Expected: exits 0.

- [ ] **Step 3: Run import check**

Run:

```bash
python -c "import src.survey.topic_ingest; import src.survey.ingest_cli; import src.reader.staged_cli"
```

Expected: exits 0.

- [ ] **Step 4: Create smoke manifest for existing downloaded PDFs**

Create ignored file `data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/ingest_manifest.yaml` with:

```yaml
papers:
  - paper_id: mtu3d
    title: "Move to Understand a 3D Scene"
    pdf: "../../../pdfs/mvp3-smoke/mtu3d.pdf"
    venue: "arXiv"
  - paper_id: msgnav
    title: "MSGNav: Unleashing the Power of Multi-modal 3D Scene Graph for Zero-Shot Embodied Navigation"
    pdf: "../../../pdfs/mvp3-smoke/msgnav.pdf"
    venue: "arXiv"
  - paper_id: vlfm
    title: "VLFM: Vision-Language Frontier Maps for Zero-Shot Semantic Navigation"
    pdf: "../../../pdfs/mvp3-smoke/vlfm.pdf"
    venue: "arXiv"
```

- [ ] **Step 5: Run skip-only smoke**

Run:

```bash
python run.py topic ingest --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml --manifest data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/ingest_manifest.yaml
```

Expected:

```text
Report: data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/ingest_report.json
Total: 3
Read: 0
Skipped existing: 3
Update: skipped
```

- [ ] **Step 6: Inspect smoke report**

Run:

```bash
python -c "import json; p='data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/ingest_report.json'; d=json.load(open(p, encoding='utf-8')); print(d['total'], d['read'], d['skipped_existing'], d['update']['status'])"
```

Expected:

```text
3 [] ['mtu3d', 'msgnav', 'vlfm'] skipped
```

- [ ] **Step 7: Final status**

Run:

```bash
git status --short --branch
```

Expected: clean except ignored smoke files, with branch ahead by MVP-6 commits.

Do not claim completion until Steps 1-3 pass and the smoke report is inspected.
