# Non-LLM TeX PaperIR Ingest Design

Date: 2026-06-29

## Status

Approved design checkpoint for PaperIR ingest v1.

This spec defines a pure non-LLM, TeX-first ingest path. If the resulting PaperIR
quality is not good enough in real evaluation, the next step is to redesign ingest
as an LLM-based system. This v1 design deliberately does not introduce hybrid LLM
repair.

## Motivation

The previous ingest pipeline used fixed LLM reading stages and large paper
contexts. It produced weak downstream survey and SOTA results, and it blurred the
boundary between source parsing, paper understanding, topic projection, and
domain update.

PDF and arXiv HTML parser experiments were also not reliable enough for the
project's needs. Dense tables, formulas, and two-column layouts caused malformed
Markdown and merged table regions. TeX source parsing is now the primary path
because it gives cleaner section boundaries, table environments, labels,
captions, equations, and provenance.

The purpose of ingest v1 is to build a stable, topic-agnostic paper evidence
artifact that later modules can consume without touching raw sources.

## Scope

Ingest v1 builds `PaperIR` from arXiv TeX source archives.

It does:

- consume the topic download manifest
- parse arXiv TeX source when available
- build section-first paper structure
- build section-local chunks
- preserve tables, equations, and figures as first-class evidence objects
- preserve raw LaTeX source for tables and equations
- attach objects to sections
- record citations, bibliography, provenance, metrics, and quality warnings
- write `paper_ir.json` artifacts and a topic-level ingest report

It does not:

- call an LLM
- summarize papers
- extract contributions
- extract SOTA records
- normalize table cells
- use PDF or HTML as fallback PaperIR sources
- replace the legacy `topic ingest` command in v1

## Source Policy

PaperIR v1 is TeX-only.

```text
TeX source available and parsed -> PaperIR
TeX source missing or parse failed -> failed PaperIR stub
```

PDF paths may be recorded as provenance, but PDF content is not parsed for v1
PaperIR. arXiv HTML is not used.

Successful source policy:

```json
{
  "primary": "arxiv_tex",
  "used": "arxiv_tex",
  "status": "available",
  "fallback_used": false,
  "source_archive_path": "sources/2303.03378.tar.gz",
  "pdf_path": "pdfs/2303.03378.pdf"
}
```

Failed source policy:

```json
{
  "primary": "arxiv_tex",
  "used": null,
  "status": "tex_unavailable",
  "fallback_used": false,
  "source_archive_path": null,
  "pdf_path": "pdfs/unknown.pdf"
}
```

The reason for excluding fallback in v1 is evaluation clarity. If PDF/HTML
fallback is mixed into v1, it becomes harder to judge whether non-LLM TeX-first
ingest is good enough.

## PaperIR Top-Level Shape

PaperIR uses flat arrays plus IDs and references. Sections define the document
tree, while chunks and evidence objects are separate arrays connected by IDs.

```json
{
  "schema_version": "paper_ir.v1",
  "paper_id": "2303.03378",
  "title": "PaLM-E: An Embodied Multimodal Language Model",
  "abstract": "...",
  "source_policy": {},
  "sections": [],
  "chunks": [],
  "tables": [],
  "equations": [],
  "figures": [],
  "citations": [],
  "bibliography": [],
  "quality": {},
  "provenance": {}
}
```

Flat arrays are preferred over nesting all content inside sections because:

- retrieval and indexing can scan chunks directly
- table/equation/figure evidence can be scanned independently
- section objects remain lightweight document structure
- references are explicit through `section_id`, `object_refs`, and object IDs

## Sections

Sections are the primary document structure.

```json
{
  "section_id": "sec-0008",
  "title": "TAMP Environment",
  "normalized_type": "experiments",
  "level": 2,
  "parent_id": "sec-0006",
  "heading_path": ["Experiments", "TAMP Environment"],
  "order": 7,
  "text_stats": {
    "char_count": 2518,
    "chunk_count": 2
  },
  "object_refs": [
    "table:tab:damp_one_percent_data",
    "table:tab:lt_sim"
  ],
  "provenance": {
    "source_file": "main.tex",
    "line_start": 430,
    "line_end": 575
  }
}
```

Sections may have zero chunks. Empty appendix sections that only contain tables
or figures should still be preserved.

## Chunks

A chunk is a section-local text retrieval unit.

Rules:

- chunks are created only within one section
- chunks never cross section boundaries
- chunk text contains paragraph-level text
- table, equation, and figure raw content is not embedded in chunk text
- chunks reference nearby or mentioned objects through `object_refs`
- chunks preserve `heading_path`
- default overlap is zero
- empty sections do not receive fake chunks

Initial chunking parameters:

```text
target_chunk_tokens: 700
max_chunk_tokens: 1200
min_chunk_tokens: 150
overlap: 0
```

Small sections can produce a chunk below `min_chunk_tokens` if the whole section
is short. `min_chunk_tokens` is a merge preference, not a hard requirement.

Example chunk:

```json
{
  "chunk_id": "2303.03378:sec-0008:c0002",
  "section_id": "sec-0008",
  "heading_path": ["Experiments", "TAMP Environment"],
  "order": 1,
  "text": "The simulated planning setting follows Lynch et al. and reports success rates over several tasks and demo counts. The paper discusses how full-mixture training and model scale affect planning performance.",
  "token_estimate": 45,
  "object_refs": [
    "table:tab:lt_sim"
  ],
  "citation_refs": [
    "lynch2022interactive"
  ],
  "provenance": {
    "source_file": "main.tex",
    "line_start": 456,
    "line_end": 490
  }
}
```

Downstream LLM context should be assembled from:

```text
section heading + relevant chunk text + referenced evidence objects
```

not from chunk text alone.

## Evidence Objects

Tables, equations, and figures are independent evidence objects.

### Tables

Tables preserve raw LaTeX as canonical evidence. PaperIR v1 does not require or
produce normalized cell grids.

```json
{
  "table_id": "tab:lt_sim",
  "section_id": "sec-0008",
  "caption": "Results on planning tasks in the simulated environment from lynch2022interactive.",
  "caption_candidates": [
    "Results on planning tasks in the simulated environment from lynch2022interactive.",
    "Task prompts for tab:lt_sim."
  ],
  "label": "tab:lt_sim",
  "latex_source": "\\begin{table*}[t] ... \\end{table*}",
  "quality_flags": [
    "has_multicolumn",
    "has_resizebox",
    "has_nested_tabular",
    "multiple_captions"
  ],
  "provenance": {
    "source_file": "main.tex",
    "line_start": 510,
    "line_end": 575
  }
}
```

For compound floats such as the `2303.03378` planning-results table, v1 does not
need to split the float into separate table objects. It must preserve the full
raw LaTeX and expose multiple captions through `caption_candidates` and a quality
warning.

### Equations

Display equations are first-class objects.

```json
{
  "equation_id": "eq:loss",
  "section_id": "sec:method",
  "label": "eq:loss",
  "latex_source": "\\begin{equation} ... \\end{equation}",
  "quality_flags": [],
  "provenance": {
    "source_file": "main.tex",
    "line_start": 210,
    "line_end": 218
  }
}
```

Inline math remains in section/chunk text.

### Figures

Figures preserve captions, labels, graphics paths, raw LaTeX, and provenance.

```json
{
  "figure_id": "fig:overview",
  "section_id": "sec:method",
  "caption": "Overview of the method.",
  "label": "fig:overview",
  "graphics_paths": ["figures/overview.pdf"],
  "latex_source": "\\begin{figure} ... \\end{figure}",
  "quality_flags": [],
  "provenance": {
    "source_file": "main.tex",
    "line_start": 300,
    "line_end": 340
  }
}
```

## Quality Gate

The quality gate evaluates PaperIR. It does not repair it.

Even failed papers should write a `paper_ir.json` stub with
`quality.status = "fail"`. Downstream modules should not consume failed PaperIR by
default.

Status values:

```text
pass
warning
fail
```

Fail conditions:

- TeX source is unavailable
- TeX parser availability is not `available`
- no sections are found
- no chunks are generated for non-empty body text
- schema validation fails
- an object ref points to a missing object
- an object has an unresolvable `section_id`
- parser crashes
- chunk generation fails

Warning conditions:

- abstract is missing
- no introduction-like section is found
- unresolved input count is greater than zero
- partial environment count is greater than zero
- one float contains multiple captions
- table is missing caption
- table is missing label
- object is attached to an unknown section
- bibliography is unresolved
- very long section cannot be chunked cleanly
- suspiciously few chunks exist relative to section text size

Quality shape:

```json
{
  "status": "warning",
  "warnings": [
    {
      "code": "multiple_captions_in_float",
      "severity": "warning",
      "target": "table:tab:lt_sim",
      "message": "A single table* environment contains multiple captions. Raw LaTeX is preserved."
    }
  ],
  "metrics": {
    "section_count": 22,
    "chunk_count": 38,
    "table_count": 9,
    "equation_count": 3,
    "figure_count": 7,
    "unknown_section_object_count": 0,
    "unresolved_object_ref_count": 0
  }
}
```

## Output Layout

Do not write PaperIR into the legacy `papers/` directory. That directory contains
old `PaperReadingPackage` artifacts with different semantics.

PaperIR v1 output:

```text
<topic_dir>/
  paper_ir/
    2303.03378/
      paper_ir.json
    1706.03762/
      paper_ir.json
  state/
    paper_ir_ingest_report.json
```

Topic-level report:

```json
{
  "topic_id": "embodied_ai",
  "manifest_path": "manifest.yaml",
  "total": 10,
  "succeeded": ["2303.03378"],
  "warning": ["1706.03762"],
  "failed": ["missing_source"],
  "artifacts": {
    "2303.03378": "paper_ir/2303.03378/paper_ir.json"
  },
  "quality_summary": {
    "pass": 6,
    "warning": 3,
    "fail": 1
  }
}
```

## CLI Integration

Add a parallel ingest path rather than replacing legacy topic ingest in v1.

Recommended command:

```text
python run.py topic ingest-ir --topic <topic.yaml> --manifest <manifest.yaml>
```

The command should:

1. load the existing download manifest
2. create a PaperIR output directory
3. process each paper independently
4. write success, warning, or failed PaperIR artifacts
5. write `state/paper_ir_ingest_report.json`

The existing `topic ingest` command should remain available until downstream
pipeline stages are migrated to PaperIR.

## Implementation Modules

Add a new formal ingest package instead of extending the legacy staged reader.

```text
src/ingest/
  paper_ir.py
  paper_ir_builder.py
  chunker.py
  quality.py
  storage.py
  cli.py
```

Suggested responsibilities:

- `paper_ir.py`: dataclasses or schema helpers for PaperIR
- `paper_ir_builder.py`: TeX parser output -> PaperIR
- `chunker.py`: section-local chunk generation and object-ref attachment
- `quality.py`: quality gate and structured warnings
- `storage.py`: read/write PaperIR and topic ingest reports
- `cli.py`: command implementation

`src/source_benchmark/tex_source_parser.py` can be reused through an adapter for
the first implementation, but it should not remain the long-term formal ingest
parser API. A later cleanup can move or refactor the parser into `src/ingest/`
once the PaperIR path is validated.

## Example: 2303.03378

The real TeX parser smoke for `2303.03378` produced:

```text
sections: 22
tables: 9
equations: 3
figures: 7
citations: 129
bibliography entries: 66
parser warnings: 0
```

The previous PDF extraction failure merged the planning results table and task
prompt table. In TeX, that content appears as a compound `table*` with two
captions inside one outer environment. PaperIR v1 should preserve that full
environment as raw LaTeX and mark the multiple-caption condition in quality
metadata.

## Testing And Evaluation

Unit tests should cover:

- successful PaperIR from a single-file TeX source
- successful PaperIR from a multi-file TeX source with `\input` / `\include`
- failed stub when source archive is missing
- failed stub when parser availability is not `available`
- section-local chunks do not cross section boundaries
- object refs resolve to existing table/equation/figure objects
- tables are not embedded in chunk text
- empty object-only sections are preserved
- multiple captions in one float generate a warning
- topic-level report counts pass, warning, and fail artifacts

Real-paper smoke tests should include:

- `2303.03378` for compound table behavior
- one long survey paper
- one equation-heavy ML paper
- one appendix-heavy paper
- one multi-file arXiv source with table files

Evaluation should answer one question:

```text
Is pure non-LLM TeX PaperIR good enough for downstream TopicPaperView, SOTA, and QA?
```

If not, the project should redesign ingest as an LLM-based system rather than add
ad hoc repair to this v1 path.

## Deferred Decisions

- exact typed implementation style: dataclasses, Pydantic, or plain dict schema
- final storage abstraction beyond JSON files
- downstream TopicPaperView retrieval API
- whether to migrate or wrap `tex_source_parser.py`
- whether to add fallback in a later version
- whether to redesign ingest as LLM-based after evaluation

