from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.survey.topic_ingest import load_ingest_manifest


def _write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


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
