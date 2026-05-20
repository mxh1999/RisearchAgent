from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from run import build_parser
from src.reader import staged_cli
from src.reader.staged_models import PaperReadingPackage


class FakeStagedReader:
    def __init__(self) -> None:
        self.calls = []

    async def read(
        self,
        *,
        paper_id,
        title,
        source_path,
        pages,
        topic,
    ) -> PaperReadingPackage:
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


def test_read_staged_text_file_args() -> None:
    args = build_parser().parse_args(
        [
            "read",
            "--staged",
            "--text-file",
            "paper.txt",
            "--paper-id",
            "sample",
            "--title",
            "Sample Paper",
            "--output-root",
            "data/readings-test",
        ]
    )

    assert args.command == "read"
    assert args.staged is True
    assert args.text_file == "paper.txt"
    assert args.paper_id == "sample"
    assert args.title == "Sample Paper"


def test_read_staged_rejects_missing_source() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            ["read", "--staged", "--paper-id", "sample", "--title", "Sample Paper"]
        )

    assert exc_info.value.code == 2


def test_non_staged_read_rejects_staged_only_flags() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["read", "2401.00001", "--text-file", "paper.txt"])

    assert exc_info.value.code == 2


def test_read_staged_rejects_arxiv_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            [
                "read",
                "2401.00001",
                "--staged",
                "--text-file",
                "paper.txt",
                "--paper-id",
                "sample",
                "--title",
                "Sample Paper",
            ]
        )

    assert exc_info.value.code == 2


def test_read_staged_rejects_unsafe_paper_id_before_extraction(monkeypatch) -> None:
    extraction_called = False

    def fail_if_called(_path):
        nonlocal extraction_called
        extraction_called = True
        raise AssertionError("source extraction should not be called")

    monkeypatch.setattr(staged_cli, "extract_pages_from_text_file", fail_if_called)
    args = SimpleNamespace(
        config="config.yaml",
        pdf=None,
        text_file="paper.txt",
        paper_id="../escape",
        title="Sample Paper",
        topic=None,
        output_root=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(staged_cli.cmd_read_staged(args))

    assert "Unsafe paper_id" in str(exc_info.value)
    assert extraction_called is False


def test_read_staged_source_reads_text_file_and_writes_package(tmp_path) -> None:
    source_path = tmp_path / "paper.txt"
    source_path.write_text("Abstract\nMethod", encoding="utf-8")
    output_dir = tmp_path / "out"
    reader = FakeStagedReader()

    json_path, markdown_path = asyncio.run(
        staged_cli.read_staged_source(
            reader=reader,
            paper_id="sample",
            title="Sample Paper",
            source_path=source_path,
            source_kind="text_file",
            output_dir=output_dir,
            topic=None,
        )
    )

    assert json_path == output_dir / "sample.json"
    assert markdown_path == output_dir / "sample.reading.md"
    assert json_path.exists()
    assert markdown_path.exists()
    assert len(reader.calls) == 1
    assert reader.calls[0]["paper_id"] == "sample"
    assert reader.calls[0]["title"] == "Sample Paper"
    assert reader.calls[0]["source_path"] == str(source_path)
    assert reader.calls[0]["topic"] is None
    assert len(reader.calls[0]["pages"]) == 1
    assert reader.calls[0]["pages"][0].text == "Abstract\nMethod"


def test_load_topic_rejects_missing_yaml(tmp_path) -> None:
    topic_path = tmp_path / "missing.yaml"

    with pytest.raises(SystemExit) as exc_info:
        staged_cli._load_topic(topic_path)

    message = str(exc_info.value)
    assert str(topic_path) in message
    assert "not found" in message


def test_load_topic_rejects_malformed_yaml(tmp_path) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: [", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        staged_cli._load_topic(topic_path)

    message = str(exc_info.value)
    assert str(topic_path) in message
    assert "invalid YAML" in message


def test_load_topic_rejects_empty_yaml(tmp_path) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        staged_cli._load_topic(topic_path)

    message = str(exc_info.value)
    assert str(topic_path) in message
    assert "empty" in message


def test_load_topic_rejects_malformed_profile_fields(tmp_path) -> None:
    topic_path = tmp_path / "topic.yaml"
    topic_path.write_text("topic_id: sample\nname: Sample\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        staged_cli._load_topic(topic_path)

    message = str(exc_info.value)
    assert str(topic_path) in message
    assert "malformed TopicProfile" in message
