from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from src.reader.staged_models import PageText


def test_build_parsed_pdf_paper_outputs_section_first_schema() -> None:
    from src.source_benchmark.pdf_parser import build_parsed_pdf_paper

    pages = [
        PageText(
            page=1,
            char_start=0,
            char_end=320,
            text=(
                "# Sample Paper Title\n\n"
                "Abstract\n"
                "We report 93.2 accuracy on ImageNet and 77.5 mAP on COCO.\n\n"
                "1 Introduction\n"
                "This paper studies a source extraction benchmark.\n\n"
                "2 Method\n"
                "Our parser keeps section-local evidence chunks.\n\n"
                "3 Experiments\n"
                "Table 1: Main accuracy results on ImageNet.\n"
                "| Method | Acc |\n"
                "| --- | ---: |\n"
                "| Ours | 93.2 |\n\n"
                "Figure 1: System overview.\n"
                "The result improves SPL by 5.1 points.\n\n"
                "References\n"
                "[1] Prior work.\n"
            ),
        )
    ]

    parsed = build_parsed_pdf_paper(
        paper_id="2312.03275",
        source_path=Path("paper.pdf"),
        pages=pages,
    )

    assert parsed["paper_id"] == "2312.03275"
    assert parsed["source_type"] == "pdf"
    assert parsed["availability"] == "available"
    assert parsed["title"] == "Sample Paper Title"
    assert parsed["text_chars"] > 0

    section_types = [section["normalized_type"] for section in parsed["sections"]]
    assert section_types == [
        "abstract",
        "introduction",
        "method",
        "experiments",
        "references",
    ]
    assert parsed["metrics"]["section_count"] == 5
    assert parsed["metrics"]["table_count"] == 1
    assert parsed["metrics"]["figure_caption_count"] == 1
    assert parsed["references_count"] == 1
    assert parsed["metrics"]["candidate_numeric_result_count"] >= 3

    section_ids = {section["section_id"] for section in parsed["sections"]}
    assert parsed["chunks"]
    assert all(chunk["section_id"] in section_ids for chunk in parsed["chunks"])
    assert all(chunk["text"] for chunk in parsed["chunks"])
    assert all(chunk["text_preview"] for chunk in parsed["chunks"])
    assert parsed["chunks"][0]["heading_path"] == ["Abstract"]

    assert parsed["tables"][0]["caption"] == "Table 1: Main accuracy results on ImageNet."
    assert parsed["tables"][0]["numeric_cell_count"] == 1
    assert parsed["figures"][0]["caption"] == "Figure 1: System overview."
    assert "formulas" in parsed


def test_build_parsed_pdf_paper_uses_fallback_section_when_headings_missing() -> None:
    from src.source_benchmark.pdf_parser import build_parsed_pdf_paper

    parsed = build_parsed_pdf_paper(
        paper_id="2401.00001",
        source_path=Path("paper.pdf"),
        pages=[
            PageText(
                page=1,
                char_start=0,
                char_end=42,
                text="Unstructured extracted text with 88.0 accuracy.",
            )
        ],
    )

    assert parsed["availability"] == "available"
    assert len(parsed["sections"]) == 1
    assert parsed["sections"][0]["section_id"] == "sec-0001"
    assert parsed["sections"][0]["normalized_type"] == "other"
    assert parsed["chunks"][0]["section_id"] == "sec-0001"
    assert any("Section detection failed" in warning for warning in parsed["warnings"])


def test_build_parsed_pdf_paper_skips_link_noise_when_extracting_title() -> None:
    from src.source_benchmark.pdf_parser import build_parsed_pdf_paper

    text = (
        "_https://example.org/project_\n\n"
        "_2023-8-1_\n\n"
        "**==> picture [100 x 16] intentionally omitted <==**\n\n"
        "## **RT-2: Vision-Language-Action Models Transfer Web Knowledge**\n\n"
        "**Author One, Author Two**\n\n"
        "## **1. Introduction**\n"
        "Robotic control text.\n"
    )

    parsed = build_parsed_pdf_paper(
        paper_id="2307.15818",
        source_path=Path("paper.pdf"),
        pages=[PageText(page=1, text=text, char_start=0, char_end=len(text))],
    )

    assert parsed["title"] == (
        "RT-2: Vision-Language-Action Models Transfer Web Knowledge"
    )
    assert parsed["sections"][0]["title"] == "Introduction"
    assert parsed["sections"][0]["normalized_type"] == "introduction"


def test_build_parsed_pdf_paper_extracts_inline_and_display_formulas() -> None:
    from src.source_benchmark.pdf_parser import build_parsed_pdf_paper

    text = (
        "1 Method\n"
        "Given an observation x_t, we compute y = W x_t + b before decoding.\n\n"
        "E = -\\sum_i p_i \\log p_i   (1)\n\n"
        "The policy \u03c0(a|s) is then optimized with reward r_t.\n"
    )

    parsed = build_parsed_pdf_paper(
        paper_id="2401.00004",
        source_path=Path("paper.pdf"),
        pages=[PageText(page=1, text=text, char_start=0, char_end=len(text))],
    )

    formulas = parsed["formulas"]
    assert [formula["kind"] for formula in formulas] == ["inline", "display", "inline"]
    assert formulas[0]["section_id"] == "sec-0001"
    assert formulas[0]["text"] == "y = W x_t + b"
    assert formulas[1]["text"] == "E = -\\sum_i p_i \\log p_i"
    assert formulas[1]["label"] == "1"
    assert formulas[2]["text"] == "\u03c0(a|s)"
    assert parsed["metrics"]["formula_count"] == 3
    assert parsed["metrics"]["display_formula_count"] == 1
    assert parsed["metrics"]["inline_formula_count"] == 2


def test_build_parsed_pdf_paper_does_not_treat_picture_placeholders_as_formulas() -> None:
    from src.source_benchmark.pdf_parser import build_parsed_pdf_paper

    text = (
        "1 Method\n"
        "**==> picture [467 x 173] intentionally omitted <==**\n\n"
        "We keep placeholder text in the section for provenance.\n"
    )

    parsed = build_parsed_pdf_paper(
        paper_id="2401.00008",
        source_path=Path("paper.pdf"),
        pages=[PageText(page=1, text=text, char_start=0, char_end=len(text))],
    )

    assert parsed["formulas"] == []
    assert parsed["metrics"]["formula_count"] == 0


def test_build_parsed_pdf_paper_extracts_multiline_caption_markdown_table() -> None:
    from src.source_benchmark.pdf_parser import build_parsed_pdf_paper

    text = (
        "3 Experiments\n"
        "Table 2\n"
        "Main results on HM3D and MP3D.\n"
        "| Method | HM3D SPL | MP3D SPL |\n"
        "| --- | ---: | ---: |\n"
        "| Ours | 36.4 | 17.5 |\n"
        "| Base | 30.1 | 14.2 |\n"
    )

    parsed = build_parsed_pdf_paper(
        paper_id="2401.00005",
        source_path=Path("paper.pdf"),
        pages=[PageText(page=1, text=text, char_start=0, char_end=len(text))],
    )

    table = parsed["tables"][0]
    assert table["caption"] == "Table 2: Main results on HM3D and MP3D."
    assert table["markdown"].startswith("| Method | HM3D SPL | MP3D SPL |")
    assert table["numeric_cell_count"] == 4
    assert table["extraction_method"] == "markdown_caption"


def test_parse_pdf_paper_uses_pymupdf_table_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    import src.source_benchmark.pdf_parser as pdf_parser

    class FakeTable:
        bbox = (10.0, 20.0, 200.0, 120.0)

        def extract(self):
            return [
                ["Method", "SPL", "SR"],
                ["Ours", "36.4", "52.6"],
                ["Base", "30.1", "48.0"],
            ]

    class FakeTables:
        tables = [FakeTable()]

    class FakePage:
        def find_tables(self):
            return FakeTables()

    class FakeDoc:
        def __iter__(self):
            return iter([FakePage()])

        def __getitem__(self, index):
            return [FakePage()][index]

        def __len__(self):
            return 1

        def close(self) -> None:
            pass

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pdf_parser,
        "extract_pages_from_pdf",
        lambda path, max_pages=None: [
            PageText(
                page=1,
                char_start=0,
                char_end=50,
                text="3 Experiments\nTable 3: Navigation results.\nNearby text.",
            )
        ],
    )
    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda path: FakeDoc()))

    parsed = pdf_parser.parse_pdf_paper(
        paper_id="2401.00006",
        output_dir=tmp_path,
        pdf_path=pdf_path,
    )

    assert len(parsed["tables"]) == 1
    table = parsed["tables"][0]
    assert table["caption"] == "Table 3: Navigation results."
    assert table["markdown"] == (
        "| Method | SPL | SR |\n"
        "| --- | --- | --- |\n"
        "| Ours | 36.4 | 52.6 |\n"
        "| Base | 30.1 | 48.0 |"
    )
    assert table["numeric_cell_count"] == 4
    assert table["extraction_method"] == "pymupdf_find_tables"


def test_parse_pdf_paper_limits_pymupdf_table_fallback_pages(
    tmp_path: Path, monkeypatch
) -> None:
    import src.source_benchmark.pdf_parser as pdf_parser

    class FakeTable:
        bbox = (0.0, 0.0, 1.0, 1.0)

        def __init__(self, value: str) -> None:
            self.value = value

        def extract(self):
            return [["Method", "SPL"], ["Ours", self.value]]

    class FakeTables:
        def __init__(self, value: str) -> None:
            self.tables = [FakeTable(value)]

    class FakePage:
        def __init__(self, value: str) -> None:
            self.value = value

        def find_tables(self):
            return FakeTables(self.value)

    class FakeDoc:
        def __iter__(self):
            return iter([FakePage("10.0"), FakePage("20.0")])

        def close(self) -> None:
            pass

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pdf_parser,
        "extract_pages_from_pdf",
        lambda path, max_pages=None: [
            PageText(
                page=1,
                char_start=0,
                char_end=50,
                text="3 Experiments\nTable 1: First page results.\nNearby text.",
            )
        ],
    )
    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda path: FakeDoc()))

    parsed = pdf_parser.parse_pdf_paper(
        paper_id="2401.00007",
        output_dir=tmp_path,
        pdf_path=pdf_path,
        max_pages=1,
    )

    assert len(parsed["tables"]) == 1
    assert "10.0" in parsed["tables"][0]["markdown"]
    assert "20.0" not in parsed["tables"][0]["markdown"]


def test_parse_pdf_paper_reuses_cached_pdf_without_downloading(
    tmp_path: Path, monkeypatch
) -> None:
    from src.source_benchmark import pdf_parser

    cached_pdf = tmp_path / "sources" / "2401.00009.pdf"
    cached_pdf.parent.mkdir()
    cached_pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pdf_parser,
        "extract_pages_from_pdf",
        lambda path, max_pages=None: [
            PageText(page=1, char_start=0, char_end=19, text="Abstract\nCached text.")
        ],
    )

    def fail_if_downloaded(url: str, target_path: Path) -> None:
        raise AssertionError("cached PDF should not be downloaded again")

    parsed = pdf_parser.parse_pdf_paper(
        paper_id="2401.00009",
        output_dir=tmp_path,
        download_pdf=fail_if_downloaded,
    )

    assert parsed["availability"] == "available"
    assert parsed["source_path"] == str(cached_pdf)


def test_parse_pdf_paper_records_download_failure(tmp_path: Path) -> None:
    from src.source_benchmark.pdf_parser import parse_pdf_paper

    def failing_download(url: str, target_path: Path) -> None:
        raise RuntimeError(f"blocked: {url}")

    parsed = parse_pdf_paper(
        paper_id="2401.00002",
        output_dir=tmp_path,
        download_pdf=failing_download,
    )

    assert parsed["availability"] == "failed"
    assert parsed["source_type"] == "pdf"
    assert parsed["source_path"].endswith("2401.00002.pdf")
    assert parsed["sections"] == []
    assert parsed["chunks"] == []
    assert any("Download failed" in warning for warning in parsed["warnings"])


def test_write_parsed_pdf_paper_writes_json(tmp_path: Path, monkeypatch) -> None:
    import src.source_benchmark.pdf_parser as pdf_parser

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        pdf_parser,
        "extract_pages_from_pdf",
        lambda path, max_pages=None: [
            PageText(
                page=1,
                char_start=0,
                char_end=44,
                text="Abstract\nShort text.\n\n1 Introduction\nIntro.",
            )
        ],
    )

    output_path = pdf_parser.write_parsed_pdf_paper(
        paper_id="2401.00003",
        output_dir=tmp_path / "parsed",
        pdf_path=pdf_path,
    )

    raw = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path.name == "2401.00003.pdf.parsed.json"
    assert raw["paper_id"] == "2401.00003"
    assert raw["source_type"] == "pdf"
    assert raw["chunks"]
