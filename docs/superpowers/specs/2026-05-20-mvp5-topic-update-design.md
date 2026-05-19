# MVP-5 Topic Update Design

## Goal

Build a single topic-level update command that refreshes the existing derived artifacts for a topic:

- `survey.md`
- `papers.md`
- `positioning.md`
- `references.md`
- `sota.md`
- `state/topic_update_report.json`

The command orchestrates already-built local workflows. It does not discover, download, or read new papers.

## CLI

Primary command:

```bash
python run.py topic update --topic data/topics/<topic_id>/topic.yaml
```

Options:

```bash
python run.py topic update \
  --topic data/topics/<topic_id>/topic.yaml \
  --readings-dir data/topics/<topic_id>/papers \
  --skip-survey \
  --skip-sota \
  --no-llm-normalize
```

Defaults:

- `--readings-dir` defaults to `<topic_dir>/papers`.
- survey synthesis runs unless `--skip-survey` is passed.
- SOTA update runs unless `--skip-sota` is passed.
- SOTA setting normalization uses the MVP-4 incremental cache unless `--no-llm-normalize` is passed.

## Non-Goals

- No paper search.
- No PDF download.
- No staged paper reading.
- No automatic retry policy across LLM failures.
- No rewriting `topic.yaml`.

## Data Flow

1. Load and validate `topic.yaml`.
2. Validate `topic.topic_id == topic_dir.name`.
3. Load staged reading packages from the readings directory.
4. Build a preflight summary:
   - number of packages;
   - package ids;
   - package ids with experiment records;
   - package ids without experiment records.
5. If survey is enabled, run the same synthesis logic as `survey synthesize`.
6. If SOTA is enabled, run the same update logic as `sota update`.
7. Write `state/topic_update_report.json`.
8. Print concise output paths and status.

## Report Shape

`state/topic_update_report.json`:

```json
{
  "topic_id": "task_driven_3d_utility_learning_for_embodied_navigation",
  "topic_name": "Task-Driven 3D Utility Learning for Embodied Navigation",
  "readings_dir": "data/topics/.../papers",
  "paper_count": 3,
  "paper_ids": ["mtu3d", "msgnav", "vlfm"],
  "papers_with_experiments": ["mtu3d", "vlfm"],
  "papers_without_experiments": ["msgnav"],
  "survey": {
    "status": "updated",
    "artifacts": ["survey.md", "papers.md", "positioning.md", "references.md"]
  },
  "sota": {
    "status": "updated",
    "record_count": 42,
    "setting_group_count": 17,
    "artifacts": ["sota.md", "state/sota_records.jsonl", "state/sota_setting_groups.json"]
  },
  "warnings": [
    "1 paper has no experiment records: msgnav"
  ]
}
```

Statuses:

- `updated`
- `skipped`
- `failed`

For MVP-5, a failed substep stops the command and reports the error through `SystemExit`; partial success recovery is a future extension.

## Artifact Rules

- `topic.yaml` must remain byte-for-byte unchanged.
- The command updates only existing workflow artifacts and `state/topic_update_report.json`.
- Survey artifacts are created only if survey runs.
- SOTA artifacts are created only if SOTA runs.
- Manual text outside AUTO blocks must be preserved.

## Architecture

Create a small orchestration layer:

- `src/survey/topic_update.py`
  - loads topic and reading packages;
  - builds preflight summary;
  - calls survey synthesis service function;
  - calls SOTA update service function;
  - writes report.

Refactor existing CLI modules to expose service functions:

- `src/survey/cli.py`
  - keep CLI behavior;
  - add reusable `synthesize_survey_artifacts(...)`.
- `src/survey/sota_cli.py`
  - keep CLI behavior;
  - add reusable `update_sota_artifacts(...)`.

This avoids shelling out to nested CLI commands and keeps tests fast.

## Error Handling

The command fails before any writes if:

- topic YAML is missing or malformed;
- `topic_id` does not match directory name;
- readings directory is missing or has malformed packages;
- both `--skip-survey` and `--skip-sota` are passed.

Survey or SOTA-specific failures use the existing service validation.

## Testing

Unit tests:

- preflight summary counts papers with and without experiments;
- report JSON round-trip / shape;
- skip behavior.

Workflow tests:

- parser accepts `topic update --topic`;
- update runs survey + SOTA with fake LLMs;
- `topic.yaml` bytes are preserved;
- manual text around AUTO blocks is preserved;
- report contains paper counts, warnings, artifacts, and statuses;
- `--skip-survey` does not create survey artifacts;
- `--skip-sota` does not create SOTA artifacts;
- both skips are rejected.

Smoke:

Run against the existing smoke topic with MTU3D / MSGNav / VLFM reading packages:

```bash
python run.py topic update \
  --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml \
  --no-llm-normalize
```

Then inspect `state/topic_update_report.json`.
