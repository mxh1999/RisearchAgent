# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project

RisearchAgent — an automated ArXiv research assistant that crawls papers, filters by relevance, performs full-text deep reading via LLM, classifies contributions against a knowledge base, and maintains SOTA benchmark leaderboards.

## Commands

```bash
# Install dependencies (conda env: paper_reader, Python 3.11)
pip install -r requirements.txt

# Environment setup
cp .env.example .env  # set GEMINI_API_KEY

# Run full pipeline
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
python run.py onboard       # interactive config setup
python run.py onboard --refine

# Verbose logging
python run.py -v <command>
```

Experiments should use the `paper_reader` conda environment.

No test suite exists yet — the `tests/` directory contains only an empty `__init__.py`.

## Architecture

### Pipeline (5 stages, all async)

`run.py` → `PipelineOrchestrator` (src/pipeline/orchestrator.py) orchestrates everything:

1. **Crawl** — `ArxivScraper` fetches papers via ArXiv API per topic queries in config.yaml
2. **Filter** — `RelevanceJudge` scores papers 0–10 against per-topic research profiles using Gemini Flash
3. **Deep Read** — `PDFDownloader` extracts text (PyMuPDF, truncated to 20 pages), `DeepReader` runs 3-pass Gemini Pro analysis
4. **Contribution Analysis** — `ContributionAnalyzer` compares against ChromaDB knowledge base, classifies as breakthrough/significant/incremental/marginal
5. **SOTA Update** — `SOTAKnowledgeBase` updates Markdown leaderboard files in `data/sota/`, with LLM-based conflict resolution

### LLM layer

`GeminiClient` (src/llm/gemini_client.py) wraps the `google-genai` SDK. All LLM calls go through it. Key features: async with semaphore-based concurrency control, JSON mode via `response_mime_type`, exponential backoff retry. Two model tiers: Flash for filtering, Pro for deep reading.

### Storage (dual)

- **SQLite** (src/storage/database.py) — structured data: papers, relevance verdicts, deep readings, contribution deltas, SOTA update audit log, pipeline runs. Uses `aiosqlite`. Schema includes automatic migrations.
- **ChromaDB** (src/knowledge/knowledge_base.py) — vector store with 3 collections: `paper_contributions`, `paper_methods`, `research_context`. Uses Gemini embeddings.

### SOTA tracking

`SOTAKnowledgeBase` (src/knowledge/sota_tracker.py) stores benchmark leaderboards as Markdown files in `data/sota/`. Uses LLM to resolve conflicts when papers report different baseline numbers. Database `sota_updates` table serves as an audit log only.

### Data models

All dataclasses live in `src/models.py`: Paper, RelevanceVerdict, DeepReading, ExperimentTable/ExperimentEntry/MethodResult, ContributionDelta, SOTAUpdateReport. The ExperimentTable hierarchy is serialized to JSON for SQLite storage.

### Configuration

`config.yaml` → `load_config()` in src/config.py → `AppConfig` dataclass. LLM API key comes from `GEMINI_API_KEY` env var (loaded via python-dotenv). Topics include ArXiv queries + research profiles for relevance filtering.

### Key patterns

- Every database method opens its own `aiosqlite.connect()` — no connection pooling
- The orchestrator wires all components together; individual modules receive their dependencies via constructor injection
- LLM responses are parsed as JSON (`generate_json`) using Gemini's native JSON mode
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
