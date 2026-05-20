from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from src.survey.topic_ingest import (
    IngestUpdateReport,
    TopicIngestReport,
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
    assert manifest.papers[1].title == "Sample Text"
    assert manifest.papers[1].source_kind == "text_file"
    assert manifest.papers[1].source_path == text_path.resolve()
    assert manifest.papers[1].metadata == {}


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
