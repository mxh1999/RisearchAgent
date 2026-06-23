# TeX Source Parser Agent Handoff

## Background

RisearchAgent is redesigning the paper ingest pipeline. Previous PDF and arXiv HTML
parser experiments showed that pure PDF/HTML extraction is not reliable enough for
the project goal, especially for dense tables, formulas, and two-column layouts.

The ingest redesign has now shifted to a TeX-first direction:

- arXiv TeX source should become the primary ingest source when available.
- PDF and arXiv HTML are fallback or validation sources, not the primary semantic
  source.
- Ingest must produce a stable paper-local representation that downstream modules
  can consume directly.
- Downstream survey, SOTA, update, and QA modules should not be responsible for
  fixing source parsing.

This task is for an independent implementation agent. The goal is to implement a
TeX source parser component and validate whether TeX source can provide a clean
enough substrate for the new ingest pipeline.

## Current Design Decision

Do not parse TeX tables into normalized cell grids during ingest.

The important output is lossless or near-lossless TeX evidence:

- section tree
- section-local text blocks
- table boundaries
- table captions
- table labels
- raw table LaTeX source
- equation boundaries
- equation labels
- raw equation LaTeX source
- figure captions and labels
- citations and references when practical
- source provenance

Later LLM-based modules can read raw LaTeX source in task-specific context. The
parser should preserve evidence and structure; it should not attempt fragile
semantic interpretation.

## Task Goal

Implement a standalone TeX source parser experiment for arXiv papers.

The parser should take an arXiv source archive or extracted source directory and
emit a JSON artifact that can serve as a TeX-first candidate for future PaperIR /
PaperMemory ingest.

This is not a full production ingest rewrite. It is an implementation experiment
with clear output schema and acceptance criteria.

## Non-Goals

- Do not implement SOTA extraction.
- Do not summarize papers.
- Do not judge topic relevance.
- Do not update DomainState or SOTA leaderboards.
- Do not call an LLM.
- Do not require PDF upload or whole-PDF processing.
- Do not rely on PDF/HTML parsing for the primary structure.
- Do not normalize tables into cell grids as a required output.
- Do not try to fully compile every LaTeX project.

## Input

The parser should support at least one of these input forms:

- local arXiv source archive, such as `2303.03378.tar.gz`
- local extracted source directory
- optional arXiv id, where the implementation may download source from:

```text
https://arxiv.org/e-print/<arxiv_id>
```

The implementation should cache downloaded source archives by `arxiv_id` and, if
available, arXiv version.

## Output

Emit one JSON file per paper. The schema may evolve, but it should contain at
least the following fields.

```json
{
  "paper_id": "2303.03378",
  "source_type": "arxiv_tex",
  "availability": "available",
  "parser_name": "tex_source_parser",
  "parser_version": "string",
  "source_archive_path": "string",
  "source_root": "string",
  "main_tex_file": "string",
  "title": "string",
  "abstract": "string",
  "sections": [],
  "tables": [],
  "equations": [],
  "figures": [],
  "citations": [],
  "bibliography": [],
  "warnings": [],
  "metrics": {}
}
```

Use explicit failure states instead of silent success:

```text
availability:
  available
  unavailable
  download_failed
  archive_extract_failed
  no_tex_entrypoint
  parse_failed
```

## Required Objects

### Section

Sections are the primary organization boundary.

```json
{
  "section_id": "sec:method",
  "title": "Method",
  "level": 1,
  "normalized_type": "method",
  "parent_id": null,
  "order": 3,
  "heading_path": ["Method"],
  "latex_source": "string",
  "plain_text": "string",
  "source_file": "main.tex",
  "line_start": 120,
  "line_end": 260
}
```

`plain_text` is best-effort and may preserve inline math as LaTeX. It should not
contain tables or display equations duplicated as ordinary paragraphs if they are
also represented as independent objects.

### Table

Tables must be first-class objects.

```json
{
  "table_id": "tab:planning",
  "caption": "Results on planning tasks.",
  "label": "tab:planning",
  "section_id": "sec:experiments",
  "latex_source": "\\begin{table} ... \\end{table}",
  "source_file": "main.tex",
  "line_start": 812,
  "line_end": 865,
  "references": ["Table~\\ref{tab:planning}"],
  "quality_flags": ["has_multicolumn", "has_resizebox"]
}
```

Do not require `normalized_cells`. The raw table source is the canonical evidence.

The parser should recognize common table environments, including:

- `table`
- `table*`
- `tabular`
- `tabular*`
- `tabularx`
- `longtable`
- `sidewaystable`
- `wraptable`
- tables wrapped by `resizebox`, `scalebox`, `adjustbox`, or similar commands

If an environment is partially parsed, keep the largest reliable raw source span
and add a warning or quality flag.

### Equation

Display equations should be first-class objects when practical.

```json
{
  "equation_id": "eq:loss",
  "label": "eq:loss",
  "section_id": "sec:method",
  "latex_source": "\\begin{equation} ... \\end{equation}",
  "source_file": "main.tex",
  "line_start": 210,
  "line_end": 218,
  "references": ["Eq.~\\ref{eq:loss}"],
  "quality_flags": []
}
```

Recognize common display math forms:

- `equation`
- `equation*`
- `align`
- `align*`
- `gather`
- `gather*`
- `multline`
- `multline*`
- `\[ ... \]`
- `$$ ... $$`

Inline math can remain inside section text.

### Figure

Figures should preserve caption, label, file references, and raw LaTeX.

```json
{
  "figure_id": "fig:overview",
  "caption": "Overview of the method.",
  "label": "fig:overview",
  "section_id": "sec:method",
  "latex_source": "\\begin{figure} ... \\end{figure}",
  "graphics_paths": ["figures/overview.pdf"],
  "source_file": "main.tex",
  "line_start": 300,
  "line_end": 340
}
```

## Parser Responsibilities

### Source Acquisition

If downloading is implemented, use arXiv source archives:

```text
https://arxiv.org/e-print/<arxiv_id>
```

Requirements:

- cache archives locally
- handle `.tar`, `.tar.gz`, `.gz`, and plain TeX-like source payloads if practical
- avoid blocking the whole batch on one slow or failed download
- record timeout and download failures clearly

### Main TeX Entrypoint Detection

The parser should identify the main TeX file. Reasonable heuristics include:

- file containing `\documentclass`
- file containing `\begin{document}`
- largest candidate TeX file with document structure
- arXiv naming conventions such as `main.tex`, `paper.tex`, `ms.tex`

If multiple candidates exist, choose the best one and record a warning.

### Include Expansion

The parser should resolve common include patterns:

- `\input{...}`
- `\include{...}`
- simple relative paths
- omitted `.tex` suffix

It does not need to support arbitrary TeX macro execution, but it should preserve
unresolved include commands and record warnings instead of dropping content.

### Structure Extraction

Extract section hierarchy from:

- `\part`
- `\chapter`
- `\section`
- `\subsection`
- `\subsubsection`
- `\paragraph`
- `\subparagraph`

Appendix sections should be retained and marked as appendix when detectable.

### Evidence Extraction

Extract first-class objects for:

- tables
- display equations
- figures
- captions
- labels
- citations
- bibliography entries when practical

Every first-class object should be attached to the nearest enclosing section.

## Quality Flags

Use quality flags to communicate parser uncertainty without pushing repair work to
downstream modules.

Suggested flags:

- `unresolved_macro`
- `unresolved_input`
- `multiple_main_candidates`
- `partial_environment`
- `unbalanced_braces`
- `has_multicolumn`
- `has_multirow`
- `has_resizebox`
- `has_adjustbox`
- `has_nested_tabular`
- `has_math`
- `caption_missing`
- `label_missing`
- `section_unknown`
- `bibliography_unresolved`

Warnings should be human-readable. Quality flags should be stable identifiers.

## Metrics

The JSON output should include stable metrics for benchmark comparison:

```json
{
  "section_count": 0,
  "table_count": 0,
  "equation_count": 0,
  "figure_count": 0,
  "citation_count": 0,
  "bibliography_entry_count": 0,
  "unresolved_input_count": 0,
  "partial_environment_count": 0,
  "missing_caption_table_count": 0,
  "missing_label_table_count": 0,
  "parse_warning_count": 0
}
```

## Acceptance Criteria

The task is complete when all of the following are true:

1. The parser can run on at least one local arXiv source archive or extracted
   source directory and emit a JSON artifact.
2. The output uses `source_type = "arxiv_tex"`.
3. The output includes section-first structure.
4. Tables are represented as first-class objects with raw `latex_source`.
5. Display equations are represented as first-class objects when detectable.
6. Figures preserve captions, labels, and graphics paths when available.
7. The parser resolves simple `\input` / `\include` trees.
8. The parser records provenance with source file and line spans where practical.
9. Parse failures and partial extraction are visible through `availability`,
   `warnings`, `quality_flags`, and `metrics`.
10. No LLM calls are used.
11. No PDF/HTML parser dependency is required for the primary TeX structure.
12. Tests or smoke scripts demonstrate the behavior on at least two source
    layouts:
    - a simple single-file TeX paper
    - a multi-file TeX paper using `\input` or `\include`

## Recommended Smoke Test Paper

Use `2303.03378` as one smoke test if its arXiv source download is available. It
contains important table-heavy content where PDF extraction previously merged
neighboring tables incorrectly. The expected TeX parser behavior is not to
understand the table semantically, but to preserve each table as a separate raw
LaTeX object with the correct caption, label if present, and section assignment.

## Implementation Guidance

Prefer a conservative static parser first.

Good first implementation strategy:

1. Extract or locate source files.
2. Detect the main TeX file.
3. Expand simple `\input` and `\include`.
4. Strip comments without corrupting escaped percent signs.
5. Tokenize commands and environments with source spans.
6. Build section hierarchy.
7. Attach environments and text blocks to nearest section.
8. Emit JSON.
9. Add focused tests for includes, section nesting, table extraction, equation
   extraction, labels, captions, and provenance.

Avoid starting with a full TeX engine. The first milestone should be robust
evidence preservation, not complete LaTeX interpretation.

## Deliverables

The implementation agent should deliver:

- source code for the TeX parser experiment
- tests or smoke scripts
- at least two generated sample JSON outputs or a command that regenerates them
- short notes describing known parser limitations and failure modes

The implementation should be kept separate from the existing PDF/HTML benchmark
code unless sharing a small utility is clearly useful.

