# MVP-6 Topic Ingest Design

## Goal

Build a deterministic topic-scoped ingestion command for papers the user already has locally. The command converts a manifest of local PDF or text files into staged reading packages under a topic workspace, writes an ingestion report, and can optionally refresh the existing topic artifacts.

Primary command:

```bash
python run.py topic ingest \
  --topic data/topics/<topic_id>/topic.yaml \
  --manifest data/topics/<topic_id>/ingest_manifest.yaml
```

Optional update:

```bash
python run.py topic ingest \
  --topic data/topics/<topic_id>/topic.yaml \
  --manifest data/topics/<topic_id>/ingest_manifest.yaml \
  --update
```

MVP-6 intentionally covers local ingestion only. Paper discovery from arXiv, Semantic Scholar, or web search is a separate MVP.

## Motivation

The existing workflow can refine a topic, read one paper, synthesize a survey, maintain topic SOTA, and update derived topic artifacts. The missing production entry point is batch ingestion: a user should be able to collect several papers, declare them once, and let the agent read only the missing papers.

This MVP keeps the workflow deterministic and testable. It avoids coupling paper reading to noisy discovery, network failures, and relevance filtering. Later discovery workflows can output the same manifest shape and reuse this ingestion path.

## CLI

New topic subcommand:

```bash
python run.py topic ingest --topic <topic.yaml> --manifest <manifest.yaml>
```

Options:

- `--topic`: required path to the topic YAML.
- `--manifest`: required path to the ingest manifest.
- `--force`: re-read papers even if `<topic_dir>/papers/<paper_id>.json` already exists.
- `--update`: run `topic update` after ingestion finishes.
- `--readings-dir`: optional override for the staged reading output directory. Defaults to `<topic_dir>/papers`.
- `--no-llm-normalize`: forwarded to the optional topic update SOTA step.

The command should fail during argument validation if `--topic` or `--manifest` is missing.

## Manifest

The manifest is YAML and path-relative to the manifest file.

```yaml
papers:
  - paper_id: mtu3d
    title: "Move to Understand a 3D Scene"
    pdf: "../../pdfs/mvp3-smoke/mtu3d.pdf"
    year: 2024
    venue: "arXiv"
    source_url: "https://arxiv.org/abs/..."

  - paper_id: sample_method
    title: "Sample Method Paper"
    text_file: "sample_method.txt"
```

Required fields per paper:

- `paper_id`
- `title`
- exactly one of `pdf` or `text_file`

Optional metadata:

- `year`
- `venue`
- `source_url`
- `notes`

For MVP-6, optional metadata is validated for basic type correctness and carried into the ingest report. It does not change staged reader prompts or reading package schema.

## Validation Rules

The command fails before reading any paper if:

- topic YAML is missing, malformed, or has a `topic_id` that does not match the topic directory name;
- manifest YAML is missing, empty, malformed, or lacks a top-level `papers` list;
- any manifest entry is not a mapping;
- any entry lacks `paper_id` or `title`;
- any entry has both `pdf` and `text_file`, or neither;
- any `paper_id` fails the existing safe paper id validation;
- the manifest contains duplicate `paper_id` values;
- any referenced source file does not exist;
- any referenced source path resolves to a directory.

Preflight validation is all-or-nothing. No reading packages or reports are written if validation fails.

## Data Flow

1. Load and validate `topic.yaml`.
2. Load and validate the manifest.
3. Resolve manifest source paths relative to the manifest file.
4. Determine output paths for all papers.
5. Skip existing papers unless `--force` is set.
6. For each paper to read:
   - extract PDF pages or text-file pages;
   - call the existing staged paper reader;
   - write `<readings_dir>/<paper_id>.json`;
   - write `<readings_dir>/<paper_id>.md`.
7. Write `<topic_dir>/state/ingest_report.json`.
8. If `--update` is set, call the existing topic update service and record its report path.
9. Print a concise summary with counts and artifact paths.

## Report Shape

`<topic_dir>/state/ingest_report.json`:

```json
{
  "topic_id": "task_driven_3d_utility_learning_for_embodied_navigation",
  "topic_name": "Task-Driven 3D Utility Learning for Embodied Navigation",
  "manifest_path": "data/topics/.../ingest_manifest.yaml",
  "readings_dir": "data/topics/.../papers",
  "total": 3,
  "read": ["new_paper"],
  "skipped_existing": ["mtu3d", "msgnav"],
  "failed": [],
  "artifacts": {
    "new_paper": {
      "json": "data/topics/.../papers/new_paper.json",
      "markdown": "data/topics/.../papers/new_paper.md"
    }
  },
  "metadata": {
    "new_paper": {
      "year": 2024,
      "venue": "arXiv",
      "source_url": "https://arxiv.org/abs/..."
    }
  },
  "update": {
    "status": "skipped",
    "report_path": null
  }
}
```

Update statuses:

- `skipped`
- `updated`
- `failed`

For MVP-6, a failed read stops the command and records the failure only if a report can be written consistently. Partial retry queues are deferred.

## Artifact Rules

- `topic.yaml` must remain byte-for-byte unchanged.
- Reading packages are written only under the resolved readings directory.
- The default readings directory is `<topic_dir>/papers`.
- The ingest report is written under `<topic_dir>/state/ingest_report.json`.
- Existing reading packages are preserved unless `--force` is set.
- Existing survey and SOTA artifacts are touched only when `--update` is set.

## Architecture

Add a small ingestion layer rather than shelling out to the CLI:

- `src/survey/topic_ingest.py`
  - manifest models and validation;
  - preflight planning;
  - ingestion orchestration;
  - report writing.
- `src/survey/ingest_cli.py`
  - CLI-facing argument handling;
  - LLM setup;
  - concise console output.
- `src/reader/staged_cli.py`
  - expose a reusable service function for staged reading from PDF or text source;
  - keep existing `read --staged` behavior unchanged.
- `run.py`
  - add `topic ingest` parser and dispatch before global legacy pipeline config loading.

The ingestion service should call the staged reader directly. It should not invoke nested subprocesses or parse CLI stdout.

## Error Handling

Preflight errors stop before any writes.

Per-paper reading errors stop the command by default. The report should include any successfully completed papers and the failing `paper_id` when doing so does not hide the original exception. Continue-on-error is not part of MVP-6 because it complicates correctness and retry semantics.

If `--update` fails after ingestion succeeds, reading packages remain written and the report records `update.status = "failed"` before re-raising a user-facing error.

## Testing

Unit tests:

- manifest loader accepts valid PDF and text entries;
- missing required fields are rejected;
- both `pdf` and `text_file` are rejected;
- duplicate `paper_id` values are rejected;
- unsafe `paper_id` values are rejected;
- missing source files are rejected during preflight;
- existing reading package is skipped without `--force`;
- `--force` schedules existing papers for reading;
- ingest report has stable shape.

Workflow tests:

- parser accepts `topic ingest --topic --manifest`;
- ingestion writes JSON and Markdown packages using a fake staged reader;
- `topic.yaml` bytes are preserved;
- `--update` calls the topic update service;
- `--no-llm-normalize` is forwarded to the topic update service;
- validation fails before writes when the manifest is invalid.

Smoke:

Use the existing smoke topic and downloaded PDFs:

```bash
python run.py topic ingest \
  --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml \
  --manifest data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/ingest_manifest.yaml
```

The first smoke should verify skip behavior for already-read MTU3D, MSGNav, and VLFM packages. A controlled `--force` run may be used on one paper when LLM cost and latency are acceptable.

## Non-Goals

- No arXiv, Semantic Scholar, or web discovery.
- No automatic PDF download.
- No relevance judge.
- No DOI/title deduplication beyond manifest `paper_id`.
- No concurrent reading.
- No continue-on-error retry queue.
- No changes to the staged reading package schema.

## Follow-Up MVP

MVP-7 should be a separate discovery workflow. It can produce a reviewed candidate list or manifest entries, then hand off to `topic ingest`. Keeping discovery separate prevents noisy candidate generation from destabilizing deterministic reading and update workflows.
