# MVP-7 Topic Discover Design

## Goal

Build an arXiv-only topic discovery workflow that searches candidate papers from a topic profile and writes reviewable local artifacts. The workflow helps evaluate whether `topic.yaml` query families can retrieve useful papers for emerging or cross-disciplinary topics.

Primary command:

```bash
python run.py topic discover \
  --topic data/topics/<topic_id>/topic.yaml
```

Outputs:

- `<topic_dir>/state/discovery_candidates.json`
- `<topic_dir>/discovery.md`
- `<topic_dir>/ingest_manifest.draft.yaml`

MVP-7 discovers candidates only. It does not download PDFs, read papers, update survey artifacts, update SOTA artifacts, or modify `topic.yaml`.

## Motivation

MVP-6 created a deterministic ingestion path for local papers. MVP-7 should sit before ingestion: it should collect candidate papers from arXiv using the topic's query families, make the result easy to review, and produce a draft manifest that can later be converted into an ingestion manifest.

Keeping discovery separate from ingestion prevents noisy search results and network instability from destabilizing the paper reader workflow.

## CLI

New topic subcommand:

```bash
python run.py topic discover --topic <topic.yaml>
```

Options:

- `--topic`: required path to `topic.yaml`.
- `--max-results-per-query`: optional integer, default `20`.
- `--sort`: optional enum, one of `submitted` or `relevance`, default `submitted`.
- `--days-lookback`: optional integer, default `365`; filters out older arXiv results by publication date.
- `--include-existing`: include papers that already have staged reading packages under `<topic_dir>/papers`; default is to exclude them.

The command should run before legacy global config loading, like the existing `topic update` and `topic ingest` commands.

## Query Source

The command reads `TopicProfile.search_queries` from `topic.yaml`.

Each query has:

- `name`
- `query`
- `purpose`

For MVP-7, every query is sent to arXiv independently. Results are deduplicated by `arxiv_id`. A candidate records all query names and query purposes that matched it.

If `search_queries` is empty, the command fails before contacting arXiv with a message telling the user to refine the topic first.

## Candidate Model

`state/discovery_candidates.json` contains:

```json
{
  "topic_id": "task_driven_3d_utility_learning_for_embodied_navigation",
  "topic_name": "Task-Driven 3D Utility Learning for Embodied Navigation",
  "source": "arxiv",
  "generated_at": "2026-05-21T00:00:00+00:00",
  "query_count": 3,
  "candidate_count": 12,
  "excluded_existing": ["2401.12345"],
  "candidates": [
    {
      "paper_id": "2401.12345",
      "arxiv_id": "2401.12345",
      "title": "Example Paper",
      "abstract": "Paper abstract.",
      "authors": ["A. Researcher", "B. Researcher"],
      "published": "2024-01-01",
      "year": 2024,
      "categories": ["cs.RO", "cs.CV"],
      "pdf_url": "https://arxiv.org/pdf/2401.12345",
      "source_url": "https://arxiv.org/abs/2401.12345",
      "matched_queries": ["direct", "benchmark"],
      "query_rationales": ["Direct topic query.", "Benchmark-oriented query."],
      "status": "candidate"
    }
  ]
}
```

`paper_id` is the arXiv id and must pass the same safe paper id constraints used by reading package writers.

## Discovery Markdown

`discovery.md` is a review surface for the user. It should contain:

- topic name and generated timestamp;
- query summary table;
- candidate table sorted by publication date descending;
- title, year, categories, matched query names, source URL, and a short abstract preview.

The file is fully generated in MVP-7. Preserving manual edits in `discovery.md` is not required.

## Draft Manifest

`ingest_manifest.draft.yaml` is a human-reviewable draft, not directly consumed by MVP-6 yet because MVP-6 requires local `pdf` or `text_file` paths.

Shape:

```yaml
papers:
  - paper_id: "2401.12345"
    title: "Example Paper"
    pdf_url: "https://arxiv.org/pdf/2401.12345"
    source_url: "https://arxiv.org/abs/2401.12345"
    venue: "arXiv"
    year: 2024
```

MVP-8 can add a download workflow that turns selected `pdf_url` entries into local `pdf` paths and then calls `topic ingest`.

## Existing Paper Filtering

By default, candidates whose `paper_id` already exists as `<topic_dir>/papers/<paper_id>.json` are excluded.

The report records excluded ids under `excluded_existing`.

If `--include-existing` is set, existing papers remain in the candidate list and `excluded_existing` is empty.

## Architecture

Add a small discovery layer:

- `src/survey/topic_discover.py`
  - candidate dataclasses;
  - arXiv result conversion;
  - deduplication and existing-paper filtering;
  - JSON, Markdown, and draft manifest rendering;
  - artifact writing.
- `src/survey/discover_cli.py`
  - CLI argument handling;
  - topic loading and validation;
  - arXiv provider setup;
  - concise console output.
- `run.py`
  - add `topic discover` parser and dispatch through `src.survey.topic_cli`.
- `src/survey/topic_cli.py`
  - dispatch `topic discover`.

Provider boundary:

- Define a small async callable interface that accepts a query string, max results, sort mode, and returns raw arXiv-like records.
- The default provider uses the installed `arxiv` package.
- Tests should use a fake provider and not contact the network.

## Error Handling

The command fails before contacting arXiv if:

- topic YAML is missing or malformed;
- `topic_id` does not match the topic directory name;
- `search_queries` is empty;
- `--max-results-per-query` is less than 1;
- `--days-lookback` is less than 1;
- `--sort` is not one of the supported modes.

If one query fails during arXiv search, MVP-7 fails the command and does not write partial artifacts. Continue-on-error can be added later if needed.

## Testing

Unit tests:

- candidate deduplication merges matched query names and rationales;
- existing reading packages are excluded by default;
- `--include-existing` keeps existing papers;
- generated JSON has stable shape;
- generated Markdown includes query and candidate tables;
- generated draft manifest contains `pdf_url`, `source_url`, `venue`, and `year`;
- empty `search_queries` fails before provider call.

CLI tests:

- parser accepts `topic discover` options;
- invalid `--sort`, `--max-results-per-query`, and `--days-lookback` are rejected;
- command writes all three artifacts using a fake provider;
- command does not call provider if topic validation fails.

Smoke:

Use the smoke topic and run:

```bash
python run.py topic discover \
  --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml \
  --max-results-per-query 3 \
  --days-lookback 3650
```

Then inspect:

```bash
python -c "import json; p='data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/discovery_candidates.json'; d=json.load(open(p, encoding='utf-8')); print(d['query_count'], d['candidate_count'])"
```

The smoke should verify artifact creation, not quality of search relevance.

## Non-Goals

- No PDF download.
- No staged reading.
- No survey update.
- No SOTA update.
- No LLM relevance scoring.
- No Semantic Scholar integration.
- No web search.
- No automatic modification of `topic.yaml`.
- No automatic call to `topic ingest`.

## Follow-Up MVP

MVP-8 should convert selected discovery candidates into local PDFs and a valid MVP-6 ingestion manifest. That can include PDF download, selected-candidate filtering, and optional handoff to `topic ingest`.
