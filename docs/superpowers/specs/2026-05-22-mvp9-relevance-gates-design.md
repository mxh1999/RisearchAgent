# MVP-9 Relevance Gates Design

## Goal

Add two relevance gates so noisy discovery results do not waste reading budget or pollute topic survey/SOTA artifacts.

- MVP-9A: pre-download title/abstract screening.
- MVP-9B: post-reading package validation.

## Motivation

The MVP-7 to MVP-8 to MVP-6 pipeline works end to end, but real arXiv discovery can retrieve papers that match generic words such as "memory" while being outside the topic. The system needs both a cheap early filter and a final full-reading filter.

## Commands

Pre-download screening:

```bash
python run.py topic screen --topic data/topics/<topic_id>/topic.yaml
```

Post-reading validation:

```bash
python run.py topic validate --topic data/topics/<topic_id>/topic.yaml
```

Both commands use the configured Gemini filter model by default. They accept:

- `--threshold`: minimum score for automatic inclusion, default `0.6`.
- `--limit`: optional cap for local testing or cost control.
- `--dry-run`: print/write report without changing candidate statuses or update filtering state.
- `--model`: optional model override.

`topic screen` also accepts `--candidates`, defaulting to `<topic_dir>/state/discovery_candidates.json`.

`topic validate` also accepts `--readings-dir`, defaulting to `<topic_dir>/papers`.

## Decisions

Both gates use one normalized decision schema:

```json
{
  "paper_id": "2605.20152",
  "decision": "accept",
  "score": 0.82,
  "reason": "Directly studies task-conditioned utility for embodied navigation.",
  "matched_topic_aspects": ["embodied navigation", "utility learning"],
  "missing_topic_aspects": []
}
```

Allowed decisions are `accept`, `reject`, and `uncertain`.

Inclusion rule:

- `accept` and `score >= threshold`: include.
- `uncertain`: include, but keep the uncertainty in the report.
- `reject` or low-score `accept`: exclude.

## MVP-9A Data Flow

1. Load `topic.yaml`.
2. Load `<topic_dir>/state/discovery_candidates.json`.
3. For each candidate, prompt the LLM with topic profile, matched queries, title, abstract, categories, and source metadata.
4. Update each screened candidate in the same JSON file with a `relevance` object.
5. Set `status` to `candidate` or `rejected`.
6. Refresh `<topic_dir>/discovery.md` and `<topic_dir>/ingest_manifest.draft.yaml`.
7. Write `<topic_dir>/state/screening_report.json`.

`topic download` already skips non-`candidate` statuses, so no download behavior change is required.

## MVP-9B Data Flow

1. Load `topic.yaml`.
2. Load staged reading packages from `<topic_dir>/papers` or `--readings-dir`.
3. For each package, prompt the LLM with topic profile plus summary, method modules, claims, experiments, critique, and existing `topic_relation`.
4. Write `<topic_dir>/state/relevance_validations.json`.
5. `topic update` automatically reads that validation report when it exists and excludes papers whose validation says `include: false`.

The reading package files are not modified. The validation state is separate so users can inspect or delete it.

## Error Handling

Missing topic files, malformed candidate JSON, topic id mismatches, missing reading packages, invalid thresholds, invalid decisions, and malformed LLM responses fail before writing partial updates when possible.

Per-paper LLM failures are recorded as `uncertain` include decisions rather than silently rejecting papers.

## Testing

Tests use fake LLMs and temporary files. Coverage should include:

- pre-download screening accepts relevant abstracts and rejects obvious false positives;
- screening updates the existing discovery JSON and manifest draft;
- dry-run leaves candidate statuses untouched;
- post-reading validation writes include/exclude decisions;
- `topic update` filters out excluded reading packages when validation exists;
- parser and CLI preflight behavior.

