from __future__ import annotations

import tarfile
import textwrap
from pathlib import Path

from src.reader.latex_source_extractor import extract_tables_from_latex_source


def test_extract_tables_from_latex_source_resolves_inputs_and_markdown(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(
        textwrap.dedent(
            r"""
            \documentclass{article}
            \begin{document}
            \section{Experiments}
            \input{tables/results}
            \end{document}
            """
        ),
        encoding="utf-8",
    )
    table_dir = source_dir / "tables"
    table_dir.mkdir()
    (table_dir / "results.tex").write_text(
        textwrap.dedent(
            r"""
            \begin{table*}
            \caption{ObjectNav results on HM3D and MP3D.}
            \label{tab:objectnav}
            \begin{tabular}{lcccc}
            \toprule
            Method & \multicolumn{2}{c}{HM3D} & \multicolumn{2}{c}{MP3D} \\
            & SR & SPL & SR & SPL \\
            VLFM & 52.60 & 30.40 & 36.40 & 17.50 \\
            Ours & 53.50 & 27.31 & 35.63 & 16.52 \\
            \bottomrule
            \end{tabular}
            \end{table*}
            """
        ),
        encoding="utf-8",
    )
    archive_path = tmp_path / "paper-source.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source_dir, arcname="paper")

    tables = extract_tables_from_latex_source(archive_path)

    assert len(tables) == 1
    table = tables[0]
    assert table.table_id == "table-1"
    assert table.caption == "ObjectNav results on HM3D and MP3D."
    assert table.label == "tab:objectnav"
    assert table.section == "Experiments"
    assert "multicolumn" in table.latex
    assert "| Method | HM3D | MP3D |" in table.markdown
    assert "| VLFM | 52.60 | 30.40 | 36.40 | 17.50 |" in table.markdown
