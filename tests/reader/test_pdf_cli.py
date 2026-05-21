from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from run import build_parser
from src.reader.pdf_cli import render_extracted_pages, write_pdf_extraction
from src.reader.staged_models import PageText


def test_pdf_extract_parser_accepts_output_and_max_pages() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "pdf",
            "extract",
            "--pdf",
            "data/papers/sample.pdf",
            "--output",
            "sample.md",
            "--max-pages",
            "3",
        ]
    )

    assert args.command == "pdf"
    assert args.pdf_command == "extract"
    assert args.pdf == "data/papers/sample.pdf"
    assert args.output == "sample.md"
    assert args.max_pages == 3


def test_render_extracted_pages_adds_stable_page_markers() -> None:
    markdown = render_extracted_pages(
        [
            PageText(page=1, text="Intro text", char_start=0, char_end=10),
            PageText(page=2, text="| Method | SPL |", char_start=11, char_end=27),
        ]
    )

    assert markdown == "[Page 1]\nIntro text\n\n[Page 2]\n| Method | SPL |\n"


def test_write_pdf_extraction_writes_normalized_pages(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "paper.md"

    monkeypatch.setattr(
        "src.reader.pdf_cli.extract_pages_from_pdf",
        lambda path, max_pages=None: [
            PageText(page=1, text="efficient text", char_start=0, char_end=14)
        ],
    )

    result = write_pdf_extraction(
        SimpleNamespace(
            pdf=str(tmp_path / "paper.pdf"),
            output=str(output),
            max_pages=1,
        )
    )

    assert result == output
    assert output.read_text(encoding="utf-8") == "[Page 1]\nefficient text\n"
