# RisearchAgent V2 Migration Inventory

Date: 2026-07-11

Status: Proposed migration map paired with
`docs/architecture/v2-harness-design.md`.

## 1. Purpose

This document classifies the current repository by migration intent. It prevents
"reuse" from becoming an accidental dependency on legacy control flow.

No large deletion is authorized by this inventory alone. Legacy removal happens
only after the V2 acceptance gates pass and is performed in separate, reviewable
commits.

## 2. Disposition Labels

### `PORT`

The behavior is useful and narrow enough to reimplement in `risearch/`. Porting
means copying the relevant behavior with a new contract and tests. It does not mean
importing the legacy module.

### `REDESIGN`

The capability remains necessary, but the current interface or semantics conflict
with V2. Implement it from the V2 contract rather than adapting the old class.

### `LEGACY_BASELINE`

Keep the component operational temporarily for regression comparison or data
migration. V2 must not depend on it.

### `RETIRE`

The capability or abstraction is not part of the V2 target. Delete it after its
remaining legacy consumers and migration needs are gone.

### `FIXTURE`

Keep data, tests, or samples as evaluation material even if their original
implementation is retired.

## 3. Migration Rules

1. New code lives in the top-level `risearch/` package.
2. `risearch/` must not import `src.*`.
3. Legacy modules are not moved during the first implementation phases; moving
   them would create a large diff without reducing architectural coupling.
4. Useful code is ported behind a V2 contract with dedicated tests.
5. Legacy and V2 artifacts use separate paths during evaluation.
6. Old commands remain frozen except for critical bug fixes.
7. README and default CLI switch only after the V2 paper reader passes its gates.
8. Parser experiments receive no new feature work.
9. Every retirement is a separate logical commit with a clear dependency check.
10. Large deletions require explicit user review at the retirement phase.

## 4. Repository Root

| Path | Disposition | V2 action |
|---|---|---|
| `AGENTS.md` | `PORT` | Keep as the repository operating policy and update commands after the V2 CLI exists. |
| `README.md` | `LEGACY_BASELINE` | Keep current usage accurate during development. Rewrite only when V2 becomes default. |
| `run.py` | `LEGACY_BASELINE` then `RETIRE` | Freeze the monolithic parser/dispatcher. V2 uses `python -m risearch`; later turn `run.py` into a short compatibility shim or delete it. |
| `config.yaml` | local legacy config | Do not migrate user secrets or endpoints automatically. Add a versioned V2 config contract later. |
| `example.yaml` | `REDESIGN` | Replace after provider capabilities and skill budgets are defined. |
| `.env.example` | `PORT` | Keep environment-only secret loading; rename variables only with an explicit migration. |
| `requirements.txt` | `REDESIGN` | Introduce project packaging and separate core, provider, and legacy dependencies. Do not add a graph framework for the MVP. |
| `data/` | `FIXTURE` and user state | Never bulk-delete. Reuse selected local PDFs, TeX samples, and topic outputs as evaluation fixtures. |

## 5. Configuration And Global Models

| Path | Disposition | Rationale and V2 action |
|---|---|---|
| `src/config.py` | `REDESIGN` | It combines legacy pipeline, storage, scraper, and LLM settings. Replace with V2 runtime/provider/skill configuration and explicit capability overrides. |
| `src/models.py` | `RETIRE` | The global pipeline dataclasses describe the legacy database and contribution workflow. Define V2 domain models from evidence and patch contracts. |

Useful configuration behavior to port:

- environment-variable API keys;
- local YAML configuration;
- concurrency and retry defaults;
- no secret values in serialized run state.

Do not port `response_format` as a capability model. Provider dialect and model
capabilities are separate concepts in V2.

## 6. Legacy Global Pipeline

### `src/crawl/`

| Path | Disposition | V2 action |
|---|---|---|
| `src/crawl/pdf_downloader.py` | `PORT` | Port atomic download/cache behavior into source tools after reviewing timeout and validation behavior. |
| `src/crawl/scraper.py` | `RETIRE` | The query-centric global crawler is replaced by topic-scoped search tools and agent query expansion. |

### `src/filter/`

| Path | Disposition | V2 action |
|---|---|---|
| `src/filter/relevance_judge.py` | `RETIRE` | Replace the fixed score stage with skill-specific screening and validation decisions backed by topic evidence. |

### `src/knowledge/`

| Path | Disposition | V2 action |
|---|---|---|
| `src/knowledge/knowledge_base.py` | `RETIRE` | ChromaDB and embedding memory are not part of the active topic design. V2 begins with explicit local evidence and lexical/structured retrieval. |
| `src/knowledge/contribution_analyzer.py` | `RETIRE` | Replace direct contribution classification with topic/domain patch proposals. |
| `src/knowledge/sota_tracker.py` | `RETIRE` | The global Markdown-first tracker is superseded by topic-scoped structured records and deterministic views. |

### `src/pipeline/`

| Path | Disposition | V2 action |
|---|---|---|
| `src/pipeline/orchestrator.py` | `LEGACY_BASELINE` then `RETIRE` | Preserve only until legacy commands are removed. Do not port its five-stage orchestration. |

## 7. LLM Layer

| Path | Disposition | V2 action |
|---|---|---|
| `src/llm/client.py` | `REDESIGN` | Replace prompt-string generation with typed messages, content parts, tools, tool results, usage, and capability snapshots. |
| `src/llm/gpt_client.py` | `REDESIGN` | Implement a new OpenAI-compatible tool-calling provider. Port URL normalization, retry intent, and bounded error reporting where useful. |
| `src/llm/claude_client.py` | `LEGACY_BASELINE` | Keep for legacy commands. Add a V2 provider only after the core contract is stable. |
| `src/llm/gemini_client.py` | `LEGACY_BASELINE` | Keep for legacy commands. Add a V2 provider only after the core contract is stable. |

Do not port permissive JSON extraction as the primary schema boundary. Tool
arguments and finish submissions require explicit validation and visible failures.

## 8. Onboarding

| Path | Disposition | V2 action |
|---|---|---|
| `src/onboard/advisor.py` | `RETIRE` | Topic refinement becomes a research skill over stable topic state. |
| `src/onboard/prompts.py` | `RETIRE` | Review for useful questions, then move selected guidance into the topic-refinement skill. |
| `src/onboard/tools.py` | `RETIRE` | It is coupled to legacy reader and config objects. |

The current `survey refine` topic profile is a better semantic starting point than
the Gemini-only onboarding loop.

## 9. Reader Package

| Path | Disposition | V2 action |
|---|---|---|
| `src/reader/page_extractor.py` | `PORT` | Port page-aware text extraction as a locator/fallback tool. Add independent page rendering and do not treat extracted Markdown as semantic truth. |
| `src/reader/reading_renderer.py` | `PORT` | Port safe IDs, path containment, and deterministic Markdown patterns to the V2 reading schema. |
| `src/reader/latex_source_extractor.py` | partial `PORT`, then `RETIRE` | Port safe archive materialization concepts only. Retire regex table normalization and legacy `SourceTable`. |
| `src/reader/staged_models.py` | `RETIRE` | Replace `PaperReadingPackage` with evidence-linked V2 reading, coverage, and experiment models. |
| `src/reader/staged_reader.py` | `LEGACY_BASELINE` then `RETIRE` | Keep for evaluation. Do not port the five fixed stages or repeated whole-text prompts. |
| `src/reader/staged_cli.py` | `RETIRE` | Replaced by `python -m risearch paper read`. |
| `src/reader/deep_reader.py` | `RETIRE` | Legacy fixed extraction coupled to global storage models. |
| `src/reader/section_parser.py` | `RETIRE` | V2 does not require a semantic section parser gateway. |
| `src/reader/pdf_cli.py` | `LEGACY_BASELINE` then `RETIRE` | Keep as a temporary diagnostic; replace with V2 PDF tool diagnostics. |

The portable V2 PDF baseline is page-aware text search plus selected page images.
Native provider PDF input is an optional capability, not a dependency.

## 10. Source Benchmark Package

| Path | Disposition | V2 action |
|---|---|---|
| `src/source_benchmark/pdf_parser.py` | `LEGACY_BASELINE` and `FIXTURE`, then `RETIRE` | Preserve current outputs for comparison. Do not use its section/table/formula heuristics in V2. |
| `src/source_benchmark/tex_source_parser.py` | partial `PORT`, `FIXTURE`, then `RETIRE` | Port safe extraction, source inventory, bounded file reading, and conservative environment-span ideas. Do not port full PaperIR-oriented section/equation/figure/bibliography extraction. |

The V2 TeX tool should be substantially smaller. Its output is raw candidate
evidence with uncertainty, not a parsed paper.

Candidate behavior to port:

- path-safe archive extraction;
- support for tar, gzip, zip, directory, and plain TeX inputs where justified;
- source file inventory;
- basic main-file hints;
- bounded source reads with file and line provenance;
- conservative table environment span discovery;
- unresolved-include warnings.

Behavior to retire:

- universal section tree;
- normalized section types;
- cleaned whole-paper plain text;
- complete equation and figure inventories;
- bibliography reconstruction;
- PaperIR quality gates;
- rule-based table cell grids.

## 11. Storage Package

| Path | Disposition | V2 action |
|---|---|---|
| `src/storage/database.py` | `LEGACY_BASELINE` then `RETIRE` | Keep only for legacy commands and optional one-time export. V2 uses topic-local versioned files first. |
| `src/storage/exporter.py` | `LEGACY_BASELINE` then `RETIRE` | Use only if legacy SQLite data must be migrated. Do not make V2 depend on the legacy schema. |

V2 storage begins with atomic JSON and append-only JSONL because they are locally
inspectable and align with topic workspaces. A database may be added later behind
the same repository interfaces if scale requires it.

## 12. Survey Package

### Topic And Artifact Foundations

| Path | Disposition | V2 action |
|---|---|---|
| `src/survey/models.py` | `PORT` | Port the concepts of topic ID, intent, concept axes, positive/negative/adjacent/collision scope, query families, anchors, benchmarks, and open questions. Add schema versioning and evidence-aware history. |
| `src/survey/artifacts.py` | `PORT` | Port stable topic paths, AUTO block preservation, and append-only survey event intent. Use atomic writes. |

### Discovery And Download

| Path | Disposition | V2 action |
|---|---|---|
| `src/survey/arxiv_provider.py` | `PORT` | Port arXiv metadata conversion, ID normalization, and explicit rate-limit errors into tools. |
| `src/survey/topic_discover.py` | partial `PORT` | Port candidate identity, deduplication, and deterministic review rendering. Query orchestration belongs to the agent. |
| `src/survey/topic_download.py` | partial `PORT` | Port atomic PDF/source caching, manifest concepts, and explicit source failures. Replace sequential workflow assumptions with source tools. |
| `src/survey/discover_cli.py` | `RETIRE` | Replaced by V2 skill commands. |
| `src/survey/download_cli.py` | `RETIRE` | Replaced by V2 source tools and skill commands. |

### Topic Refinement And Relevance

| Path | Disposition | V2 action |
|---|---|---|
| `src/survey/refiner.py` | `REDESIGN` | Preserve topic-profile semantics and useful prompt questions, but implement them as the `refine-topic` skill with tool access and explicit user decisions. |
| `src/survey/relevance.py` | `REDESIGN` | Preserve the accept/reject/uncertain concept and separate pre-read/post-read evidence. Replace fixed batch prompts with agent decisions and typed evidence. |
| `src/survey/relevance_cli.py` | `RETIRE` | Replaced by V2 topic skills. |

### Reading, Ingest, And Update Orchestration

| Path | Disposition | V2 action |
|---|---|---|
| `src/survey/reading_loader.py` | `RETIRE` | Coupled to flat legacy `PaperReadingPackage` files. V2 reads evidence-linked paper workspaces through a repository interface. |
| `src/survey/topic_ingest.py` | `RETIRE` | Manifest validation ideas may inform source tools, but fixed batch reading is replaced by agent runs. |
| `src/survey/ingest_cli.py` | `RETIRE` | Replaced by `paper read` and `topic survey`. |
| `src/survey/topic_update.py` | `RETIRE` | Replace survey-then-SOTA orchestration with validated domain patches and materialized views. |
| `src/survey/topic_cli.py` | `RETIRE` | Replaced by the V2 CLI. |

### Survey Synthesis

| Path | Disposition | V2 action |
|---|---|---|
| `src/survey/synthesis_models.py` | partial `PORT` | Taxonomy, paper role, positioning, and reference concepts remain useful. Redefine them as domain state and patch objects with evidence IDs. |
| `src/survey/synthesizer.py` | `RETIRE` | Replace one-shot synthesis over all reading packages with iterative retrieval, critique, and patch proposal. |
| `src/survey/survey_renderer.py` | `PORT` | Port deterministic Markdown rendering after new domain models exist. |
| `src/survey/cli.py` | `RETIRE` | Split loading, runtime, and rendering responsibilities into V2 modules. |

### SOTA

| Path | Disposition | V2 action |
|---|---|---|
| `src/survey/sota_models.py` | `PORT` and `REDESIGN` | Port deterministic IDs, record sorting, result kinds, and setting-group concepts. Expand evidence and comparability axes. Remove dependency on `PaperReadingPackage`. |
| `src/survey/sota_normalizer.py` | partial `PORT` | Port conservative exact matching and high-confidence merge policy. Route semantic decisions through V2 verifier/patch contracts. |
| `src/survey/sota_renderer.py` | `PORT` | Preserve deterministic grouping/ranking and main-vs-auxiliary separation; render only accepted records by default. |
| `src/survey/sota_cli.py` | `RETIRE` | Replaced by accepted experiment/domain patches and the V2 renderer command. |

## 13. Tests

All existing tests remain during the parallel implementation. They continue to
protect the frozen legacy baseline but are not evidence that a legacy abstraction
belongs in V2.

### Tests To Port As Behavior References

- safe paper IDs and output path containment;
- page-aware PDF extraction and fallback behavior;
- archive path traversal protection;
- topic ID and topic profile validation;
- arXiv ID normalization and candidate deduplication;
- atomic artifact updates and manual AUTO block preservation;
- deterministic SOTA IDs, sorting, grouping, and rendering;
- explicit download/source failure reporting.

### Tests To Replace

- fixed staged-reader call order;
- fixed prompt schemas for summary/method/experiments/topic relation;
- flat `PaperReadingPackage` round trips;
- survey synthesis from all reading packages in one prompt;
- parser section/formula/table completeness metrics;
- topic update as a fixed survey-then-SOTA sequence.

### New V2 Test Layers

1. Runtime unit tests with a scripted fake provider.
2. Tool contract and error-semantics tests.
3. Checkpoint/recovery/no-progress tests.
4. Evidence immutability and resolution tests.
5. Completion-policy defect and retry tests.
6. PDF text/image locality tests.
7. TeX candidate-span and sandbox-safety tests.
8. Patch validation and canonical state materialization tests.
9. Real-paper evaluation outside the default fast unit-test suite.

## 14. Documentation

| Path | Disposition | V2 action |
|---|---|---|
| `docs/architecture/v2-harness-design.md` | authoritative V2 design | Review before implementation and update through explicit design decisions. |
| `docs/architecture/v2-migration-inventory.md` | authoritative migration map | Keep synchronized with retirement commits. |
| `docs/superpowers/specs/*` | `LEGACY_BASELINE` | Freeze. They document historical decisions but are not V2 authority. Archive or delete after the relevant legacy code is retired. |
| `docs/superpowers/plans/*` | `RETIRE` later | Historical implementation plans add noise once V2 replaces their code. Git history remains the archive. |
| `docs/source_extraction_benchmark/*` | `FIXTURE` or user working material | Do not modify during the architecture commit. Review when parser experiments are retired. |

Do not update README to advertise unimplemented V2 behavior.

## 15. Dependencies

### Likely V2 Core Dependencies

- `PyYAML` for local configuration;
- `python-dotenv` for local secret loading;
- `PyMuPDF` for page inspection, text locality, and image rendering;
- one HTTP/model transport selected after the provider spike;
- the existing `arxiv` package initially, unless a narrower API client proves
  simpler.

### Legacy-Only Candidates After Migration

- `chromadb`;
- `aiosqlite`;
- `google-genai` unless a V2 Gemini provider is implemented;
- `pymupdf4llm` unless evaluation shows value as an optional text locator.

Do not add LangGraph, a vector database, an embedding framework, or a general
multi-agent framework before the minimal runtime is evaluated. The repository
should own its small agent and evidence contracts.

## 16. Data Migration

V2 writes topic-agnostic paper workspaces under `data/library/papers/` and
topic-specific projections under `data/topics/<topic_id>/paper_views/`. It does
not overwrite legacy flat reading packages.

Potential migration inputs:

- `papers/<paper_id>.json` legacy reading packages;
- `state/sota_records.jsonl`;
- `state/sota_setting_groups.json`;
- SQLite export data;
- manual text in stable Markdown artifacts.

Migration policy:

1. Raw source files may be reused after hashing and inventory.
2. Legacy generated claims and experiment records are unverified imports by
   default.
3. Imported records do not become canonical V2 evidence merely because they have
   page numbers.
4. V2 may re-read papers and supersede imported records.
5. Manual Markdown text is preserved; generated AUTO blocks are rematerialized
   from accepted V2 state.

## 17. Atomic Implementation Sequence

Recommended logical commits:

1. `docs`: approve V2 architecture and migration inventory.
2. `feat`: add V2 package, contracts, event store, and fake-provider runtime.
3. `feat`: add OpenAI-compatible tool-calling provider and capability probe.
4. `feat`: add PDF inspect/search/read/render tools.
5. `feat`: add evidence ledger, coverage, and `read-paper` completion policy.
6. `feat`: add V2 reading renderer and CLI.
7. `test`: add reviewed paper evaluation harness and baseline report.
8. `feat`: add minimal TeX table evidence tools.
9. `feat`: add `refine-topic`, topic search/download tools, and `survey-topic`.
10. `feat`: add domain and experiment patch validation.
11. `feat`: add `track-topic` and scheduling boundary.
12. `refactor`: switch default CLI and README after acceptance.
13. `refactor`: retire legacy components in dependency order.

Each commit must pass the tests available for its layer. Parser cleanup and legacy
deletion must not be mixed with new runtime features.

## 18. Retirement Order

After V2 acceptance, retire in this order:

1. legacy source benchmark parsers after their useful safety code and fixtures are
   ported;
2. staged reader and flat reading package after `read-paper` is default;
3. survey ingest/synthesis/update orchestration after `survey-topic` is default;
4. legacy SOTA CLI after patch-based SOTA is default;
5. global pipeline, contribution analyzer, ChromaDB, and SQLite exporter after any
   required data export;
6. onboarding and old CLI branches;
7. obsolete plans/specs and legacy-only dependencies.

Before each retirement commit, use import search and command tests to demonstrate
that no active V2 path depends on the target.

## 19. First Implementation Boundary

The first code milestone ends at a validated single-paper reader. It includes:

- agent runtime;
- one provider;
- PDF tools;
- evidence ledger;
- coverage and completion policy;
- reading JSON/Markdown;
- evaluation on a small reviewed corpus.

It explicitly excludes:

- topic discovery orchestration;
- survey synthesis;
- SOTA state mutation;
- citation graph expansion;
- TeX tools unless the PDF-only evaluation cannot resolve selected table cases;
- multi-agent execution;
- legacy deletion.

This boundary tests the central hypothesis before the repository commits to the
full migration.
