# TeX Source Parser Design

Date: 2026-06-23

## Status

Approved design checkpoint for the TeX source parser experiment.

## Goal

Implement a standalone TeX-first parser for already downloaded arXiv source
packages. The parser emits section-first JSON evidence for future PaperMemory
ingest experiments.

The parser does not download arXiv sources, manage caches, call an LLM, parse
PDF content, or normalize tables into cell grids. A downloaded PDF path may be
recorded as provenance only.

## Research Findings

arXiv source packages are not uniform. Official documentation states that source
downloads may be single gzip-compressed TeX-like files or gzip-compressed tar
archives. Real package inspection confirmed both shapes.

Probe papers:

- `2303.03378`: tar archive, two TeX files, one include, table-heavy main file.
- `1706.03762`: tar archive, ten TeX files, main `ms.tex`, many simple inputs.
- `1810.04805`: tar archive, twenty TeX files, short `main.tex`, many included
  section and table files.
- `2103.00020`: tar archive, four TeX files, large `clip_paper.tex`, included
  large table files.
- `hep-lat/9107002v1`: single gzip-compressed TeX-like source.

Library probes:

- `pylatexenc` parsed the tested expanded sources quickly and exposes node
  positions, but it is still not a full TeX engine and should not own the whole
  extraction path.
- `TexSoup` parsed the samples but was slower and does not provide the source
  span/provenance control needed by the output schema.
- `plasTeX` failed on a real source because it attempted package-aware expansion
  and graphics processing. That behavior conflicts with static evidence
  preservation.

The implementation should therefore use a conservative static source-span parser
as the primary mechanism. Optional third-party parsing can be considered later
for text cleanup, but it is not required for the first implementation.

## Public Interface

Add `src/source_benchmark/tex_source_parser.py`.

Primary functions:

```python
def parse_tex_source_paper(
    *,
    paper_id: str,
    source_path: Path,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    ...


def write_parsed_tex_source_paper(
    *,
    paper_id: str,
    source_path: Path,
    output_dir: Path,
    pdf_path: Path | None = None,
) -> Path:
    ...
```

The JSON output uses:

- `source_type = "arxiv_tex"`
- `parser_name = "tex_source_parser"`
- explicit `availability` states
- `source_archive_path`, `source_root`, `main_tex_file`, and optional `pdf_path`

No network or cache API is exposed from this parser.

## Source Materialization

The parser accepts local inputs only:

- extracted source directory
- `.tar`
- `.tar.gz`
- single `.gz` TeX-like source
- plain `.tex`
- `.zip` when practical

Archives are extracted into a temporary directory for parsing. Extraction must be
path-safe and reject path traversal. Directory inputs are read in place.

If materialization fails, the output availability is `archive_extract_failed`.
If no TeX entrypoint can be found, the output availability is
`no_tex_entrypoint`.

## Main File Detection

The parser scores TeX files using:

- `\documentclass` or `\documentstyle`
- `\begin{document}`
- preferred names such as `main.tex`, `paper.tex`, `ms.tex`, `article.tex`
- file size as a weak tie-breaker

If multiple strong candidates exist, the parser chooses the highest score and
records a `multiple_main_candidates` warning.

## Include Expansion

The parser expands simple static includes:

- `\input{...}`
- `\include{...}`
- omitted `.tex` suffix
- relative paths from the current source file

Expansion records source segments with source file, absolute character range in
the flattened text, and original line offset. This segment map is used to recover
object and section provenance.

Unresolved includes are preserved as raw commands, recorded as warnings, and
counted in metrics. Recursive include cycles are skipped with warnings.

## Extraction Strategy

The primary extraction mechanism is a balanced-brace and environment scanner over
the flattened TeX text after comment stripping.

First-class objects:

- tables: `table`, `table*`, `sidewaystable`, `sidewaystable*`, `wraptable`,
  `longtable`, and orphan `tabular`, `tabular*`, `tabularx`
- figures: `figure`, `figure*`, `wrapfigure`, `sidewaysfigure`,
  `sidewaysfigure*`
- equations: `equation`, `equation*`, `align`, `align*`, `gather`, `gather*`,
  `multline`, `multline*`, `\[...\]`, and `$$...$$`

Tables nested inside table floats are not emitted again as separate objects.
Orphan tabular-like environments are emitted as tables with a quality flag.

Captions, labels, graphics paths, citations, refs, and bibliography entries are
extracted with balanced argument scanning where possible. When extraction is
partial, the raw source span remains the canonical evidence and quality flags
describe the uncertainty.

## Section Model

Sections are extracted from:

- `\part`
- `\chapter`
- `\section`
- `\subsection`
- `\subsubsection`
- `\paragraph`
- `\subparagraph`

The parser builds parent relationships with a level stack. Section IDs prefer a
nearby section `\label{...}` when available; otherwise they use stable generated
IDs. Appendix mode starts after `\appendix` or appendix-like headings and is
reflected through `normalized_type = "appendix"` when applicable.

Section `latex_source` preserves the section span. Section `plain_text` is
best-effort text cleanup with first-class object spans removed, so tables and
display equations are not duplicated as ordinary paragraphs.

## Bibliography

The parser extracts `\bibitem` entries from:

- inline `thebibliography` environments in the flattened TeX
- `.bbl` files in the source root, preferring names associated with the main file
  or `\bibliography{...}` commands

If the source only contains `\bibliography{...}` and no usable `.bbl` is found,
the parser records `bibliography_unresolved`.

## Quality Flags And Metrics

Stable quality flags include:

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
- `orphan_tabular`

Metrics include the handoff-required counts for sections, tables, equations,
figures, citations, bibliography entries, unresolved inputs, partial
environments, missing table captions, missing table labels, and warnings.

## Testing Plan

Add focused tests under `tests/source_benchmark/test_tex_source_parser.py`.

Required synthetic layouts:

- single-file TeX paper with title, abstract, section, table, equation, figure,
  citations, and inline bibliography
- multi-file TeX paper using `\input` / `\include`, table file, figure file, and
  external `.bbl`

Additional tests:

- wrapped table with `\resizebox` and nested `tabular`
- orphan `tabular`
- missing table caption or label quality flags
- unresolved include warning and metric
- archive input smoke test

Optional manual smoke commands may be documented for real downloaded sources,
but tests must not depend on network access.

## Known Limitations

The parser does not execute arbitrary TeX macros, resolve custom command
semantics, compile projects, infer table cells, or parse PDF content. Very
macro-heavy captions or environments may be partially cleaned, but raw LaTeX
evidence remains available. Complex catcode changes and generated include names
are out of scope for the first implementation.
