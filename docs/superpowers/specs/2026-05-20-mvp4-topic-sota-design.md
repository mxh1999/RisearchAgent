# MVP-4 Topic SOTA Design

## Goal

Build a topic-scoped SOTA maintenance workflow that turns staged reading package experiment records into stable topic artifacts:

- `<topic_dir>/sota.md`
- `<topic_dir>/state/sota_records.jsonl`
- `<topic_dir>/state/sota_setting_groups.json`

The workflow must update existing topic files in place and must not rewrite `topic.yaml`.

## Non-Goals

- No web search or automatic benchmark leaderboard verification.
- No full-history LLM re-normalization on every update.
- No LLM-based numeric result conflict resolution.
- No migration of the older global `src/knowledge/sota_tracker.py` workflow.
- No database schema changes.

## CLI

Primary command:

```bash
python run.py sota update --topic data/topics/<topic_id>/topic.yaml
```

By default, the command uses incremental LLM setting canonicalization when it sees a raw setting that cannot be confidently matched to an existing setting group.

Optional source override:

```bash
python run.py sota update --topic data/topics/<topic_id>/topic.yaml --readings-dir data/readings
```

Conservative offline mode:

```bash
python run.py sota update --topic data/topics/<topic_id>/topic.yaml --no-llm-normalize
```

This mode creates one canonical group per raw `(benchmark, setting)` and never semantically merges settings.

Backwards compatibility:

```bash
python run.py sota
```

continues to show the existing global SOTA markdown directory.

## Data Flow

1. Load and validate `topic.yaml`.
2. Validate `topic.topic_id == topic_dir.name`.
3. Load staged reading packages from `<topic_dir>/papers` by default.
4. Extract every `ExperimentRecord` from every package into raw SOTA records.
5. Normalize raw text fields:
   - `benchmark`: trim whitespace, collapse internal spaces, preserve display case.
   - `setting`: trim whitespace, collapse internal spaces, default empty to `N/A`.
   - `metric`: trim whitespace, collapse internal spaces.
6. Write normalized raw records as JSONL to `state/sota_records.jsonl`.
7. Load `state/sota_setting_groups.json` if present.
8. Assign each record to a canonical setting group:
   - exact normalized `(benchmark, setting)` match against an existing group is automatic;
   - otherwise retrieve a small top-k candidate group list by lexical similarity;
   - if LLM normalization is enabled, ask the LLM whether to merge into one candidate or create a new group;
   - if confidence is not high, create or keep a separate group and render a warning.
9. Persist the updated setting registry to `state/sota_setting_groups.json`.
10. Render `sota.md` as deterministic markdown tables grouped by canonical benchmark, canonical setting, and metric.

## Record Model

Each topic SOTA record contains:

- `record_id`
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

`record_id` is deterministic:

```text
<paper_id>::<benchmark>::<setting>::<metric>::<method>
```

after raw text normalization.

## Setting Group Registry

`state/sota_setting_groups.json` stores incremental canonicalization results:

```json
{
  "groups": [
    {
      "group_id": "goat_bench_val_unseen_standard",
      "canonical_benchmark": "GOAT-Bench",
      "canonical_setting": "val unseen, standard RGB-D protocol",
      "raw_benchmark_settings": [
        {"benchmark": "GOAT-Bench", "setting": "val unseen"}
      ],
      "comparison_axes": {
        "split": "val unseen",
        "sensor": "RGB-D",
        "protocol": "standard",
        "task": "GOAT navigation"
      },
      "confidence": "high",
      "rationale": "Same benchmark split, task, sensor, and evaluation protocol."
    }
  ]
}
```

The registry is append/update only for discovered groups. It avoids sending all historical records to the LLM on every update.

## LLM Canonicalization

The LLM receives only:

- topic name and short intent;
- one new raw benchmark/setting pair with a small number of example records;
- up to five candidate existing groups;
- explicit instructions to avoid merging when protocol, split, sensor, task definition, evaluator, or fine-tuning regime differs.

Expected JSON:

```json
{
  "action": "merge_existing",
  "group_id": "goat_bench_val_unseen_standard",
  "canonical_benchmark": "GOAT-Bench",
  "canonical_setting": "val unseen, standard RGB-D protocol",
  "comparison_axes": {
    "split": "val unseen",
    "sensor": "RGB-D",
    "protocol": "standard",
    "task": "GOAT navigation"
  },
  "confidence": "high",
  "rationale": "Same split and protocol."
}
```

Allowed actions:

- `merge_existing`
- `create_new`

Allowed confidence values:

- `high`
- `medium`
- `low`

Only `high` confidence `merge_existing` decisions are merged automatically. `medium` and `low` confidence decisions create a separate group with warning text in `sota.md`.

## Ranking Semantics

Within each `(canonical_benchmark, canonical_setting, metric)` table:

- if `higher_is_better` is true, sort by value descending;
- if false, sort by value ascending;
- ties sort by method then paper id;
- rank is display-only and recomputed on render.

If records in the same table disagree on `higher_is_better`, keep all records but render a warning note above the table.

If a table includes a low/medium confidence group, render the group confidence and rationale before the table.

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

### <Canonical Setting> / <Metric> (higher is better)

| Rank | Method | Value | Paper | Evidence |
|---:|---|---:|---|---|
| 1 | Method | 35.1 | `paper_id` | raw setting: val unseen; p.8, Experiments: "short quote" |
```

Quotes are truncated to keep the table readable.

## Error Handling

The command fails before writes if:

- topic YAML is missing, invalid, or has mismatched `topic_id`;
- readings directory is missing or has malformed packages;
- no experiment records are found.
- LLM canonicalization returns malformed JSON, unknown group ids, or unknown actions.

If `sota.md` does not exist, the command creates it. If it exists, only the `AUTO:sota` block is replaced.

## Testing

Unit tests:

- normalization and sorting;
- JSONL rendering;
- setting registry round-trip;
- exact setting group matching;
- conservative grouping without LLM;
- LLM merge/create schema validation;
- markdown table rendering;
- mixed metric direction warning;
- no-experiment failure.

CLI/workflow tests:

- parser accepts `sota update --topic`;
- command creates `sota.md` and `state/sota_records.jsonl`;
- command creates/updates `state/sota_setting_groups.json`;
- command preserves manual text around the `AUTO:sota` block;
- command preserves `topic.yaml` bytes;
- old `python run.py sota` path remains parseable.

## Future Extensions

- Add `sota verify` to compare local records against external benchmark pages.
- Add conflict analysis when multiple papers report inconsistent baseline values.
- Add embedding-based candidate retrieval if lexical retrieval becomes weak.
