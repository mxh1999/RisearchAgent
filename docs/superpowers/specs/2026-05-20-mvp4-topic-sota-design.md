# MVP-4 Topic SOTA Design

## Goal

Build a topic-scoped SOTA maintenance workflow that turns staged reading package experiment records into stable topic artifacts:

- `<topic_dir>/sota.md`
- `<topic_dir>/state/sota_records.jsonl`

The workflow must update existing topic files in place and must not rewrite `topic.yaml`.

## Non-Goals

- No web search or automatic benchmark leaderboard verification.
- No LLM-based conflict resolution.
- No migration of the older global `src/knowledge/sota_tracker.py` workflow.
- No database schema changes.

## CLI

Primary command:

```bash
python run.py sota update --topic data/topics/<topic_id>/topic.yaml
```

Optional source override:

```bash
python run.py sota update --topic data/topics/<topic_id>/topic.yaml --readings-dir data/readings
```

Backwards compatibility:

```bash
python run.py sota
```

continues to show the existing global SOTA markdown directory.

## Data Flow

1. Load and validate `topic.yaml`.
2. Validate `topic.topic_id == topic_dir.name`.
3. Load staged reading packages from `<topic_dir>/papers` by default.
4. Extract every `ExperimentRecord` from every package.
5. Normalize grouping keys:
   - `benchmark`: trim whitespace, collapse internal spaces, preserve display case.
   - `setting`: trim whitespace, collapse internal spaces, default empty to `N/A`.
   - `metric`: trim whitespace, collapse internal spaces.
6. Write normalized records as JSONL to `state/sota_records.jsonl`.
7. Render `sota.md` as deterministic markdown tables grouped by benchmark, setting, and metric.

## Record Model

Each topic SOTA record contains:

- `paper_id`
- `title`
- `benchmark`
- `setting`
- `metric`
- `method`
- `value`
- `higher_is_better`
- `source_page`
- `source_section`
- `source_quote`
- `source_confidence`

The record is intentionally close to `ExperimentRecord` so the workflow remains explainable and auditable.

## Ranking Semantics

Within each `(benchmark, setting, metric)` table:

- if `higher_is_better` is true, sort by value descending;
- if false, sort by value ascending;
- ties sort by method then paper id;
- rank is display-only and recomputed on render.

If records in the same table disagree on `higher_is_better`, keep all records but render a warning note above the table.

## Markdown Output

`sota.md` should contain one stable auto block:

```markdown
# <Topic Name> SOTA

<!-- BEGIN AUTO:sota -->
...
<!-- END AUTO:sota -->
```

The auto block should contain sections:

```markdown
## <Benchmark>

### <Setting> / <Metric> ↑

| Rank | Method | Value | Paper | Evidence |
|---:|---|---:|---|---|
| 1 | Method | 35.1 | `paper_id` | p.8, Experiments: "short quote" |
```

Quotes are truncated to keep the table readable.

## Error Handling

The command fails before writes if:

- topic YAML is missing, invalid, or has mismatched `topic_id`;
- readings directory is missing or has malformed packages;
- no experiment records are found.

If `sota.md` does not exist, the command creates it. If it exists, only the `AUTO:sota` block is replaced.

## Testing

Unit tests:

- normalization and sorting;
- JSONL rendering;
- markdown table rendering;
- mixed metric direction warning;
- no-experiment failure.

CLI/workflow tests:

- parser accepts `sota update --topic`;
- command creates `sota.md` and `state/sota_records.jsonl`;
- command preserves manual text around the `AUTO:sota` block;
- command preserves `topic.yaml` bytes;
- old `python run.py sota` path remains parseable.

## Future Extensions

- Add `sota verify` to compare local records against external benchmark pages.
- Add conflict analysis when multiple papers report inconsistent baseline values.
- Add canonical benchmark aliases after enough real data is collected.
