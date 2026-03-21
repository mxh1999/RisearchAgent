# RisearchAgent

An automated ArXiv research assistant that reads full papers, tracks state-of-the-art benchmarks, and classifies contributions — so you can focus on the papers that actually matter.

## Why RisearchAgent

Most tools stop at abstract-level summaries. RisearchAgent goes deeper:

- **Full-text deep reading** — Three-pass LLM analysis of complete PDFs, not just abstracts
- **SOTA tracking** — Extracts benchmark results and maintains up-to-date leaderboard tables in Markdown
- **Contribution classification** — Rates papers as breakthrough / significant / incremental / marginal against your existing knowledge base
- **Personalized filtering** — Scores relevance against your research profile, so you only read what's worth reading

## Pipeline

```
ArXiv API ──> Crawl ──> Filter ──> Deep Read ──> Contribute ──> SOTA Update
                         (Gemini Flash)  (Gemini Pro)   (ChromaDB)    (Markdown tables)
```

1. **Crawl** — Fetch papers from ArXiv by configurable topic queries
2. **Filter** — LLM relevance scoring (0–10) against your research profile
3. **Deep Read** — Download PDF, extract text (PyMuPDF), run three-pass LLM analysis
4. **Contribution Analysis** — Compare findings against ChromaDB knowledge base
5. **SOTA Update** — Extract experiment tables and update benchmark leaderboards

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env       # add your GEMINI_API_KEY

# Interactive onboarding — builds your config.yaml via conversation
python run.py onboard

# Or manually edit config.yaml with your research topics
```

## Usage

```bash
# Run the full pipeline (crawl → filter → read → analyze → SOTA)
python run.py pipeline

# Or run stages individually
python run.py crawl                    # fetch new papers
python run.py filter                   # score relevance
python run.py read <arxiv_id>          # deep-read a specific paper

# Knowledge management
python run.py sota                     # view SOTA leaderboards
python run.py stats                    # database statistics
python run.py export [output.json]     # export knowledge for sharing
python run.py import data.json         # import knowledge (--merge to upsert)

# Onboarding
python run.py onboard                  # first-time setup
python run.py onboard --refine         # update existing research profile
```

## Configuration

`config.yaml` controls everything:

| Section | What it does |
|---------|-------------|
| `topics` | ArXiv search queries + per-topic research profile for relevance filtering |
| `llm` | Model selection (Flash/Pro), concurrency, temperature |
| `scraper` | Max results per topic, lookback window in days |
| `filter` | Relevance score thresholds |

## Tech Stack

| Component | Choice |
|-----------|--------|
| LLM | Gemini Flash (filtering) + Pro (deep reading) |
| PDF Extraction | PyMuPDF |
| Vector Store | ChromaDB |
| Database | SQLite via aiosqlite |
| Embeddings | Gemini Embedding |
