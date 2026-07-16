from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from run import build_parser
from src.reader.staged_models import PaperReadingPackage
from src.survey.topic_ingest import (
    IngestUpdateReport,
    TopicIngestReport,
    ingest_topic_papers,
    load_ingest_manifest,
    plan_topic_ingest,
    write_topic_ingest_report,
)


def _write_topic(topic_dir: Path, topic_id: str = "utility_nav") -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            f"""
            topic_id: {topic_id}
            name: Utility Navigation
            description: Task-conditioned utility over 3D memory.
            intent: Build a focused reading set.
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


def _write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _write_valid_manifest(topic_dir: Path) -> Path:
    source_path = topic_dir / "sources" / "sample.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("paper text", encoding="utf-8")
    return _write_manifest(
        topic_dir,
        """
        papers:
          - paper_id: sample
            title: Sample Paper
            text_file: sources/sample.txt
            year: 2024
        """,
    )


class FakeReadService:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_on = fail_on

    async def __call__(
        self,
        *,
        paper_id: str,
        title: str,
        source_path: Path,
        source_kind: str,
        source_archive_path: Path | None = None,
        output_dir: Path,
        topic: object,
    ) -> tuple[Path, Path]:
        self.calls.append(
            {
                "paper_id": paper_id,
                "title": title,
                "source_path": source_path,
                "source_kind": source_kind,
                "source_archive_path": source_archive_path,
                "output_dir": output_dir,
                "topic": topic,
            }
        )
        if self.fail_on == paper_id:
            raise RuntimeError(f"read failed: {paper_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        package = PaperReadingPackage(
            paper_id=paper_id,
            title=title,
            source_path=str(source_path),
        )
        json_path = output_dir / f"{paper_id}.json"
        markdown_path = output_dir / f"{paper_id}.reading.md"
        json_path.write_text(
            json.dumps(package.to_dict(), indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(f"# {title}\n", encoding="utf-8")
        return json_path, markdown_path


class FakeTopicUpdater:
    def __init__(self, fail: bool = False, system_exit: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail = fail
        self.system_exit = system_exit

    async def __call__(
        self,
        *,
        topic_path: Path,
        readings_dir: Path,
        no_llm_normalize: bool,
    ) -> Path:
        self.calls.append(
            {
                "topic_path": topic_path,
                "readings_dir": readings_dir,
                "no_llm_normalize": no_llm_normalize,
            }
        )
        if self.system_exit:
            raise SystemExit("update exited")
        if self.fail:
            raise RuntimeError("update failed")
        report_path = topic_path.parent / "state" / "topic_update_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"status": "ok"}\n', encoding="utf-8")
        return report_path


def test_load_ingest_manifest_returns_entries_with_resolved_sources_and_metadata(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "papers" / "sample.pdf"
    text_path = tmp_path / "texts" / "sample.txt"
    pdf_path.parent.mkdir()
    text_path.parent.mkdir()
    pdf_path.write_bytes(b"%PDF-1.4\n")
    text_path.write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        tmp_path,
        """
        papers:
          - paper_id: sample_pdf
            title: Sample PDF
            pdf: papers/sample.pdf
            year: 2024
            venue: ICLR
            source_url: https://example.com/paper
            notes: Strong baseline.
          - paper_id: sample_text
            title: Sample Text
            text_file: texts/sample.txt
        """,
    )

    manifest = load_ingest_manifest(manifest_path)

    assert manifest.manifest_path == manifest_path
    assert [entry.paper_id for entry in manifest.papers] == ["sample_pdf", "sample_text"]
    assert manifest.papers[0].title == "Sample PDF"
    assert manifest.papers[0].source_kind == "pdf"
    assert manifest.papers[0].source_path == pdf_path.resolve()
    assert manifest.papers[0].metadata == {
        "year": 2024,
        "venue": "ICLR",
        "source_url": "https://example.com/paper",
        "notes": "Strong baseline.",
    }
    assert manifest.papers[0].source_archive_path is None
    assert manifest.papers[1].title == "Sample Text"
    assert manifest.papers[1].source_kind == "text_file"
    assert manifest.papers[1].source_path == text_path.resolve()
    assert manifest.papers[1].source_archive_path is None
    assert manifest.papers[1].metadata == {}


def test_load_ingest_manifest_accepts_optional_source_archive(tmp_path: Path) -> None:
    pdf_path = tmp_path / "papers" / "sample.pdf"
    source_archive_path = tmp_path / "sources" / "sample.tar.gz"
    pdf_path.parent.mkdir()
    source_archive_path.parent.mkdir()
    pdf_path.write_bytes(b"%PDF-1.4\n")
    source_archive_path.write_bytes(b"source archive")
    manifest_path = _write_manifest(
        tmp_path,
        """
        papers:
          - paper_id: sample_pdf
            title: Sample PDF
            pdf: papers/sample.pdf
            source_archive: sources/sample.tar.gz
        """,
    )

    manifest = load_ingest_manifest(manifest_path)

    assert manifest.papers[0].source_archive_path == source_archive_path.resolve()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "empty"),
        ("papers: not-a-list\n", "papers"),
        (
            """
            papers:
              - title: Missing ID
                pdf: paper.pdf
            """,
            "paper_id",
        ),
        (
            """
            papers:
              - paper_id: missing_title
                pdf: paper.pdf
            """,
            "title",
        ),
        (
            """
            papers:
              - paper_id: both_sources
                title: Both Sources
                pdf: paper.pdf
                text_file: paper.txt
            """,
            "exactly one",
        ),
        (
            """
            papers:
              - paper_id: no_source
                title: No Source
            """,
            "exactly one",
        ),
        (
            """
            papers:
              - paper_id: ../unsafe
                title: Unsafe ID
                pdf: paper.pdf
            """,
            "Unsafe paper_id",
        ),
        (
            """
            papers:
              - paper_id: duplicate
                title: First
                pdf: paper.pdf
              - paper_id: duplicate
                title: Second
                pdf: paper.pdf
            """,
            "Duplicate paper_id",
        ),
    ],
)
def test_load_ingest_manifest_rejects_invalid_manifest_shapes(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "paper.txt").write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(tmp_path, content)

    with pytest.raises(ValueError, match=message):
        load_ingest_manifest(manifest_path)


def test_load_ingest_manifest_rejects_missing_source_file(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        """
        papers:
          - paper_id: missing_source
            title: Missing Source
            pdf: missing.pdf
        """,
    )

    with pytest.raises(ValueError, match="does not exist"):
        load_ingest_manifest(manifest_path)


def test_load_ingest_manifest_rejects_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        load_ingest_manifest(tmp_path / "missing.yaml")


def test_load_ingest_manifest_rejects_source_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "source_dir"
    source_dir.mkdir()
    manifest_path = _write_manifest(
        tmp_path,
        """
        papers:
          - paper_id: source_directory
            title: Source Directory
            text_file: source_dir
        """,
    )

    with pytest.raises(ValueError, match="is a directory"):
        load_ingest_manifest(manifest_path)


def test_load_ingest_manifest_rejects_boolean_year(tmp_path: Path) -> None:
    (tmp_path / "paper.txt").write_text("paper text", encoding="utf-8")
    manifest_path = _write_manifest(
        tmp_path,
        """
        papers:
          - paper_id: bad_year
            title: Bad Year
            text_file: paper.txt
            year: true
        """,
    )

    with pytest.raises(ValueError, match="year"):
        load_ingest_manifest(manifest_path)


def test_topic_ingest_parser_accepts_options() -> None:
    args = build_parser().parse_args(
        [
            "topic",
            "ingest",
            "--topic",
            "topic.yaml",
            "--manifest",
            "manifest.yaml",
            "--readings-dir",
            "readings",
            "--force",
            "--update",
            "--no-llm-normalize",
        ]
    )

    assert args.command == "topic"
    assert args.topic_command == "ingest"
    assert args.topic == "topic.yaml"
    assert args.manifest == "manifest.yaml"
    assert args.readings_dir == "readings"
    assert args.force is True
    assert args.update is True
    assert args.no_llm_normalize is True


def test_cmd_topic_ingest_reports_missing_manifest_before_config_or_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.survey import ingest_cli

    topic_path = _write_topic(tmp_path / "utility_nav")
    missing_manifest = tmp_path / "missing.yaml"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        ingest_cli,
        "load_config",
        lambda _config: pytest.fail("load_config should not be called"),
    )

    args = SimpleNamespace(
        config="config.yaml",
        topic=str(topic_path),
        manifest=str(missing_manifest),
        readings_dir=None,
        force=False,
        update=False,
        no_llm_normalize=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(ingest_cli.cmd_topic_ingest(args))

    assert "not found" in str(exc_info.value)
    assert str(missing_manifest) in str(exc_info.value)


def test_cmd_topic_ingest_skip_only_does_not_build_reader_or_require_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.survey import ingest_cli

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    readings_dir = topic_dir / "papers"
    readings_dir.mkdir()
    (readings_dir / "sample.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        ingest_cli,
        "_build_staged_reader",
        lambda _config: pytest.fail("_build_staged_reader should not be called"),
    )

    args = SimpleNamespace(
        config="config.yaml",
        topic=str(topic_path),
        manifest=str(manifest_path),
        readings_dir=None,
        force=False,
        update=False,
        no_llm_normalize=False,
    )

    report = asyncio.run(ingest_cli.cmd_topic_ingest(args))

    assert report.read == []
    assert report.skipped_existing == ["sample"]
    raw_report = json.loads(
        (topic_dir / "state" / "ingest_report.json").read_text(encoding="utf-8")
    )
    assert raw_report["read"] == []
    assert raw_report["skipped_existing"] == ["sample"]
    assert raw_report["metadata"] == {"sample": {"year": 2024}}


def test_plan_topic_ingest_skips_existing_package_without_force(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    readings_dir = topic_dir / "papers"
    readings_dir.mkdir()
    (readings_dir / "sample.json").write_text("{}", encoding="utf-8")

    plan = plan_topic_ingest(
        topic_path=topic_path,
        manifest_path=manifest_path,
        readings_dir=None,
        force=False,
    )

    assert plan.topic_path == topic_path
    assert plan.topic_dir == topic_dir
    assert plan.topic.topic_id == "utility_nav"
    assert plan.manifest.manifest_path == manifest_path
    assert plan.readings_dir == readings_dir
    assert plan.to_read == []
    assert len(plan.skipped_existing) == 1
    skipped = plan.skipped_existing[0]
    assert skipped.paper_id == "sample"
    assert skipped.title == "Sample Paper"
    assert skipped.source_kind == "text_file"
    assert skipped.source_path == (topic_dir / "sources" / "sample.txt").resolve()
    assert skipped.output_json_path == readings_dir / "sample.json"
    assert skipped.output_markdown_path == readings_dir / "sample.reading.md"
    assert skipped.metadata == {"year": 2024}


def test_plan_topic_ingest_reads_existing_package_with_force(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    readings_dir = topic_dir / "papers"
    readings_dir.mkdir()
    (readings_dir / "sample.json").write_text("{}", encoding="utf-8")

    plan = plan_topic_ingest(
        topic_path=topic_path,
        manifest_path=manifest_path,
        readings_dir=None,
        force=True,
    )

    assert [entry.paper_id for entry in plan.to_read] == ["sample"]
    assert plan.skipped_existing == []


def test_plan_topic_ingest_uses_readings_dir_override(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    override_dir = tmp_path / "custom_readings"

    plan = plan_topic_ingest(
        topic_path=topic_path,
        manifest_path=manifest_path,
        readings_dir=override_dir,
        force=False,
    )

    assert plan.readings_dir == override_dir
    assert plan.to_read[0].output_json_path == override_dir / "sample.json"
    assert plan.to_read[0].output_markdown_path == override_dir / "sample.reading.md"
    assert plan.skipped_existing == []


def test_write_topic_ingest_report_json_shape_and_path(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    report = TopicIngestReport(
        topic_id="utility_nav",
        topic_name="Utility Navigation",
        manifest_path="manifest.yaml",
        readings_dir="papers",
        total=2,
        read=["sample"],
        skipped_existing=["old"],
        failed=[],
        artifacts={
            "sample": {
                "json": "papers/sample.json",
                "markdown": "papers/sample.reading.md",
            }
        },
        metadata={"sample": {"year": 2024}},
        update=IngestUpdateReport(
            status="skipped",
            report_path=None,
        ),
    )

    report_path = write_topic_ingest_report(topic_dir, report)

    assert report_path == topic_dir / "state" / "ingest_report.json"
    assert report_path.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(report_path.read_text(encoding="utf-8")) == {
        "artifacts": {
            "sample": {
                "json": "papers/sample.json",
                "markdown": "papers/sample.reading.md",
            }
        },
        "failed": [],
        "manifest_path": "manifest.yaml",
        "metadata": {"sample": {"year": 2024}},
        "read": ["sample"],
        "readings_dir": "papers",
        "skipped_existing": ["old"],
        "topic_id": "utility_nav",
        "topic_name": "Utility Navigation",
        "total": 2,
        "update": {
            "report_path": None,
            "status": "skipped",
        },
    }
    assert IngestUpdateReport(status="failed", error="boom").to_dict() == {
        "status": "failed",
        "report_path": None,
        "error": "boom",
    }


def test_ingest_topic_papers_reads_missing_paper_writes_report_and_preserves_topic(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    topic_before = topic_path.read_text(encoding="utf-8")
    manifest_path = _write_valid_manifest(topic_dir)
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

    assert topic_path.read_text(encoding="utf-8") == topic_before
    assert report.read == ["sample"]
    assert report.skipped_existing == []
    assert report.failed == []
    assert report.artifacts == {
        "sample": {
            "json": str(topic_dir / "papers" / "sample.json"),
            "markdown": str(topic_dir / "papers" / "sample.reading.md"),
        }
    }
    assert report.metadata == {"sample": {"year": 2024}}
    assert report.update.to_dict() == {"status": "skipped", "report_path": None}
    assert len(read_service.calls) == 1
    call = dict(read_service.calls[0])
    topic = call.pop("topic")
    assert call == {
        "paper_id": "sample",
        "title": "Sample Paper",
        "source_path": (topic_dir / "sources" / "sample.txt").resolve(),
        "source_kind": "text_file",
        "source_archive_path": None,
        "output_dir": topic_dir / "papers",
    }
    assert getattr(topic, "topic_id") == "utility_nav"
    report_path = topic_dir / "state" / "ingest_report.json"
    assert json.loads(report_path.read_text(encoding="utf-8")) == report.to_dict()


def test_ingest_topic_papers_skips_existing_and_updates_with_forwarded_options(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    readings_dir = tmp_path / "readings"
    readings_dir.mkdir()
    (readings_dir / "sample.json").write_text("{}", encoding="utf-8")
    read_service = FakeReadService()
    update_service = FakeTopicUpdater()

    report = asyncio.run(
        ingest_topic_papers(
            topic_path=topic_path,
            manifest_path=manifest_path,
            readings_dir=readings_dir,
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
    assert report.failed == []
    assert report.metadata == {"sample": {"year": 2024}}
    assert update_service.calls == [
        {
            "topic_path": topic_path,
            "readings_dir": readings_dir,
            "no_llm_normalize": True,
        }
    ]
    assert report.update.to_dict() == {
        "status": "updated",
        "report_path": str(topic_dir / "state" / "topic_update_report.json"),
    }
    assert json.loads(
        (topic_dir / "state" / "ingest_report.json").read_text(encoding="utf-8")
    ) == report.to_dict()


def test_ingest_topic_papers_forwards_source_archive_to_read_service(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    pdf_path = topic_dir / "pdfs" / "sample.pdf"
    source_archive_path = topic_dir / "sources" / "sample.tar.gz"
    pdf_path.parent.mkdir()
    source_archive_path.parent.mkdir()
    pdf_path.write_bytes(b"%PDF-1.4\n")
    source_archive_path.write_bytes(b"source archive")
    manifest_path = _write_manifest(
        topic_dir,
        """
        papers:
          - paper_id: sample
            title: Sample Paper
            pdf: pdfs/sample.pdf
            source_archive: sources/sample.tar.gz
        """,
    )
    read_service = FakeReadService()

    asyncio.run(
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

    assert read_service.calls[0]["source_archive_path"] == source_archive_path.resolve()


def test_ingest_topic_papers_failed_read_writes_failed_report_and_reraises(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    read_service = FakeReadService(fail_on="sample")

    with pytest.raises(RuntimeError, match="read failed"):
        asyncio.run(
            ingest_topic_papers(
                topic_path=topic_path,
                manifest_path=manifest_path,
                readings_dir=None,
                force=False,
                update=True,
                no_llm_normalize=False,
                read_service=read_service,
                update_service=FakeTopicUpdater(),
            )
        )

    raw_report = json.loads(
        (topic_dir / "state" / "ingest_report.json").read_text(encoding="utf-8")
    )
    assert raw_report["read"] == []
    assert raw_report["failed"] == ["sample"]
    assert raw_report["update"] == {"status": "skipped", "report_path": None}


def test_ingest_topic_papers_failed_update_writes_failed_report_and_reraises(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)

    with pytest.raises(RuntimeError, match="update failed"):
        asyncio.run(
            ingest_topic_papers(
                topic_path=topic_path,
                manifest_path=manifest_path,
                readings_dir=None,
                force=False,
                update=True,
                no_llm_normalize=False,
                read_service=FakeReadService(),
                update_service=FakeTopicUpdater(fail=True),
            )
        )

    raw_report = json.loads(
        (topic_dir / "state" / "ingest_report.json").read_text(encoding="utf-8")
    )
    assert raw_report["read"] == ["sample"]
    assert raw_report["failed"] == []
    assert raw_report["update"] == {
        "status": "failed",
        "report_path": None,
        "error": "update failed",
    }


def test_ingest_topic_papers_system_exit_update_writes_failed_report_and_reraises(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)

    with pytest.raises(SystemExit, match="update exited"):
        asyncio.run(
            ingest_topic_papers(
                topic_path=topic_path,
                manifest_path=manifest_path,
                readings_dir=None,
                force=False,
                update=True,
                no_llm_normalize=False,
                read_service=FakeReadService(),
                update_service=FakeTopicUpdater(system_exit=True),
            )
        )

    raw_report = json.loads(
        (topic_dir / "state" / "ingest_report.json").read_text(encoding="utf-8")
    )
    assert raw_report["read"] == ["sample"]
    assert raw_report["failed"] == []
    assert raw_report["update"] == {
        "status": "failed",
        "report_path": None,
        "error": "update exited",
    }


def test_cmd_topic_ingest_update_rejects_no_experiment_records_before_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.survey import ingest_cli

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    manifest_path = _write_valid_manifest(topic_dir)
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir()
    package = PaperReadingPackage(
        paper_id="sample",
        title="Sample Paper",
        source_path=str(topic_dir / "sources" / "sample.txt"),
    )
    (papers_dir / "sample.json").write_text(
        json.dumps(package.to_dict()),
        encoding="utf-8",
    )

    def fail_if_llm_is_built(*_args, **_kwargs):
        raise AssertionError("LLM should not be built before SOTA preflight")

    monkeypatch.setattr("src.survey.topic_cli._build_llm", fail_if_llm_is_built)
    args = SimpleNamespace(
        config="config.yaml",
        topic=str(topic_path),
        manifest=str(manifest_path),
        readings_dir=None,
        force=False,
        update=True,
        no_llm_normalize=False,
    )

    with pytest.raises(SystemExit, match="No experiment records"):
        asyncio.run(ingest_cli.cmd_topic_ingest(args))

    raw_report = json.loads(
        (topic_dir / "state" / "ingest_report.json").read_text(encoding="utf-8")
    )
    assert raw_report["read"] == []
    assert raw_report["skipped_existing"] == ["sample"]
    assert raw_report["update"]["status"] == "failed"
    assert not (topic_dir / "survey.md").exists()
