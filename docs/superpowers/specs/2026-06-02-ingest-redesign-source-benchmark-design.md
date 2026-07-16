# Ingest Redesign And Source Benchmark Design

Date: 2026-06-02

## Status

Approved design checkpoint. This spec captures the agreed direction so far. It does
not define the final PaperMemory schema or implementation plan. Those decisions
depend on the Phase 0 source extraction benchmark.

## Motivation

The current topic ingest flow reads each paper through a fixed set of LLM prompts
and then feeds large paper context into downstream stages. This has produced weak
survey and SOTA results, and previous tests showed that the configured provider is
unstable with files and long contexts.

The redesigned pipeline should stop treating ingest as "summarize one paper".
Ingest should construct reusable paper memory, and later stages should retrieve
only the relevant sections, chunks, tables, and evidence needed for a specific
task.

## Primary Use Cases

1. Survey an unfamiliar field.
   The pipeline discovers and ingests papers, builds a domain state, creates SOTA
   data, and renders a survey report.

2. Add a new paper to an already surveyed field.
   The pipeline ingests the paper, evaluates its value against the existing domain
   state, reports the delta, and updates SOTA/domain artifacts when justified.

3. Interactively ask questions about a specific paper.
   The system answers from paper evidence. Accepted corrections or annotations can
   update paper, topic, or domain data.

## Design Direction

Use a fully layered design rather than preserving the current topic-bound ingest
shape.

```text
raw source
  -> PaperMemory
  -> TopicPaperView
  -> DomainState / DomainDelta
  -> reports
  -> interactive QA and patches
```

The key architectural choice is to separate paper-local memory from topic-specific
interpretation.

## Core Artifacts

### PaperMemory

Topic-agnostic memory for one paper. It should contain structured, section-first
paper evidence and retrieval metadata. It should not decide how important the
paper is for a specific topic.

Final fields are intentionally deferred until after the source benchmark. The
expected direction is:

- identity and source metadata
- section-first document structure
- chunks under sections
- tables, figures, captions, references
- evidence units with provenance
- parse quality warnings
- retrieval index metadata

### TopicPaperView

Topic-specific projection of one PaperMemory.

Expected responsibilities:

- topic relevance
- matched concept axes
- method taxonomy hints
- contribution candidates
- topic-relevant experiment candidates
- benchmark, dataset, metric, and result records
- topic-relevant limitations and failure modes
- evidence refs and confidence flags

### DomainState

Canonical state for one surveyed field. Version 1 should implement practical
survey knowledge while leaving interfaces for richer claim graphs later.

Expected content:

- topic profile
- paper registry
- taxonomy
- method families
- datasets
- benchmarks
- metrics
- SOTA tables
- key papers
- open problems
- terminology
- unresolved conflicts
- provenance

### DomainDelta

The proposed change caused by adding a new paper or accepting an interaction
patch.

Expected content:

- taxonomy changes
- method family changes
- SOTA updates
- conflicts
- key paper changes
- survey patch suggestions
- confidence and review flags
- evidence refs

### InteractionPatch

Structured update generated from user interaction.

Expected content:

- target: PaperMemory, TopicPaperView, or DomainState
- operation: add, update, delete, mark conflict, or mark reviewed
- reason
- evidence
- user note

## Pipeline V2

### Phase 0: Source Extraction Benchmark

Before designing final PaperMemory ingest, decide which arXiv source should be the
default input.

Scope:

- only arXiv papers
- only ML/AI/Robotics-related categories: `cs.LG`, `cs.AI`, `cs.CV`, `cs.RO`,
  `stat.ML`
- no TeX source, because source archive downloads are too slow for normal use
- automatically download both PDF and arXiv HTML
- compare PDF extraction and arXiv HTML extraction
- use pairwise manual preference, not numeric manual scoring
- run as a standalone experiment, not a permanent pipeline component

Phase 0a uses 8-10 smoke papers. Phase 0b expands to 20-30 papers only if Phase 0a
is inconclusive.

Phase 0a buckets:

- ML single-column clean paper
- LLM/NLP-style arXiv paper
- CV two-column vision paper
- Embodied AI or robotics two-column paper
- long ML/AI survey paper
- benchmark or dataset paper
- table-heavy leaderboard paper
- appendix-heavy ML paper
- equation-heavy ML paper
- older ML/AI arXiv paper

Each paper downloads:

```text
https://arxiv.org/pdf/<arxiv_id>
https://arxiv.org/html/<arxiv_id>
```

HTML unavailability is recorded as source-policy evidence.

Automatic comparison metrics:

- text character count
- section count
- normalized section coverage
- table count
- figure caption count
- reference count
- noise warnings
- chunk count
- oversized chunk count
- candidate numeric result count

Manual pairwise preferences:

```yaml
section_structure: pdf | html | tie | neither
text_readability: pdf | html | tie | neither
table_usability: pdf | html | tie | neither
evidence_locality: pdf | html | tie | neither
sota_readiness: pdf | html | tie | neither
overall_primary_choice: pdf | html | tie | neither
notes: ""
```

Decision rule:

- If one source wins `overall_primary_choice` on at least 70% of papers and
  `table_usability` / `sota_readiness` do not strongly disagree, choose it as the
  primary source.
- Otherwise, expand to Phase 0b.

Phase 0 output:

```text
primary_source: pdf | arxiv_html
fallback_source: arxiv_html | pdf
fallback_conditions: [...]
```

### Parser Exploration Boundary

Parser implementation is deliberately delegated to independent exploration tasks.
This spec defines their goal and acceptance criteria, not their implementation.

Two independent agents or sessions should later explore:

- PDF extraction candidate
- arXiv HTML extraction candidate

Both must emit the same benchmark output schema:

```text
ParsedPaper
- paper_id
- source_type: pdf | html
- parser_name
- parser_version_or_notes
- title
- text_chars
- sections[]
- chunks[]
- tables[]
- figures[]
- references[]
- warnings[]
```

Core nested objects:

```text
Section
- section_id
- title
- normalized_type
- level
- parent_id
- order
- text
- char_count

Chunk
- chunk_id
- section_id
- order
- text
- token_estimate
- heading_path

Table
- table_id
- section_id
- caption
- markdown
- raw_text
- numeric_cell_count

Figure
- figure_id
- section_id
- caption

Reference
- reference_id
- raw_text
```

Acceptance criteria for Phase 0a:

- 8-10 arXiv papers are downloaded, or failures are explicitly recorded.
- Every paper has PDF parsed output.
- HTML-available papers have HTML parsed output.
- All parsed outputs conform to the same schema.
- Each paper has a pairwise Markdown comparison report.
- `manual_preferences.yaml` can be filled and summarized.
- `summary.md` reports overall and per-dimension PDF/HTML preferences.
- The result recommends a primary/fallback source policy or explicitly triggers
  Phase 0b.

### Phase 1: Paper Ingest

After Phase 0 selects the source policy, implement PaperMemory ingest.

Responsibilities:

- parse the selected primary source
- fall back when the source is unavailable or parse quality fails
- build section-first document structure
- chunk within sections
- extract tables, figures, and references
- create evidence units
- build retrieval index metadata
- store parse quality warnings

Non-goals:

- no topic relevance judgment
- no SOTA update
- no final survey note generation
- no whole-paper long-context LLM prompt

### Phase 2: Topic Projection

`PaperMemory + TopicProfile -> TopicPaperView`

LLM jobs must use scoped context, for example:

- method extraction from method-like sections
- experiment extraction from result sections and table chunks
- topic relation from abstract, introduction, conclusion, and retrieved chunks

### Phase 3: Domain Build / Update

Unknown field survey:

```text
TopicPaperView x N -> DomainState
```

Known field new-paper update:

```text
new TopicPaperView + existing DomainState -> DomainDelta -> updated DomainState
```

### Phase 4: Report Rendering

Reports are views over state, not direct raw-paper LLM outputs.

Expected reports:

- `survey.md`
- `sota.md`
- `papers.md`
- `update_report.md`
- QA patch reports

### Phase 5: Interactive QA And Patch

QA retrieves from PaperMemory, TopicPaperView, and DomainState. Answers cite
evidence. Accepted corrections are represented as InteractionPatch records and can
update the relevant state.

## Key Principles

- section-first, not page-first
- page data is provenance only, not the primary organization boundary
- PaperMemory is topic-agnostic
- TopicPaperView is topic-specific
- DomainState is the canonical survey/SOTA state
- reports are rendered from state
- evidence refs are required for generated conclusions
- LLM jobs use scoped context only
- provider long-context/file instability is treated as a design constraint
- final source policy depends on Phase 0 benchmark evidence

## Deferred Decisions

These are intentionally not decided in this spec:

- final PaperMemory schema
- final TopicPaperView schema
- final DomainState and DomainDelta schema details
- parser implementation choices
- whether PDF or arXiv HTML is primary
- fallback thresholds
- storage layout and migration strategy
- implementation plan

## Open Follow-Up

After Phase 0 produces a source policy, continue design from PaperMemory schema and
retrieval/index interfaces.
