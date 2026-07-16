# TeX Source Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone local TeX source parser that emits section-first `arxiv_tex` JSON evidence without downloading sources, parsing PDFs, calling LLMs, or normalizing tables into grids.

**Architecture:** Add a focused parser module under `src/source_benchmark/tex_source_parser.py` and tests under `tests/source_benchmark/test_tex_source_parser.py`. The implementation uses static archive materialization, main-file detection, include expansion with provenance segments, balanced-brace scanning, and first-class table/equation/figure extraction.

**Tech Stack:** Python 3.11 in this repo, standard library only for the parser, `pytest` for tests, no network-dependent tests.

---

## File Structure

- Create `src/source_benchmark/tex_source_parser.py`: parser public API, archive materialization, source flattening, TeX scanning, schema building, and CLI entrypoint.
- Create `tests/source_benchmark/test_tex_source_parser.py`: synthetic unit and smoke tests for single-file, multi-file, archive, missing metadata, unresolved includes, and bibliography behavior.
- Modify `src/source_benchmark/__init__.py` only if an export is needed. Prefer no change unless tests reveal import friction.

## Task 1: Public API Skeleton And Failure Schema

**Files:**
- Create: `src/source_benchmark/tex_source_parser.py`
- Test: `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Write failing tests for missing source and no TeX entrypoint**

Create `tests/source_benchmark/test_tex_source_parser.py` with:

```python
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.source_benchmark.tex_source_parser'`.

- [ ] **Step 3: Implement minimal public API and empty paper schema**

Create `src/source_benchmark/tex_source_parser.py` with constants:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PARSER_NAME = "tex_source_parser"
PARSER_VERSION = "0.1.0"
SOURCE_TYPE = "arxiv_tex"


def parse_tex_source_paper(
    *,
    paper_id: str,
    source_path: Path,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    source_path = Path(source_path)
    warnings: list[str] = []
    if not source_path.exists():
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            pdf_path=pdf_path,
            availability="unavailable",
            warnings=[f"Source path unavailable: {source_path}"],
        )
    tex_files = list(source_path.rglob("*.tex")) if source_path.is_dir() else []
    if not tex_files and source_path.suffix.lower() != ".tex":
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            pdf_path=pdf_path,
            availability="no_tex_entrypoint",
            warnings=[f"No TeX entrypoint found under: {source_path}"],
        )
    warnings.append("Parser skeleton does not extract TeX content yet.")
    return _empty_parsed_paper(
        paper_id=paper_id,
        source_path=source_path,
        pdf_path=pdf_path,
        availability="parse_failed",
        warnings=warnings,
    )
```

Add `_empty_parsed_paper(...)` returning all required top-level fields:

```python
def _empty_parsed_paper(
    *,
    paper_id: str,
    source_path: Path,
    pdf_path: Path | None,
    availability: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "source_type": SOURCE_TYPE,
        "availability": availability,
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "source_archive_path": str(source_path),
        "source_root": str(source_path if source_path.is_dir() else source_path.parent),
        "main_tex_file": "",
        "pdf_path": str(pdf_path) if pdf_path is not None else "",
        "title": "",
        "abstract": "",
        "sections": [],
        "tables": [],
        "equations": [],
        "figures": [],
        "citations": [],
        "bibliography": [],
        "warnings": warnings,
        "metrics": _metrics(
            section_count=0,
            table_count=0,
            equation_count=0,
            figure_count=0,
            citation_count=0,
            bibliography_entry_count=0,
            unresolved_input_count=0,
            partial_environment_count=0,
            missing_caption_table_count=0,
            missing_label_table_count=0,
            parse_warning_count=len(warnings),
        ),
    }
```

Add `_metrics(...)` with the exact keys required in the design.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS for the two initial tests.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "✨ feat: add tex source parser schema skeleton"
```

## Task 2: Materialization And Main TeX Detection

**Files:**
- Modify: `src/source_benchmark/tex_source_parser.py`
- Test: `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Write failing tests for plain TeX and archive input**

Append tests:

```python
import gzip
import tarfile
import textwrap


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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: FAIL because archive/gzip materialization and section extraction are not implemented.

- [ ] **Step 3: Implement materialization, main detection, title, and minimal sections**

Add imports: `gzip`, `io`, `re`, `tarfile`, `tempfile`, `zipfile`, `dataclasses`.

Implement:

- `_materialize_source(source_path: Path, target_dir: Path) -> tuple[Path, str]`
- `_safe_extract_tar(...)`
- `_safe_destination(...)`
- `_choose_main_tex(root: Path, warnings: list[str]) -> Path | None`
- `_read_text(path: Path) -> str`
- `_extract_title(text: str) -> str`
- `_extract_sections_minimal(text: str, main_file: Path) -> list[dict[str, Any]]`

Minimal section extraction should detect `\section{...}` only for this task and return section objects with:

```python
{
    "section_id": "sec-0001",
    "title": "Introduction",
    "level": 1,
    "normalized_type": "introduction",
    "parent_id": None,
    "order": 0,
    "heading_path": ["Introduction"],
    "latex_source": "...",
    "plain_text": "...",
    "source_file": "paper.tex",
    "line_start": 5,
    "line_end": 7,
}
```

Update `parse_tex_source_paper(...)` to use `TemporaryDirectory` for archive inputs and return available JSON when a main file is found.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS for Task 1 and Task 2 tests.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "✨ feat: parse local tex source inputs"
```

## Task 3: Include Expansion With Provenance

**Files:**
- Modify: `src/source_benchmark/tex_source_parser.py`
- Test: `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Write failing tests for multi-file include and unresolved include**

Append:

```python
def test_parse_tex_source_paper_resolves_inputs_with_source_provenance(tmp_path: Path) -> None:
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: FAIL because includes are not expanded with segment provenance.

- [ ] **Step 3: Implement `FlattenedSource` and recursive include expansion**

Add dataclasses:

```python
@dataclass(frozen=True)
class SourceSegment:
    source_file: Path
    flat_start: int
    flat_end: int
    line_offset: int


@dataclass(frozen=True)
class FlattenedSource:
    text: str
    segments: list[SourceSegment]
    unresolved_input_count: int
```

Implement `_strip_comments_preserve_lines`, `_flatten_tex_file`, `_resolve_input_path`, `_line_number_for_position`, and `_provenance_for_span`.

Expansion rules:

- Search `\input{...}` and `\include{...}` after comment stripping.
- Try `name.tex` first when no suffix exists, then bare `name`.
- Resolve relative to current file.
- Preserve unresolved include command in flattened text.
- Skip recursive cycles and record warnings.

Update section provenance to use `_provenance_for_span`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS through include tests.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "✨ feat: expand tex inputs with provenance"
```

## Task 4: First-Class Tables, Figures, And Equations

**Files:**
- Modify: `src/source_benchmark/tex_source_parser.py`
- Test: `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Write failing tests for first-class objects**

Append:

```python
def test_parse_tex_source_paper_extracts_tables_figures_and_equations(tmp_path: Path) -> None:
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py::test_parse_tex_source_paper_extracts_tables_figures_and_equations -q
```

Expected: FAIL because first-class objects are not implemented.

- [ ] **Step 3: Implement environment and balanced-brace scanner**

Implement:

- `_find_environment_spans(text: str, warnings: list[str])`
- `_find_display_math_spans(text: str)`
- `_find_matching_brace(text: str, open_pos: int) -> int`
- `_extract_command_argument(text: str, command_name: str) -> str`
- `_extract_caption`, `_extract_label`, `_extract_graphics_paths`
- `_quality_flags_for_latex(kind: str, latex_source: str, caption: str, label: str)`
- `_build_tables`, `_build_equations`, `_build_figures`

Use raw source spans for `latex_source`. Deduplicate nested `tabular` when it is
inside a `table` span. Generate IDs from labels when present, otherwise use
`table-0001`, `equation-0001`, `figure-0001`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS through object extraction tests.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "✨ feat: extract tex evidence objects"
```

## Task 5: Section Hierarchy, Abstract, Citations, References, And Bibliography

**Files:**
- Modify: `src/source_benchmark/tex_source_parser.py`
- Test: `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Write failing tests for hierarchy and bibliography**

Append:

```python
def test_parse_tex_source_paper_extracts_section_tree_abstract_citations_and_bbl(tmp_path: Path) -> None:
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py::test_parse_tex_source_paper_extracts_section_tree_abstract_citations_and_bbl -q
```

Expected: FAIL because hierarchy, abstract, citations, and `.bbl` parsing are incomplete.

- [ ] **Step 3: Implement section hierarchy and bibliographic extraction**

Replace minimal section extraction with:

- command levels for `part`, `chapter`, `section`, `subsection`,
  `subsubsection`, `paragraph`, `subparagraph`
- parent stack and heading path
- section label extraction near heading command
- appendix detection after `\appendix`
- normalized section type mapping
- object-span removal from section `plain_text`

Implement:

- `_extract_abstract`
- `_extract_citations`
- `_extract_references`
- `_extract_bibliography`
- `_extract_bibliography_from_bbl`
- `_clean_latex_text`

For citations, split comma-separated keys and attach to nearest section when
the citation position is inside a section; otherwise use empty `section_id`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS through hierarchy and bibliography tests.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "✨ feat: build tex section tree and references"
```

## Task 6: Quality Flags, Missing Metadata, Write Helper, And CLI

**Files:**
- Modify: `src/source_benchmark/tex_source_parser.py`
- Test: `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Write failing tests for quality flags and JSON writer**

Append:

```python
def test_parse_tex_source_paper_flags_orphan_tabular_and_missing_metadata(tmp_path: Path) -> None:
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py::test_parse_tex_source_paper_flags_orphan_tabular_and_missing_metadata tests/source_benchmark/test_tex_source_parser.py::test_write_parsed_tex_source_paper_writes_json -q
```

Expected: FAIL until flags and writer are complete.

- [ ] **Step 3: Implement final quality metrics, writer, and CLI**

Implement `write_parsed_tex_source_paper(...)` with sorted, indented JSON.

Add `main()` supporting:

```text
--paper-id
--source
--pdf
--output-dir
```

Complete metrics:

- `section_count`
- `table_count`
- `equation_count`
- `figure_count`
- `citation_count`
- `bibliography_entry_count`
- `unresolved_input_count`
- `partial_environment_count`
- `missing_caption_table_count`
- `missing_label_table_count`
- `parse_warning_count`

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS all TeX parser tests.

- [ ] **Step 5: Commit Task 6**

Run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "✨ feat: finalize tex parser writer and flags"
```

## Task 7: Full Verification And Real Source Smoke

**Files:**
- Modify only if verification exposes defects:
  - `src/source_benchmark/tex_source_parser.py`
  - `tests/source_benchmark/test_tex_source_parser.py`

- [ ] **Step 1: Run focused parser tests**

Run:

```powershell
pytest tests/source_benchmark/test_tex_source_parser.py -q
```

Expected: PASS.

- [ ] **Step 2: Run source benchmark test subset**

Run:

```powershell
pytest tests/source_benchmark tests/reader/test_latex_source_extractor.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full test suite if time permits**

Run:

```powershell
pytest -q
```

Expected: PASS. If unrelated existing tests fail, record the failing tests and
whether the failure is connected to this parser change.

- [ ] **Step 4: Run manual smoke on an already downloaded real source if available**

If a local probe source exists at `%TEMP%\risearch_tex_probe\2303.03378.eprint`,
run:

```powershell
python -m src.source_benchmark.tex_source_parser --paper-id 2303.03378 --source "$env:TEMP\risearch_tex_probe\2303.03378.eprint" --output-dir "$env:TEMP\risearch_tex_probe\parsed"
```

Expected: JSON file is written with `source_type = "arxiv_tex"`, nonzero sections,
nonzero tables, and warnings only for explainable static-parser limitations.

- [ ] **Step 5: Commit any verification fixes**

If verification required changes, run:

```powershell
git add src/source_benchmark/tex_source_parser.py tests/source_benchmark/test_tex_source_parser.py
git commit -m "🐛 fix: harden tex parser verification cases"
```

If no fixes were required, do not create an empty commit.

## Self-Review

- Spec coverage: local archive/directory/plain inputs, no download/cache, PDF provenance only, main detection, include expansion, section tree, first-class tables/equations/figures, citations, `.bbl` bibliography, warnings, metrics, writer, and tests are each covered by tasks above.
- Placeholder scan: no unfinished-marker words or vague implementation-only placeholders remain.
- Type consistency: public function names, top-level JSON keys, metric names, and quality flag names match the approved design.
