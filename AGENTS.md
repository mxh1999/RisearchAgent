# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project

RisearchAgent — an automated ArXiv research assistant that crawls papers, filters by relevance, performs full-text deep reading via LLM, classifies contributions against a knowledge base, and maintains SOTA benchmark leaderboards.

## Commands

```bash
# Install dependencies (conda env: paper_reader, Python 3.11)
pip install -r requirements.txt

# Environment setup
cp .env.example .env  # set RISEARCHAGENT_API_KEY

# Run legacy Gemini-only pipeline
python run.py pipeline

# Run individual stages
python run.py crawl
python run.py filter
python run.py read <arxiv_id>

# Utilities
python run.py sota          # view SOTA leaderboards
python run.py stats         # database statistics
python run.py export [out.json]
python run.py import data.json --merge
python run.py onboard       # legacy Gemini-only config setup
python run.py onboard --refine

# Verbose logging
python run.py -v <command>
```

Experiments should use the `paper_reader` conda environment.

Run tests with `conda run -n paper_reader python -m pytest`.

## Architecture

### Legacy pipeline (5 stages, all async)

`run.py` → `PipelineOrchestrator` (src/pipeline/orchestrator.py) orchestrates everything:

1. **Crawl** — `ArxivScraper` fetches papers via ArXiv API per topic queries in config.yaml
2. **Filter** — `RelevanceJudge` scores papers 0–10 against per-topic research profiles
3. **Deep Read** — `PDFDownloader` extracts text and `DeepReader` runs staged LLM analysis
4. **Contribution Analysis** — `ContributionAnalyzer` compares against ChromaDB knowledge base, classifies as breakthrough/significant/incremental/marginal
5. **SOTA Update** — `SOTAKnowledgeBase` updates Markdown leaderboard files in `data/sota/`, with LLM-based conflict resolution

### LLM layer

`create_llm_client()` (src/llm/client.py) selects an API-dialect adapter. The default is the OpenAI-compatible `GPTClient` using `gpt-5.6-sol`; Claude- and Gemini-compatible clients remain for explicit legacy configurations. API keys are loaded from the configured environment variable and must never be committed.

### Storage

- **SQLite** (src/storage/database.py) — structured data: papers, relevance verdicts, deep readings, contribution deltas, SOTA update audit log, pipeline runs. Uses `aiosqlite`. Schema includes automatic migrations.
- **ChromaDB** (src/knowledge/knowledge_base.py) — retained only by the legacy pipeline. Embeddings are not part of the active topic workflow or new agent design.

### SOTA tracking

`SOTAKnowledgeBase` (src/knowledge/sota_tracker.py) stores benchmark leaderboards as Markdown files in `data/sota/`. Uses LLM to resolve conflicts when papers report different baseline numbers. Database `sota_updates` table serves as an audit log only.

### Data models

All dataclasses live in `src/models.py`: Paper, RelevanceVerdict, DeepReading, ExperimentTable/ExperimentEntry/MethodResult, ContributionDelta, SOTAUpdateReport. The ExperimentTable hierarchy is serialized to JSON for SQLite storage.

### Configuration

`config.yaml` → `load_config()` in src/config.py → `AppConfig` dataclass. The default GPT provider reads `RISEARCHAGENT_API_KEY` from `.env`. Topics include ArXiv queries + research profiles for relevance filtering.

### Key patterns

- Every database method opens its own `aiosqlite.connect()` — no connection pooling
- The orchestrator wires all components together; individual modules receive their dependencies via constructor injection
- LLM responses are parsed as JSON through the selected provider adapter
- Section parsing in `deep_reader.py` uses LLM-based parsing (not regex)
- The onboarding module (src/onboard/) runs a synchronous conversational loop, separate from the async pipeline

### Data directories

All under `data/` (gitignored): `papers.db`, `chroma/`, `pdfs/`, `sota/` (Markdown leaderboards)

## Git Commit Policy

- Create a git commit after completing each logical unit of work (e.g., a feature, a bug fix, a refactor)
- Use conventional commit format with emoji (see `/commit` command for reference)
- Keep commits atomic: one commit per logical change, split if multiple concerns are mixed
- Run `make format-check && make test` before committing; fix any failures first
- Do not push to remote unless explicitly asked
- Do not amend or force-push existing commits unless explicitly asked
