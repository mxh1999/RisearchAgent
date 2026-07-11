# RisearchAgent V2 Research Harness Design

Date: 2026-07-11

Status: Proposed architecture baseline. Implementation must not begin until the
decisions and acceptance gates in this document are reviewed.

## 1. Executive Decision

RisearchAgent V2 will be a research-agent harness, not a fixed paper-processing
pipeline.

The system will use a deterministic outer shell for safety, persistence, and
validation, while an LLM-controlled inner loop decides which research action to
take next. PDF is the default semantic source. TeX source is an optional precision
tool for resolving table evidence, not a required ingest format and not the source
of a universal PaperIR.

The implementation will be built as a new top-level `risearch/` package. The new
package must not import the current `src/` package. Existing modules may be ported
only after their assumptions and tests have been reviewed. The old implementation
remains available as a legacy baseline until V2 passes the evaluation gates.

The central design rule is:

> Reuse evidence, fixtures, and narrow utilities. Do not reuse legacy control-flow
> assumptions.

## 2. Product Goal

The product center is interactive research work:

- refine an unclear research direction;
- discover and prioritize relevant papers;
- read individual papers deeply and critically;
- answer paper- and topic-level questions with inspectable evidence;
- identify core, baseline, adjacent, and collision papers;
- maintain auditable experiment records and SOTA views;
- track new papers by reusing the same research capabilities.

Background tracking is a scheduled invocation of the same skills. It is not a
separate semantic pipeline.

## 3. Problems V2 Must Correct

The current implementation encodes a fixed sequence of LLM calls and passes a
truncated copy of the same paper text to each stage. Downstream survey and SOTA
modules are coupled to the resulting `PaperReadingPackage`. The LLM interface only
supports single-prompt text generation and JSON generation; it does not expose
tool calls, multimodal inputs, persistent conversation state, or explicit provider
capabilities.

The parser experiments have also accumulated responsibilities that belong to a
research agent: deciding section semantics, reconstructing tables, choosing useful
evidence, and building a complete intermediate representation before any task is
known. This makes parser quality a blocking dependency for all downstream work.

V2 must correct these architectural properties rather than add more repair rules.

## 4. Design Principles

1. **LLM-controlled research, deterministic infrastructure.**
   The model chooses research actions. Code owns safety, persistence, validation,
   deterministic transformations, and canonical state.

2. **Evidence-first, not parser-first.**
   Conclusions and records point to source evidence. A universal normalized paper
   representation is not required.

3. **Task-scoped reading.**
   The agent reads enough of a paper to satisfy an explicit goal and completion
   rubric. It may inspect additional material when evidence is weak.

4. **PDF-first, TeX-on-demand.**
   PDF preserves the published visual artifact. Raw TeX is consulted when a table
   or formula cannot be interpreted confidently from the PDF.

5. **Capabilities over provider names.**
   A provider dialect does not imply tool calling, native PDF input, vision,
   structured output, caching, or a particular context length.

6. **Canonical state is protected.**
   The agent proposes typed changes. Validators apply accepted changes. The model
   does not directly rewrite canonical topic or SOTA state.

7. **Stable human artifacts, append-only audit data.**
   Markdown files remain stable views. Evidence, patches, and run events retain an
   audit trail.

8. **Single-agent first.**
   Multi-agent execution is an optimization for later topic-scale work, not an MVP
   requirement.

9. **Evaluation before deletion.**
   Legacy code is removed only after V2 wins on a representative real-paper set.

## 5. Terminology

### Harness

The runtime that gives an LLM messages, tools, state, budgets, checkpoints,
termination rules, and observability. It does not encode a domain-specific order
of research actions.

### Skill

A versioned research policy consisting of instructions, an allowed tool set,
output contracts, and a completion rubric. Initial skills are `refine-topic`,
`read-paper`, `survey-topic`, and `track-topic`.

### Tool

A narrow, typed capability exposed to the agent. Tools inspect sources, search,
record evidence, or propose changes. A tool should not hide an entire fixed
workflow behind one call.

### Run State

Mutable state for one agent run: messages, tool results, checklist, budget,
temporary artifacts, and proposed output.

### Canonical State

Reviewed topic knowledge: paper registry, evidence, experiment records, domain
state, accepted patches, and rendered views.

### Evidence

A source-backed unit that can be inspected independently of an LLM conclusion.
Evidence is immutable after creation; corrections create a replacement record.

## 6. System Architecture

```text
User Goal / Schedule / Topic State
                 |
                 v
        +------------------+
        |  Research Skill  |
        +------------------+
                 |
                 v
        +------------------+
        | Agent Run Loop   |<--------------------+
        | plan/tool/verify |                     |
        +------------------+                     |
           |       |       |                     |
           v       v       v                     |
       Search    PDF     TeX/Table                |
       Tools     Tools     Tools                  |
           |       |       |                     |
           +-------+-------+---------------------+
                           |
                           v
                  Evidence Ledger
                           |
                           v
                 Proposed Typed Patches
                           |
                           v
             Validators / Conflict Detection
                           |
                           v
          Canonical State and Markdown Views
```

The runtime and tools are reusable across skills. Skills may impose output and
completion requirements but must not prescribe a fixed order of tool calls.

## 7. Package Boundary

The target package layout is:

```text
risearch/
  __init__.py
  __main__.py
  agent/
    runtime.py
    messages.py
    tools.py
    checkpoint.py
    completion.py
    events.py
  providers/
    base.py
    capabilities.py
    openai_compatible.py
  tools/
    arxiv.py
    citations.py
    pdf.py
    tex.py
    evidence.py
    workspace.py
  skills/
    base.py
    refine_topic.py
    read_paper.py
    survey_topic.py
    track_topic.py
  domain/
    topic.py
    paper.py
    evidence.py
    experiments.py
    patches.py
    domain_state.py
  storage/
    workspace.py
    jsonl.py
    atomic.py
  render/
    reading.py
    survey.py
    sota.py
```

V2 code must not import `src.*`. A transitional command may invoke V2 as a
subprocess or exchange versioned files, but no new domain model should inherit
from or wrap a legacy model directly.

This constraint prevents a gradual reintroduction of `PaperReadingPackage` and
fixed-stage assumptions into the new core.

## 8. Agent Runtime

### 8.1 Run Contract

An `AgentRun` contains:

- `run_id`;
- user goal;
- selected skill and skill version;
- model and provider configuration;
- model capability snapshot;
- allowed tools;
- message history;
- working checklist;
- token, tool-call, time, and monetary budgets when available;
- checkpoint pointer;
- status;
- proposed final output;
- typed blocker when incomplete.

Run statuses are:

```text
created
running
waiting_for_user
completed
failed
budget_exhausted
cancelled
```

`budget_exhausted` is not reported as successful completion.

### 8.2 Core Loop

The runtime performs the following loop:

1. Assemble current instructions, compacted history, checklist, and relevant
   workspace state.
2. Ask the provider for the next agent turn with allowed tool schemas.
3. If the turn contains tool calls, validate and execute them, persist results,
   and continue.
4. If the turn requests completion, run the skill completion policy.
5. If completion fails, return structured defects to the agent and continue while
   budget remains.
6. If the model returns neither tool calls nor a valid completion request, run one
   recovery turn; repeated no-progress turns terminate with a typed blocker.
7. Checkpoint after every model turn and every completed tool call.

The runtime does not contain nodes named `summary`, `method`, `experiments`, or
similar paper semantics.

### 8.3 Completion Is A Tool

Each skill exposes a typed `finish` tool. Calling it submits a candidate result;
it does not unconditionally end the run.

Completion validation has two layers:

- mechanical validation: schema, IDs, resolvable evidence, allowed values, and
  artifact consistency;
- semantic validation: skill-specific coverage and evidence support, performed by
  a bounded verifier model when deterministic checks are insufficient.

Validation returns either `accepted` or a list of actionable defects. The agent
may address defects until its budget is exhausted. A verifier cannot silently
repair the submitted result.

### 8.4 Context Management

The runtime keeps recent messages and active tool results in model context. Older
work is compacted into a run summary and offloaded to files.

Compacted summaries are navigation aids, not evidence. Any final claim must point
to an immutable `EvidenceRef`, not to a context summary.

Large tool results are stored as artifacts. The model receives a bounded preview,
metadata, and a handle that can be read in smaller ranges.

### 8.5 Budgets And No-Progress Detection

The MVP must support maximum model turns, tool calls, wall time, and input/output
tokens when the provider reports them. Monetary limits are added when reliable
price metadata exists.

The runtime detects repeated identical tool calls, repeated verifier defects, and
consecutive turns with no state change. It terminates with an explicit blocker
instead of looping indefinitely.

### 8.6 Multi-Agent Boundary

The first implementation has one agent per run. Later, `survey-topic` may dispatch
isolated paper-reading runs in parallel. A parent run receives only structured
child outputs and artifact handles, not full child histories.

## 9. Provider Interface

### 9.1 Required Abstraction

The provider interface exchanges typed messages and content parts rather than a
single prompt string.

Conceptual types:

```text
AgentMessage
- role
- content_parts[]
- tool_calls[]
- tool_results[]

ContentPart
- text | image | input_file | artifact_ref

AgentTurn
- content_parts[]
- tool_calls[]
- stop_reason
- usage
```

The interface must preserve provider tool-call IDs and raw stop reasons so that a
run can recover from interrupted calls.

### 9.2 Capability Model

Capabilities are explicit data:

```text
supports_tool_calling
supports_parallel_tool_calls
supports_structured_output
supports_image_input
supports_native_pdf_input
supports_file_upload
supports_prompt_cache
supports_reasoning_controls
context_window
max_output_tokens
```

Static configuration may declare capabilities, but a provider smoke test must be
able to verify critical ones. The runtime must fail closed when a requested mode
is unsupported. It must never silently replace visual PDF reading with extracted
text while claiming equivalent behavior.

### 9.3 Initial Provider Scope

The V2 MVP targets one OpenAI-compatible tool-calling provider because it matches
the active project configuration. Claude- and Gemini-compatible transports remain
legacy until the runtime contract is stable.

Native PDF input is optional. The portable baseline is selected page images plus
page-aware text tools. This avoids assuming that a third-party OpenAI-compatible
endpoint implements official file or Responses APIs.

### 9.4 Structured Outputs

Structured output is used for tool arguments, completion submissions, verifier
results, and patches. It must not be used to force every reasoning turn into a
large fixed paper schema.

## 10. Skill Contract

A skill definition contains:

```text
name
version
instructions
allowed_tools
input_schema
output_schema
completion_policy
default_budgets
```

Skills are domain policies over a shared runtime. They may recommend strategies,
but they must leave action order to the agent.

### 10.1 `refine-topic`

The skill turns a vague direction, notes, examples, and user feedback into a
versioned topic profile. It may run pilot searches to test whether proposed query
families retrieve the intended field.

It must expose meaningful framing choices to the user rather than silently
collapsing an ambiguous direction into one query. Background runs cannot use this
skill when a material user decision is unresolved.

### 10.2 `read-paper`

Inputs:

- paper identity and local or remote source;
- optional topic profile;
- optional focused research questions;
- reading mode: `screen`, `standard`, or `deep`.

Required output areas for `standard` and `deep` modes:

- identity and source inventory;
- one-sentence takeaway;
- problem and motivation;
- method decomposition;
- primary claims;
- primary experiment settings and results;
- limitations and critical assessment;
- unresolved ambiguities;
- coverage report;
- topic relation when a topic is provided.

Each primary claim and experiment record requires evidence. The skill does not
require a fixed order for collecting these fields.

### 10.3 `survey-topic`

The skill iteratively searches, screens, expands citations, reads selected papers,
and proposes domain changes. It retrieves existing topic state rather than passing
all paper readings into one prompt.

Expected outputs include:

- topic-paper membership and role patches;
- taxonomy patches;
- benchmark and terminology patches;
- collision and positioning analysis;
- missing-evidence and next-reading queues;
- survey view patches.

### 10.4 `track-topic`

The skill starts from an existing `DomainState`, searches a bounded time range,
reads only promising new papers, and emits a `DomainDelta`. It must distinguish
"no relevant change" from a failed or incomplete run.

## 11. Tool Design

Tools should be small enough that the agent can choose and combine them. Every tool
returns typed status, bounded content, provenance, warnings, and an artifact handle
when the result is large.

### 11.1 Source And Discovery Tools

Initial tools:

```text
search_arxiv
get_arxiv_metadata
download_paper_pdf
download_arxiv_source
find_citing_papers
find_references
```

Search and citation tools return candidates. They do not automatically add papers
to canonical topic state.

### 11.2 PDF Tools

```text
inspect_pdf
search_pdf_text
read_pdf_pages
render_pdf_pages
read_pdf_metadata
```

`inspect_pdf` returns page count, available text layer, file size, and warnings.

`search_pdf_text` is a locator. Results contain page number and nearby text. It is
not a semantic section parser.

`read_pdf_pages` returns page-aware extracted text for a bounded range. It supports
navigation and quotable prose evidence.

`render_pdf_pages` returns page images with configurable detail. Visual inspection
is required for dense tables, plots, diagrams, and layout-dependent claims unless
equivalent TeX evidence is available.

When native provider PDF input is supported, the skill may use it for an initial
whole-document overview. Targeted tools remain necessary for repeatable evidence
locality and cost control.

### 11.3 TeX Table Evidence Tools

```text
ensure_tex_source
list_source_files
search_tex_source
read_tex_source
find_table_candidates
render_table_candidate
```

The first implementation may omit `render_table_candidate`.

`find_table_candidates` performs conservative source-span discovery. It returns
raw LaTeX, file and line ranges, nearby captions/labels, and uncertainty flags. It
does not normalize cells or claim semantic correctness.

The agent may read included files and macro definitions when needed. Missing or
unparseable TeX is a recoverable condition; PDF reading continues.

TeX source is untrusted input. Archive extraction must reject path traversal.
Compilation, if implemented, runs without network access, without shell escape,
inside a resource-limited sandbox.

### 11.4 Evidence And State Tools

```text
search_paper_library
read_paper_reading
read_domain_state
search_topic_evidence
record_evidence
list_evidence
read_evidence
record_coverage
propose_reading
propose_domain_patch
propose_experiment_records
inspect_patch_validation
request_user_input
```

These tools are the only mutation path from an agent run toward canonical state.
The model does not receive unrestricted file-write access to topic state in the
MVP.

`request_user_input` suspends an interactive run with a typed question and reason.
It is not available to background runs; those runs terminate with
`waiting_for_user` and a visible blocker instead of guessing.

## 12. Evidence Model

### 12.1 EvidenceRef

An evidence record has this conceptual shape:

```json
{
  "evidence_id": "ev_<stable_hash>",
  "paper_id": "2507.04047",
  "source_type": "pdf",
  "source_id": "paper.pdf",
  "locator": {
    "page_start": 6,
    "page_end": 6,
    "table": "Table 3"
  },
  "raw_excerpt": "...",
  "visual_artifact": "runs/<run_id>/artifacts/page-006.png",
  "extraction_method": "text_layer",
  "verification_status": "exact_source_match",
  "content_hash": "sha256:...",
  "created_by_run": "run_...",
  "confidence": "high",
  "warnings": []
}
```

For TeX evidence, the locator contains source file, line range, label, and optional
PDF page/table linkage.

Evidence IDs are stable hashes over source identity, source content hash, locator,
and raw excerpt. Evidence is not rewritten in place.

`record_evidence` does not trust a model-supplied quote. It reopens the referenced
source and either stores an exact source span, records a normalized/fuzzy match
with a warning, or rejects the record. For visual-only evidence, the page image is
canonical and any model transcription is stored separately with
`verification_status = "visual_interpretation"`.

### 12.2 Claim And Reading Records

A claim contains normalized agent-authored text plus one or more evidence IDs. A
reading package is a view over claims, method notes, experiments, critique, and
coverage. It does not embed the entire paper or duplicate raw page text.

### 12.3 Experiment Records

An experiment record distinguishes:

- paper method vs paper-reported baseline;
- official, reproduced, or unclear result source;
- main task, auxiliary, ablation, or diagnostic result kind;
- benchmark, dataset, task, split, protocol, sensors, training data, and evaluator;
- metric, direction, value, and units;
- evidence IDs;
- comparability status and unresolved axes.

A deterministic validator checks that numeric values and method names are present
in the cited raw evidence. Semantic header-to-cell mapping may require a verifier
model or human review.

## 13. Coverage And Completion For Paper Reading

The reader maintains an explicit coverage ledger rather than pretending that a
single prompt read the whole paper.

Coverage entries record:

- source area or page range;
- reason for inspection;
- status: `inspected`, `skipped_with_reason`, or `unresolved`;
- evidence created;
- remaining questions.

The `read-paper` completion policy requires:

1. all required output areas are present;
2. every primary claim has resolvable evidence;
3. every primary experiment record has evidence with a complete header path;
4. method and experiment evidence comes from relevant paper regions;
5. limitations include author-stated limitations when available and clearly mark
   agent inference as inference;
6. unresolved table or setting ambiguity is reported instead of guessed;
7. the coverage ledger explains uninspected material that could affect the goal.

The policy does not require reading every appendix page for every task. It requires
the agent to justify task-relevant coverage.

## 14. State And Artifact Layout

Paper-local evidence is topic-agnostic and lives in a reusable library. A topic
stores projections and accepted domain state rather than another copy of the
paper.

```text
data/
  library/
    paper_registry.jsonl
    papers/
      <paper_id>/
        source.json
        evidence.jsonl
        reading.json
        reading.md
        coverage.json
  runs/
    <run_id>/
      run.json
      events.jsonl
      result.json
      artifacts/
  topics/
    <topic_id>/
      topic.yaml
      survey.md
      papers.md
      positioning.md
      references.md
      sota.md
      paper_views/
        <paper_id>.json
      state/
        topic_history.jsonl
        topic_papers.jsonl
        experiment_records.jsonl
        setting_groups.json
        domain_state.json
        domain_patches.jsonl
```

`source.json`, evidence, and the base reading are reusable across topics. A
`TopicPaperView` records topic relevance, taxonomy, collision, and topic-specific
experiment interpretation by referencing global evidence IDs.

The library registry owns paper identity and source hashes. `topic_papers.jsonl`
owns topic membership, role, review status, and a pointer to the corresponding
`TopicPaperView`. A paper can therefore participate in several topics without
duplicating its source evidence.

Legacy flat files such as `data/topics/<topic_id>/papers/<paper_id>.json` may
coexist during migration. V2 never overwrites them.

Human-facing Markdown remains a deterministic view over accepted state. Existing
manual text outside managed blocks is preserved.

Run events contain references to large tool artifacts rather than embedding them.
Secrets, API keys, and full provider authorization headers are never written to
events.

## 15. Canonical State Mutation

State updates follow:

```text
Agent proposal
  -> schema validation
  -> evidence resolution
  -> deterministic conflict checks
  -> optional semantic verifier
  -> accepted | rejected | needs_review
  -> append patch event
  -> materialize canonical state
  -> render Markdown views
```

Rejected patches remain auditable but do not alter canonical state. `needs_review`
patches are visible and excluded from automatic leaderboards by default.

## 16. SOTA Semantics

SOTA tracking remains structured-data-first. The agent extracts candidate records
and proposes semantic setting groups. Code performs deterministic IDs, type checks,
sorting, duplicate detection, and rendering.

Automatic semantic merges require high confidence and matching comparison axes.
Different split, sensor, protocol, task definition, training regime, evaluator, or
result provenance remains separate unless evidence proves equivalence.

Paper-reported baselines are preserved but are not treated as verified global SOTA.
The main leaderboard may exclude auxiliary, ablation, diagnostic, low-confidence,
and incomparable records while retaining them in the audit store.

## 17. Failure Semantics

Tools return typed errors such as:

```text
source_unavailable
network_error
unsupported_capability
invalid_source
parse_or_render_error
evidence_not_found
ambiguous_table
rate_limited
```

The agent may recover by choosing another tool or source. Tool failures are not
converted to empty success values.

A run result always distinguishes:

- completed with validated output;
- completed with review-required findings;
- incomplete due to missing evidence;
- failed due to runtime/provider/tool error;
- stopped by budget or user action.

## 18. Security Boundary

- API keys remain in environment variables or approved secret stores.
- Downloaded archives are extracted with path traversal protection.
- TeX projects are never trusted or compiled on the host without sandboxing.
- Source URLs are validated before download.
- Canonical state writes use atomic replacement or append-only files.
- Agent tool arguments are schema-validated.
- Tool output is treated as untrusted content and clearly delimited in prompts.
- The MVP does not expose a general shell tool to the paper-reading agent.

## 19. CLI Direction

V2 receives a separate entry point:

```bash
python -m risearch paper read --pdf paper.pdf --paper-id 2507.04047
python -m risearch topic refine "research direction"
python -m risearch topic survey --topic data/topics/<topic_id>/topic.yaml
python -m risearch topic track --topic data/topics/<topic_id>/topic.yaml
python -m risearch run inspect <run_id>
```

The current `python run.py ...` interface is frozen during the reader MVP. After
V2 migration, `run.py` may become a compatibility shim with explicit deprecation
messages.

## 20. Evaluation Plan And Acceptance Gates

### 20.1 Corpus

Create a manually reviewed set of at least 8 papers covering:

- clean single-column ML;
- two-column CV;
- embodied AI or robotics;
- table-heavy benchmark paper;
- appendix-heavy paper;
- equation-heavy paper;
- survey paper;
- multi-file TeX source with table includes.

The existing VLFM, MTU3D, PDF parser smoke papers, and TeX samples are initial
candidates, not a sufficient final corpus.

### 20.2 Human Reference

For each paper, annotate a bounded rubric:

- primary claims and supporting pages;
- method components;
- primary experiment tables;
- selected exact experiment records and header paths;
- important limitations;
- known ambiguities.

The reference set should prioritize correctness over exhaustive transcription of
every baseline row.

### 20.3 Metrics

Required metrics:

- evidence locator validity;
- evidence entailment precision;
- required-area coverage;
- primary experiment precision and recall;
- exact numeric value accuracy;
- header-to-cell mapping accuracy;
- result-role classification accuracy;
- ambiguity disclosure recall;
- tool calls, input/output tokens, latency, and provider failures;
- completion validity and premature-finish rate.

### 20.4 Initial Gates

Before the legacy reader can be retired, V2 should achieve on the reviewed corpus:

- 100% mechanically resolvable evidence references;
- at least 95% evidence entailment precision;
- at least 95% primary experiment precision;
- at least 90% primary experiment recall;
- at least 95% exact numeric value accuracy;
- no silent acceptance of a known ambiguous header-to-cell mapping;
- lower premature-finish rate than the legacy reader;
- no critical regression in required-area coverage.

Cost and latency are recorded during the quality-first MVP. Operational budgets
are set after the first quality baseline rather than optimized prematurely.

## 21. Migration Strategy

### Phase 0: Architecture And Corpus

- approve this design and the migration inventory;
- define the reviewed paper corpus and rubric;
- freeze new features in the legacy reader/parser path.

### Phase 1: Runtime Skeleton

- add the independent `risearch/` package;
- implement provider-neutral messages, tool registry, event log, checkpoint, and
  fake-provider tests;
- implement one OpenAI-compatible tool-calling provider;
- add capability smoke tests.

### Phase 2: PDF Reader MVP

- implement PDF inspect/search/read/render tools;
- implement evidence and coverage storage;
- implement `read-paper` and its completion policy;
- render V2 reading JSON and Markdown;
- run the first legacy-vs-V2 evaluation.

### Phase 3: TeX Table Evidence

- implement source download, safe extraction, file search, and conservative table
  span discovery;
- allow the reader to invoke TeX tools on demand;
- evaluate complex table mappings.

### Phase 4: Topic Research

- implement interactive `refine-topic` and versioned topic profiles;
- port arXiv discovery and download capabilities as tools;
- implement `survey-topic` with retrieval over accepted paper evidence;
- add domain patches and stable survey views.

### Phase 5: SOTA And Tracking

- port and strengthen structured experiment records and renderers;
- add patch validation and review-required states;
- implement `track-topic` and scheduled invocation boundaries.

### Phase 6: Legacy Retirement

- replace the default CLI and README;
- migrate required topic artifacts;
- delete legacy parser, staged reader, global pipeline, ChromaDB, and obsolete
  specifications in separate reviewable commits.

## 22. Explicitly Rejected Designs

### Universal Non-LLM PaperIR As A Required Gateway

Rejected because it makes parser completeness a prerequisite for every downstream
task and duplicates semantic decisions that capable multimodal agents can make in
task context.

### Fixed LLM Stage Graph

Rejected because the paper, goal, evidence quality, and available sources determine
the appropriate reading sequence.

### Whole-Paper Prompt Repeated For Every Output Field

Rejected because it is expensive, loses targeted evidence locality, and truncates
long papers without an explicit coverage decision.

### LLM Directly Rewriting Canonical State

Rejected because it weakens auditability, deterministic conflict handling, and
recovery from malformed output.

### Multi-Agent MVP

Rejected because it adds coordination, context, cost, and debugging complexity
before the single-agent reading contract is validated.

### TeX As The Only Reading Source

Rejected because source is not always available, TeX projects are irregular, and
the published PDF is the authoritative visual artifact.

## 23. Design Influences

- PaperQA2: model-driven tool ordering, iterative evidence gathering, and
  self-correction are more important than a fixed RAG sequence.
- OpenScholar: retrieval-augmented self-feedback is preferable to one-shot survey
  synthesis.
- STORM and Co-STORM: multi-perspective questioning and human steering are useful
  topic-research policies.
- Open Deep Research: research, compression, and report generation should be
  separate model responsibilities over shared run state.
- DeerFlow: skills, tools, workspace, goals, compaction, and durable runs are
  harness concerns.
- PaperBench: file access alone does not prevent premature completion; explicit
  completion conditions and coverage tracking are necessary.

These projects are influences, not dependencies. V2 should begin with a small
runtime whose contracts are owned by this repository.

## 24. Deferred Implementation Choices

The following choices require a focused spike after architecture approval:

- plain dataclasses plus manual validation versus a schema library;
- direct provider HTTP implementation versus a thin third-party model SDK;
- exact page-image transport supported by the configured OpenAI-compatible
  endpoint;
- local PDF image resolution and caching policy;
- citation graph provider and rate-limit policy;
- whether semantic completion verification uses the reader model or a separate
  verifier model.

These choices may change implementation details but must not change the control,
evidence, or state boundaries defined above.
