# Paper Reader Agent

Automated ArXiv paper reader with full-text analysis, SOTA tracking, and contribution comparison.

## What Makes This Different

Most tools only do summary-level analysis. This project does:
- **Full-text deep reading** — Three-pass LLM analysis of complete papers (not just abstracts)
- **SOTA tracking** — Automatic benchmark extraction and state-of-the-art table maintenance
- **Contribution comparison** — Classifies papers as breakthrough/significant/incremental/marginal against existing knowledge

## Architecture

Five-stage pipeline:

1. **Crawl** — Fetch papers from ArXiv API by configurable topics
2. **Filter** — LLM relevance scoring (0-10) against your research profile
3. **Deep Read** — PDF download → text extraction → three-pass LLM analysis
4. **Contribution Analysis** — Compare against ChromaDB knowledge base
5. **SOTA Update** — Extract benchmarks and update tracking table

## Tech Stack

| Component | Choice |
|-----------|--------|
| LLM | Gemini (Flash for filtering, Pro for reading) |
| PDF Extraction | PyMuPDF |
| Vector Store | ChromaDB |
| Database | SQLite + aiosqlite |
| Embeddings | Google text-embedding-004 |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your GEMINI_API_KEY
# Edit config.yaml with your research topics
```

## Usage

```bash
# Crawl papers from ArXiv
python run.py crawl

# Filter by relevance to your research profile
python run.py filter

# Deep-read a specific paper
python run.py read <arxiv_id>

# Run full pipeline (crawl → filter → read → analyze → SOTA)
python run.py pipeline

# View SOTA tracking table
python run.py sota

# View database statistics
python run.py stats
```

## Configuration

Edit `config.yaml` to define:
- **topics**: ArXiv search queries + your research profile per topic
- **llm**: Model selection, concurrency, temperature
- **scraper**: Results limit, lookback days
- **filter**: Relevance score thresholds

## Future: OpenClaw Integration

Core logic is decoupled from the interaction layer. Planned OpenClaw skill integration for:
- Daily digest push to Telegram/Slack/WhatsApp
- Conversational queries ("What's new in embodied AI?")
- SOTA table queries ("What's the best ObjectNav method?")
