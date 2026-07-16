# Paper Reader Agent Design

Date: 2026-05-13

## Goal

Build a research copilot for paper reading, field survey, SOTA tracking, and long-term research knowledge maintenance.

The product should not be only an automated arXiv pipeline. The main user experience is interactive research work:

- refine an unclear or emerging research direction into a stable topic profile;
- survey a field when the user is unfamiliar with it;
- deeply read individual papers with evidence-backed notes;
- identify core, baseline, recent, adjacent, and collision papers;
- maintain SOTA records in a structured and auditable form;
- reuse the same reading and survey artifacts for background tracking.

Automatic tracking is a backend workflow that reuses the same topic, reading, and SOTA structures.

## Current Problems

The existing repository already has useful low-level components: arXiv crawling, relevance filtering, PDF extraction, LLM reading, ChromaDB knowledge storage, and Markdown SOTA output. The main issue is product and architecture shape.

### Deep Reading Is Too Shallow

`DeepReader` currently extracts a few high-level fields from introduction, method, experiments, and context sections. This is closer to field extraction than paper reading.

Missing capabilities:

- section-level understanding;
- evidence citation with page or section location;
- claim extraction;
- method module breakdown;
- experiment setting normalization;
- critical assessment;
- topic-specific relation and collision analysis;
- follow-up questions and reusable reading memory.

### Survey Is Not A Real Workflow

The onboarding module configures research interests, but it does not implement survey behavior. The desired survey behavior is closer to the thesis direction brainstorming process:

- start from an unclear research direction;
- decompose concepts;
- propose possible framings;
- challenge weak framings;
- identify anchor papers and collision papers;
- build a taxonomy and reading plan;
- update stable artifacts such as `survey.md`, `papers.md`, `references.md`, and `positioning.md`.

### Topic Definition Is Too Query-Centric

Emerging and cross-disciplinary topics are hard to capture with one arXiv query. A topic should be a research intent object, not just a search string.

The topic profile should include:

- natural-language intent;
- positive examples;
- negative examples;
- concept axes;
- anchor papers;
- collision papers;
- benchmark hints;
- query families;
- user feedback history.

### SOTA Tracking Is Not Auditable Enough

The current SOTA tracker lets the LLM directly update Markdown leaderboards. This is fragile because benchmark, split, metric, setting, official vs reproduced results, and source evidence can be mixed.

SOTA should be structured-data-first:

- store individual result records in JSONL or SQLite;
- preserve evidence and source;
- detect conflicts programmatically where possible;
- use LLM only for explanation and normalization assistance;
- render Markdown as a view, not the source of truth.

## Recommended Architecture

Move from a linear pipeline to workflow-centered architecture:

```text
User Intent
  -> Topic Refinement
  -> Search / Collection
  -> Paper Reading
  -> Survey Synthesis
  -> SOTA Extraction
  -> Knowledge / Artifacts
```

Core modules:

- `TopicRefiner`: turns vague user intent, notes, anchors, and exclusions into `topic.yaml`.
- `PaperCollector`: searches and expands candidate papers using query families, anchors, metadata, and feedback.
- `PaperReader`: performs staged paper reading and writes reading packages.
- `SurveySynthesizer`: classifies papers, builds taxonomy, analyzes gaps/collisions, and updates survey artifacts.
- `SOTAStore`: stores structured experiment records and renders leaderboard views.
- `ArtifactManager`: updates stable topic files while preserving user edits.

## Artifact Layout

Use one stable directory per topic:

```text
data/topics/<topic_id>/
  topic.yaml
  survey.md
  papers.md
  references.md
  positioning.md
  sota.md
  papers/
    <paper_id>.reading.md
    <paper_id>.json
  state/
    papers.jsonl
    readings.jsonl
    sota_records.jsonl
    survey_events.jsonl
```

Default behavior is to update existing files. The agent should not create many timestamped full-document variants.

Markdown files can use auto-managed blocks:

```markdown
<!-- BEGIN AUTO:taxonomy -->
Auto-managed taxonomy content lives here.
<!-- END AUTO:taxonomy -->
```

Only auto blocks are rewritten. User-written text outside those blocks is preserved.

## CLI Design

First-version CLI:

```bash
python run.py survey refine "task-conditioned 3D utility learning for embodied navigation"
python run.py survey refine --from-note 2026-05-11_21-32-21_thesis_direction_brainstorm.md
python run.py survey run data/topics/decision_aware_3d_nav/topic.yaml
python run.py read 2506.12345 --topic data/topics/decision_aware_3d_nav/topic.yaml
python run.py track data/topics/decision_aware_3d_nav/topic.yaml
```

Meaning:

- `survey refine`: clarify and save a topic profile.
- `survey run`: collect, classify, read, and synthesize papers for a topic.
- `read`: deeply read one paper, optionally relative to a topic.
- `track`: periodically collect new papers and reuse read/survey/SOTA workflows.

Optional management commands:

```bash
python run.py topic list
python run.py topic show decision_aware_3d_nav
python run.py topic validate data/topics/decision_aware_3d_nav/topic.yaml
python run.py sota show data/topics/decision_aware_3d_nav/topic.yaml
python run.py sota verify data/topics/decision_aware_3d_nav/topic.yaml
```

## Topic Refinement Workflow

`survey refine` should follow the thesis brainstorming pattern:

1. Load user context from natural language, a note file, anchors, or existing project material.
2. Decompose the direction into concept axes.
3. Propose 2-3 framings and recommend the strongest one.
4. Ask the user to choose or revise the framing.
5. Define positive, negative, collision, and adjacent scope.
6. Generate query families instead of one query.
7. Run a pilot search when needed.
8. Use user feedback to update `topic.yaml`.
9. Update stable artifacts.

Example concept axes for the current thesis direction:

- upstream representation: object-centric 3D memory;
- spatial substrate: scene-level spatial memory, frontier, map;
- decision layer: task-conditioned utility over object/frontier/region/viewpoint;
- downstream validation: ObjectNav, OVON, GOAT;
- deployment axis: RGB-only as optional technical constraint.

Example topic profile fields:

```yaml
name: decision_aware_3d_understanding_for_navigation
description: >
  Study how 3D scene understanding and memory can be converted into
  task-conditioned navigation decisions.
concept_axes:
  - object_centric_3d_memory
  - scene_level_spatial_memory
  - task_conditioned_utility
  - open_goal_embodied_navigation
positive_scope:
  - papers that score objects, frontiers, regions, or viewpoints for navigation
  - papers that build 3D memory for embodied decision-making
negative_scope:
  - pure SLAM without semantic or task-conditioned decision-making
  - static 3D grounding without embodied action
anchor_papers:
  - MTU3D
  - MSGNav
  - D3D-VLP
collision_papers:
  - MSGNav
  - MTU3D
search_queries:
  - '"embodied navigation" "3D memory"'
  - '"open-vocabulary navigation" "scene graph"'
benchmark_hints:
  - GOAT-Bench
  - HM3D-OVON
open_questions:
  - What utility supervision is available beyond heuristic frontier scoring?
```

## PaperReader Workflow

The reader should be staged rather than one large prompt:

```text
PDF/Page Text
  -> Section Map
  -> Section Notes
  -> Claim Extraction
  -> Method Breakdown
  -> Experiment Extraction
  -> Topic Relation
  -> Report Rendering
```

Each stage should have an independent schema and be rerunnable.

Human-readable output:

```text
papers/<paper_id>.reading.md
```

Machine-readable output:

```text
papers/<paper_id>.json
```

The Markdown reading should include:

- metadata;
- one-sentence takeaway;
- problem;
- method breakdown;
- claims and evidence;
- experiments;
- relation to topic;
- critical assessment;
- follow-up questions.

The JSON reading should include:

- paper metadata;
- section map;
- section notes;
- claims with evidence;
- method modules;
- experiment records;
- topic relation;
- critique;
- follow-up papers or questions.

Every important claim should carry evidence when possible: page, section, table, and short quote.

## SurveySynthesizer Workflow

Input:

- `topic.yaml`;
- collected paper metadata;
- selected reading packages;
- user feedback;
- existing artifacts.

Stages:

1. Classify papers into `core`, `collision`, `baseline`, `recent`, `adjacent`, `irrelevant`.
2. Build or update taxonomy.
3. Build benchmark map.
4. Analyze gaps and collision risks.
5. Generate reading plan.
6. Update stable artifacts.

The most important output is not a generic related-work summary. It should answer:

- what has already been done;
- what overlaps strongly with the user's idea;
- what claims are no longer novel;
- what differentiation remains plausible;
- which papers must be read before making a research claim;
- which experiments are needed to defend the positioning.

## SOTAStore Workflow

Paper reading produces candidate experiment records:

```json
{
  "paper_id": "2506.12345",
  "paper_title": "MSGNav: Multi-modal 3D Scene Graph Navigation",
  "benchmark": "GOAT-Bench",
  "dataset": "HM3D",
  "task": "open-vocabulary lifelong navigation",
  "split": "val unseen",
  "goal_type": "category/language/image",
  "metric": "SPL",
  "value": 35.1,
  "higher_is_better": true,
  "method": "MSGNav",
  "method_role": "paper_method",
  "result_source": "reported_by_authors",
  "evidence": {
    "page": 8,
    "section": "Experiments",
    "table": "Table 1",
    "quote": "The paper reports GOAT-Bench results under the validation split."
  },
  "notes": "Check whether the reported setting is directly comparable to trained navigation policies."
}
```

Update flow:

```text
PaperReader.extract_experiments
  -> candidate SOTA records
  -> normalize benchmark / metric / setting names
  -> detect duplicate or conflict
  -> store records
  -> render sota.md
```

Conflict categories:

- same setting, same metric, same method, different value;
- different setting;
- reproduced vs official;
- paper-reported baseline;
- unclear.

The system should preserve both records when comparability is unclear.

## MVP Plan

### MVP-1: Topic Refinement And Stable Artifacts

Implement:

- `survey refine`;
- `--from-note`;
- topic directory creation;
- `topic.yaml`;
- stable Markdown artifacts;
- `survey_events.jsonl`.

Goal: solve topic ambiguity and query brittleness first.

### MVP-2: Staged PaperReader

Implement:

- page-aware PDF extraction;
- staged reading schemas;
- reading Markdown and JSON outputs;
- topic relation analysis.

Goal: make single-paper reading reliable enough for survey and SOTA.

### MVP-3: Survey Run And Artifact Updating

Implement:

- query family generation from `topic.yaml`;
- paper collection and classification;
- core/collision paper reading;
- taxonomy and positioning updates;
- auto-block Markdown updates.

Goal: reproduce the thesis-direction brainstorming workflow in a reusable survey command.

### MVP-4: Structured SOTA

Implement:

- `state/sota_records.jsonl`;
- SOTA record normalization;
- conflict detection;
- Markdown rendering;
- `sota show` and `sota verify`.

Goal: make leaderboard updates auditable.

## Design Decisions

- Interactive read/survey is the product center; tracking is a backend workflow.
- Topic is a research intent profile, not a single search query.
- Paper reading is staged and evidence-backed.
- Survey updates existing artifacts by default.
- Markdown is for human reading; JSONL/JSON is source-of-truth state.
- SOTA is structured-data-first, Markdown-second.

## Open Questions

- Whether the first implementation should support only arXiv papers or also local PDFs from the start.
- Whether citation expansion should use external APIs in MVP-1 or wait until MVP-3.
- Whether the first structured SOTA store should be JSONL-only or also mirrored into SQLite.
- How much of the interactive refinement should be single-turn generation versus multi-turn confirmation.
