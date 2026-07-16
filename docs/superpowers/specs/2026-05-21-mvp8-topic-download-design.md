# MVP-8 Topic Download Design

## Goal

Build a deterministic bridge from MVP-7 discovery artifacts to MVP-6 ingestion by downloading selected candidate PDFs and writing a valid topic-local `ingest_manifest.yaml`.

Primary command:

```bash
python run.py topic download --topic data/topics/<topic_id>/topic.yaml
```

## Scope

MVP-8 downloads PDFs and writes local artifacts only. It does not read PDFs, run staged paper analysis, update survey files, update SOTA files, or modify `topic.yaml`.

Inputs:

- `<topic_dir>/state/discovery_candidates.json` by default.
- Candidate rows whose `status` is `candidate`.
- Existing staged papers under `<topic_dir>/papers` are skipped unless `--include-existing` is passed.

Outputs:

- `<topic_dir>/pdfs/<paper_id>.pdf`
- `<topic_dir>/ingest_manifest.yaml`
- `<topic_dir>/state/download_report.json`

## CLI

```bash
python run.py topic download --topic <topic.yaml>
```

Options:

- `--topic`: required path to `topic.yaml`.
- `--candidates`: optional path to discovery candidates JSON, default `<topic_dir>/state/discovery_candidates.json`.
- `--manifest`: optional output path, default `<topic_dir>/ingest_manifest.yaml`.
- `--limit`: optional positive integer, default `10`.
- `--all`: ignore `--limit` and materialize all eligible candidates.
- `--include-existing`: include papers that already have staged packages.
- `--force`: re-download PDFs even when the target file already exists.

The command should run before legacy global config loading, like `topic discover`, `topic ingest`, and `topic update`.

## Data Flow

1. Load `topic.yaml` and validate that the discovery file belongs to the same `topic_id`.
2. Read candidates in discovery order.
3. Filter to `status == "candidate"`, apply existing-paper skip rules, and cap by `--limit` unless `--all` is set.
4. Download each candidate's `pdf_url` to `<topic_dir>/pdfs/<paper_id>.pdf` using an atomic temporary file.
5. Reuse existing PDF files unless `--force` is set.
6. Write `ingest_manifest.yaml` with relative `pdf` paths so MVP-6 `load_ingest_manifest` can consume it directly.
7. Write `state/download_report.json` with downloaded, reused, skipped, and failed rows.

## Error Handling

Missing topic files, missing discovery files, malformed discovery JSON, topic id mismatches, missing candidate `pdf_url`, invalid `--limit`, and conflicting `--all --limit` fail before network downloads when possible.

Per-paper network failures are isolated: the command continues with remaining candidates, records failures in the report, and excludes failed papers from `ingest_manifest.yaml`.

## Testing

Tests should use fake download functions and temporary files, not the public network. Coverage should include candidate filtering, existing-paper skipping, PDF reuse, failed downloads, valid manifest generation, parser validation, and CLI dispatch.

