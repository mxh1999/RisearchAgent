from __future__ import annotations

import gzip
import tarfile
import textwrap
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


def test_parse_tex_source_paper_accepts_plain_tex_file(tmp_path: Path) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    tex_path = tmp_path / "paper.tex"
    tex_path.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Plain Paper}
            \begin{document}
            \maketitle
            \section{Introduction}
            Hello.
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    parsed = parse_tex_source_paper(paper_id="2401.00003", source_path=tex_path)

    assert parsed["availability"] == "available"
    assert parsed["main_tex_file"].endswith("paper.tex")
    assert parsed["title"] == "Plain Paper"
    assert parsed["metrics"]["section_count"] == 1


def test_parse_tex_source_paper_accepts_tar_gz_archive(tmp_path: Path) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Archive Paper}
            \begin{document}
            \section{Method}
            Text.
            \end{document}
            """
        ),
        encoding="utf-8",
    )
    archive_path = tmp_path / "source.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source_dir, arcname="paper")

    parsed = parse_tex_source_paper(paper_id="2401.00004", source_path=archive_path)

    assert parsed["availability"] == "available"
    assert parsed["main_tex_file"].endswith("main.tex")
    assert parsed["title"] == "Archive Paper"
    assert parsed["metrics"]["section_count"] == 1


def test_parse_tex_source_paper_accepts_single_gzip_tex(tmp_path: Path) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    raw = textwrap.dedent(
        r"""
        \documentclass{article}
        \title{Gzip Paper}
        \begin{document}
        \section{Results}
        Text.
        \end{document}
        """
    ).encode("utf-8")
    source_path = tmp_path / "paper.gz"
    source_path.write_bytes(gzip.compress(raw))

    parsed = parse_tex_source_paper(paper_id="2401.00005", source_path=source_path)

    assert parsed["availability"] == "available"
    assert parsed["main_tex_file"].endswith(".tex")
    assert parsed["title"] == "Gzip Paper"
    assert parsed["metrics"]["section_count"] == 1


def test_parse_tex_source_paper_resolves_inputs_with_source_provenance(
    tmp_path: Path,
) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Multi File Paper}
            \begin{document}
            \input{sections/intro}
            \include{sections/method}
            \end{document}
            """
        ),
        encoding="utf-8",
    )
    sections = source_dir / "sections"
    sections.mkdir()
    (sections / "intro.tex").write_text(
        r"\section{Introduction}" + "\nIntro text.\n",
        encoding="utf-8",
    )
    (sections / "method.tex").write_text(
        r"\section{Method}" + "\nMethod text.\n",
        encoding="utf-8",
    )

    parsed = parse_tex_source_paper(paper_id="2401.00006", source_path=source_dir)

    assert parsed["availability"] == "available"
    assert [section["title"] for section in parsed["sections"]] == [
        "Introduction",
        "Method",
    ]
    assert parsed["sections"][0]["source_file"].endswith("sections/intro.tex")
    assert parsed["sections"][1]["source_file"].endswith("sections/method.tex")
    assert parsed["metrics"]["unresolved_input_count"] == 0


def test_parse_tex_source_paper_preserves_unresolved_inputs(tmp_path: Path) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \begin{document}
            \input{missing/intro}
            \section{Fallback}
            Text.
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    parsed = parse_tex_source_paper(paper_id="2401.00007", source_path=source_dir)

    assert parsed["availability"] == "available"
    assert parsed["metrics"]["unresolved_input_count"] == 1
    assert any("Unresolved input" in warning for warning in parsed["warnings"])
    assert r"\input{missing/intro}" in parsed["sections"][0]["latex_source"]
