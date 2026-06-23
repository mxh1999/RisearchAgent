from __future__ import annotations

from pathlib import Path


def test_parse_tex_source_paper_reports_unavailable_source(tmp_path: Path) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    missing = tmp_path / "missing.tar.gz"

    parsed = parse_tex_source_paper(
        paper_id="2401.00001",
        source_path=missing,
        pdf_path=tmp_path / "paper.pdf",
    )

    assert parsed["paper_id"] == "2401.00001"
    assert parsed["source_type"] == "arxiv_tex"
    assert parsed["parser_name"] == "tex_source_parser"
    assert parsed["availability"] == "unavailable"
    assert parsed["source_archive_path"] == str(missing)
    assert parsed["pdf_path"] == str(tmp_path / "paper.pdf")
    assert parsed["sections"] == []
    assert parsed["tables"] == []
    assert parsed["equations"] == []
    assert parsed["figures"] == []
    assert parsed["citations"] == []
    assert parsed["bibliography"] == []
    assert parsed["metrics"]["section_count"] == 0
    assert any("Source path unavailable" in warning for warning in parsed["warnings"])


def test_parse_tex_source_paper_reports_no_tex_entrypoint(tmp_path: Path) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "README.txt").write_text("not TeX", encoding="utf-8")

    parsed = parse_tex_source_paper(
        paper_id="2401.00002",
        source_path=source_dir,
    )

    assert parsed["availability"] == "no_tex_entrypoint"
    assert parsed["main_tex_file"] == ""
    assert parsed["metrics"]["parse_warning_count"] >= 1
    assert any("No TeX entrypoint" in warning for warning in parsed["warnings"])
