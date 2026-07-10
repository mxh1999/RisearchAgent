# RisearchAgent

An automated arXiv research assistant that surveys a research topic, reads full papers, and maintains auditable SOTA tables.

## Why RisearchAgent

Most tools stop at abstract-level summaries. RisearchAgent is designed for topic-level research workflows:

- **Topic refinement** - Turns a vague research direction or chat note into a reusable topic profile with scope, query families, benchmark hints, and open questions.
- **Topic discovery** - Searches arXiv from the topic profile, screens candidates, downloads papers, and builds a topic-local reading set.
- **Full-paper reading** - Runs staged LLM analysis over complete PDFs with page-aware evidence.
- **TeX source table extraction** - Downloads arXiv source archives when available and extracts LaTeX tables for cleaner benchmark evidence than PDF text alone.
- **Survey synthesis** - Maintains topic artifacts such as `survey.md`, `papers.md`, `positioning.md`, and `references.md`.
- **SOTA tracking** - Extracts experiment records and renders auditable Markdown leaderboards with result kinds and setting groups.

## Pipeline

```text
survey refine -> topic discover -> topic screen -> topic download
       -> topic ingest -> topic validate -> topic update
```

1. **Refine** - Build or update `topic.yaml` from a natural-language topic description.
2. **Discover** - Query arXiv with topic-specific query families.
3. **Screen** - Use an LLM relevance gate before downloading.
4. **Download** - Materialize PDFs and, when possible, arXiv TeX source archives.
5. **Ingest** - Deep-read accepted papers. PDF text is used for the full paper; TeX source tables are injected into the experiment extraction stage.
6. **Validate** - Re-check relevance after full reading.
7. **Update** - Refresh survey artifacts and SOTA markdown tables.

The legacy global pipeline is still available, but new topic survey work should prefer the topic workflow above.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env       # add your RISEARCHAGENT_API_KEY
cp example.yaml config.yaml # add your provider base_url and model names

# Refine a topic with the default GPT provider
python run.py survey refine "your research direction"

# Or manually edit config.yaml with your research topics
```

## Usage

```bash
# Legacy Gemini-only global pipeline
python run.py pipeline

# Legacy stages
python run.py crawl
python run.py filter
python run.py read <arxiv_id>

# Knowledge management
python run.py sota
python run.py stats
python run.py export [output.json]
python run.py import data.json         # add --merge to upsert

# Legacy Gemini-only onboarding
python run.py onboard
python run.py onboard --refine
```

## Topic Workflow

```bash
# 1. Refine a topic from free-form text
python run.py survey refine "semantic exploration for object-goal navigation"

# 2. Discover and screen candidate papers
python run.py topic discover --topic data/topics/<topic_id>/topic.yaml --sort relevance
python run.py topic screen --topic data/topics/<topic_id>/topic.yaml --threshold 0.6

# 3. Download PDFs and arXiv source archives, then write an ingest manifest
python run.py topic download --topic data/topics/<topic_id>/topic.yaml --all

# 4. Deep-read the downloaded papers
python run.py topic ingest --topic data/topics/<topic_id>/topic.yaml \
  --manifest data/topics/<topic_id>/ingest_manifest.yaml

# 5. Validate read papers and update survey/SOTA artifacts
python run.py topic validate --topic data/topics/<topic_id>/topic.yaml --threshold 0.6
python run.py topic update --topic data/topics/<topic_id>/topic.yaml
```

Use `--no-llm-normalize` with `topic update` when you want conservative exact SOTA setting groups without LLM-based synonym merging.

## PDF And Source Extraction

PDF extraction uses `pymupdf4llm` first and falls back to PyMuPDF. This is good enough for page-aware full-paper reading, but complex benchmark tables can still lose column structure in PDF text.

For arXiv papers, `topic download` also tries `https://arxiv.org/e-print/<paper_id>` and stores the result under `sources/<paper_id>.tar.gz`. During `topic ingest`, the reader extracts LaTeX table environments from that source archive and injects them into the experiment extraction stage. This gives SOTA extraction access to table captions, labels, raw LaTeX, and best-effort markdown tables with preserved benchmark axes such as HM3D/MP3D, train set, split, and metric columns.

If the source archive is unavailable or cannot be parsed, ingestion continues with PDF text only.

## Configuration

`config.yaml` is local-only and ignored by git because it may contain private provider endpoints. Start from `example.yaml`:

```bash
cp example.yaml config.yaml
```

Set `RISEARCHAGENT_API_KEY` in `.env`. The default provider uses an OpenAI-compatible Chat Completions API:

```yaml
llm:
  response_format: gpt
  base_url: https://api.ikuncode.cc
  api_key_env: RISEARCHAGENT_API_KEY
  filter_model: gpt-5.6-sol
  reader_model: gpt-5.6-sol
```

`response_format` selects the API dialect: `gpt` for OpenAI-compatible chat completions, `claude` for Anthropic-compatible messages, and `gemini` for Gemini-native calls.

Topic workflows primarily use `topic.yaml` files created under `data/topics/<topic_id>/`.

| Section | What it does |
|---------|-------------|
| `topics` | arXiv search queries and per-topic research profile for relevance filtering |
| `llm` | Provider dialect, base URL, model selection, concurrency, temperature, and API key env var |
| `scraper` | Max results per topic and lookback window in days |
| `filter` | Relevance score thresholds |

## Tech Stack

| Component | Choice |
|-----------|--------|
| LLM | `gpt-5.6-sol` through an OpenAI-compatible provider by default |
| PDF Extraction | `pymupdf4llm` with PyMuPDF fallback |
| Table Extraction | arXiv TeX source archives when available |
| Database | SQLite via aiosqlite |
