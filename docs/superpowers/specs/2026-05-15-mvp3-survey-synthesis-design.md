# MVP-3 Survey Synthesis Design

## Goal

MVP-3 turns a refined topic and a set of staged reading packages into stable survey artifacts. It implements the reusable version of the thesis-direction brainstorming workflow: read several papers, organize the field, classify related work, identify collisions, and update Markdown files without overwriting user notes.

## Scope

MVP-3 implements offline synthesis first:

- input: `topic.yaml` plus staged reading package JSON files;
- output: updated `survey.md`, `papers.md`, `positioning.md`, `references.md`;
- update mode: auto-block replacement only;
- audit trail: append a `synthesize` event to `state/survey_events.jsonl`.

MVP-3 does not implement paper search, citation expansion, periodic tracking, or structured SOTA storage. Those remain later milestones. The CLI and data boundaries should not prevent those extensions, but this version must be useful and testable without network search.

## User Workflow

The intended workflow is:

```bash
python run.py survey refine --from-note notes/thesis_direction.md

python run.py read --staged \
  --pdf data/pdfs/mvp3-smoke/mtu3d.pdf \
  --paper-id mtu3d \
  --title "Move to Understand a 3D Scene" \
  --topic data/topics/<topic_id>/topic.yaml

python run.py survey synthesize \
  --topic data/topics/<topic_id>/topic.yaml
```

When `--topic` is provided to `read --staged`, reading packages are written under `<topic_dir>/papers/`. `survey synthesize` defaults to reading `*.json` from that directory. A `--readings-dir` option may override the source directory for tests or ad-hoc runs.

## Local Test Corpus

The current local test corpus lives under `data/pdfs/mvp3-smoke/`, which is ignored by git. It contains public PDFs for:

- MTU3D;
- MSGNav;
- D3D-VLP;
- VGGT;
- IGGT;
- EmbodiedScan;
- VLFM;
- OpenFMNav;
- GOAT-Bench;
- HM3D-OVON;
- SG3D.

`data/pdfs/mvp3-smoke/manifest.json` records source URLs. M3Fusion is listed in the topic profile, but no public PDF was found from the DOI page, so it is not part of the local smoke corpus unless the user provides a copy.

## Architecture

MVP-3 adds a small survey synthesis layer on top of MVP-1 and MVP-2:

```text
topic.yaml
  + papers/*.json
  -> reading loader
  -> survey synthesizer
  -> survey renderer
  -> TopicArtifactManager.update_auto_block(...)
```

The main units are:

- `src/survey/reading_loader.py`: loads and validates `PaperReadingPackage` JSON files from a directory.
- `src/survey/synthesis_models.py`: dataclasses for the structured survey result.
- `src/survey/synthesizer.py`: builds the synthesis prompt, calls an LLM, validates and normalizes the response.
- `src/survey/survey_renderer.py`: renders structured synthesis into Markdown blocks.
- `src/survey/cli.py`: adds `survey synthesize`.

The synthesis layer should consume the existing `TopicProfile` and `PaperReadingPackage` models. It should not duplicate staged reading logic.

## Synthesis Schema

The LLM returns one object with these sections:

- `taxonomy`: a list of method groups, each with `name`, `description`, `paper_ids`, and `key_distinction`.
- `paper_map`: a list of paper classifications, each with `paper_id`, `title`, `role`, `rationale`, and `evidence`.
- `positioning`: concise statements for `thesis_gap`, `novelty_claim`, `collision_risks`, and `recommended_positioning`.
- `references`: a list of reference entries with `paper_id`, `title`, `why_relevant`, and optional evidence quote.
- `open_questions`: unresolved questions that should guide the next survey iteration.

Allowed paper roles are:

- `core`;
- `adjacent`;
- `collision`;
- `background`.

The parser must fail clearly on missing required top-level sections or unknown paper ids. It may normalize common LLM scalar drift, such as a single string where `list[str]` is expected.

## Markdown Output

`survey.md` updates the `taxonomy` auto-block. It should summarize:

- method groups;
- what each group optimizes or assumes;
- which papers belong to each group;
- the most important distinction for the thesis topic.

`papers.md` updates the `paper-map` auto-block. It should group papers by role and include short rationales grounded in reading package evidence.

`positioning.md` updates the `positioning` auto-block. It should state:

- the thesis gap;
- why the topic is not already solved by collision papers;
- what claim is defensible;
- what risks need follow-up reading.

`references.md` updates the `references` auto-block. It should provide a compact, reusable bibliography-style list for downstream writing.

The renderer must preserve manual text outside auto-blocks.

## Error Handling

`survey synthesize` should fail before calling the LLM if:

- `topic.yaml` is missing or malformed;
- the readings directory does not exist;
- no reading package JSON files are found;
- a reading package is malformed;
- duplicate `paper_id` values are found.

If the LLM returns malformed synthesis JSON, the command should exit with a clear schema error and leave existing Markdown artifacts unchanged. Artifact updates should happen after the full synthesis object is validated.

## Testing

Automated tests should cover:

- loading multiple reading package JSON files;
- rejecting duplicates and malformed packages;
- validating synthesis schemas;
- rendering all four auto-blocks;
- preserving manual Markdown outside auto-blocks;
- CLI argument validation and lazy imports;
- an end-to-end fake LLM workflow from topic + readings to updated artifacts.

Manual smoke should use at least three real PDFs from `data/pdfs/mvp3-smoke/` after converting them to staged reading packages with `read --staged`.

## Deferred Work

MVP-3 intentionally defers:

- automatic paper search and ranking;
- citation graph expansion;
- arXiv/Semantic Scholar integrations;
- SOTA record extraction;
- incremental synthesis over partial paper sets;
- web UI or visualization.

