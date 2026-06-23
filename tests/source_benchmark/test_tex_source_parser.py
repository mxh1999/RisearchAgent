from __future__ import annotations

import gzip
import os
import subprocess
import sys
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


def test_parse_tex_source_paper_extracts_tables_figures_and_equations(
    tmp_path: Path,
) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    tex_path = tmp_path / "paper.tex"
    tex_path.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Objects Paper}
            \begin{document}
            \section{Experiments}\label{sec:experiments}
            Text before objects.
            \begin{table}[t]
            \resizebox{\columnwidth}{!}{
            \begin{tabular}{lc}
            Method & Acc \\
            Ours & 99.0 \\
            \end{tabular}
            }
            \caption{Main results.}
            \label{tab:main}
            \end{table}
            \begin{equation}
            L = -\sum_i y_i \log p_i
            \label{eq:loss}
            \end{equation}
            \begin{figure}
            \includegraphics[width=\linewidth]{figures/overview.pdf}
            \caption{Overview figure.}
            \label{fig:overview}
            \end{figure}
            Text after objects.
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    parsed = parse_tex_source_paper(paper_id="2401.00008", source_path=tex_path)

    assert parsed["availability"] == "available"
    assert parsed["metrics"]["table_count"] == 1
    assert parsed["metrics"]["equation_count"] == 1
    assert parsed["metrics"]["figure_count"] == 1
    table = parsed["tables"][0]
    assert table["table_id"] == "tab:main"
    assert table["caption"] == "Main results."
    assert table["label"] == "tab:main"
    assert table["section_id"] == "sec:experiments"
    assert r"\begin{table}" in table["latex_source"]
    assert "has_resizebox" in table["quality_flags"]
    assert "has_math" not in table["quality_flags"]
    equation = parsed["equations"][0]
    assert equation["equation_id"] == "eq:loss"
    assert equation["label"] == "eq:loss"
    assert equation["section_id"] == "sec:experiments"
    figure = parsed["figures"][0]
    assert figure["figure_id"] == "fig:overview"
    assert figure["graphics_paths"] == ["figures/overview.pdf"]
    section_text = parsed["sections"][0]["plain_text"]
    assert "Text before objects." in section_text
    assert "Text after objects." in section_text
    assert "Method & Acc" not in section_text
    assert "L = -" not in section_text


def test_parse_tex_source_paper_extracts_section_tree_abstract_citations_and_bbl(
    tmp_path: Path,
) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Knowledge Paper}
            \begin{document}
            \begin{abstract}
            We cite prior work \citep{vaswani2017attention}.
            \end{abstract}
            \section{Method}\label{sec:method}
            See \ref{tab:main}.
            \subsection{Model}\label{sec:model}
            Model text.
            \appendix
            \section{More Results}\label{sec:appendix}
            Appendix text.
            \bibliography{main}
            \end{document}
            """
        ),
        encoding="utf-8",
    )
    (source_dir / "main.bbl").write_text(
        textwrap.dedent(
            r"""
            \begin{thebibliography}{1}
            \bibitem{vaswani2017attention}
            Ashish Vaswani et al. Attention is all you need.
            \end{thebibliography}
            """
        ),
        encoding="utf-8",
    )

    parsed = parse_tex_source_paper(paper_id="2401.00009", source_path=source_dir)

    assert parsed["title"] == "Knowledge Paper"
    assert parsed["abstract"] == "We cite prior work \\citep{vaswani2017attention}."
    assert [section["section_id"] for section in parsed["sections"]] == [
        "sec:method",
        "sec:model",
        "sec:appendix",
    ]
    assert parsed["sections"][1]["parent_id"] == "sec:method"
    assert parsed["sections"][1]["heading_path"] == ["Method", "Model"]
    assert parsed["sections"][2]["normalized_type"] == "appendix"
    assert parsed["citations"] == [
        {"key": "vaswani2017attention", "command": "citep", "section_id": ""}
    ]
    assert parsed["bibliography"][0]["key"] == "vaswani2017attention"
    assert "Attention is all you need" in parsed["bibliography"][0]["raw_text"]
    assert parsed["metrics"]["citation_count"] == 1
    assert parsed["metrics"]["bibliography_entry_count"] == 1


def test_parse_tex_source_paper_flags_orphan_tabular_and_missing_metadata(
    tmp_path: Path,
) -> None:
    from src.source_benchmark.tex_source_parser import parse_tex_source_paper

    tex_path = tmp_path / "paper.tex"
    tex_path.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \begin{document}
            \section{Results}
            \begin{tabular}{lc}
            Method & Score \\
            Ours & $99.0$ \\
            \end{tabular}
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    parsed = parse_tex_source_paper(paper_id="2401.00010", source_path=tex_path)

    table = parsed["tables"][0]
    assert "orphan_tabular" in table["quality_flags"]
    assert "caption_missing" in table["quality_flags"]
    assert "label_missing" in table["quality_flags"]
    assert "has_math" in table["quality_flags"]
    assert parsed["metrics"]["missing_caption_table_count"] == 1
    assert parsed["metrics"]["missing_label_table_count"] == 1


def test_write_parsed_tex_source_paper_writes_json(tmp_path: Path) -> None:
    import json
    from src.source_benchmark.tex_source_parser import write_parsed_tex_source_paper

    tex_path = tmp_path / "paper.tex"
    tex_path.write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{Writable}
            \begin{document}
            \section{Intro}
            Text.
            \end{document}
            """
        ),
        encoding="utf-8",
    )

    output_path = write_parsed_tex_source_paper(
        paper_id="2401.00011",
        source_path=tex_path,
        output_dir=tmp_path / "parsed",
    )

    raw = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path.name == "2401.00011.tex.parsed.json"
    assert raw["paper_id"] == "2401.00011"
    assert raw["source_type"] == "arxiv_tex"
    assert raw["title"] == "Writable"


def test_tex_source_parser_module_cli_accepts_extensionless_tar(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \title{CLI Paper}
            \begin{document}
            \section{Intro}
            Text.
            \end{document}
            """
        ),
        encoding="utf-8",
    )
    source_archive = tmp_path / "source.eprint"
    with tarfile.open(source_archive, "w") as archive:
        archive.add(source_dir, arcname="paper")
    output_dir = tmp_path / "parsed"
    env = os.environ.copy()
    env["PYTHONPATH"] = "."

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.source_benchmark.tex_source_parser",
            "--paper-id",
            "2401.00012",
            "--source",
            str(source_archive),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    output_path = output_dir / "2401.00012.tex.parsed.json"
    assert output_path.exists()
    import json

    raw = json.loads(output_path.read_text(encoding="utf-8"))
    assert raw["availability"] == "available"
    assert raw["metrics"]["section_count"] == 1
