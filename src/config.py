import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.models import SearchTopic


@dataclass
class LLMConfig:
    filter_model: str
    reader_model: str
    embedding_model: str
    api_key: str
    max_concurrent: int
    temperature: float


@dataclass
class ScraperConfig:
    max_results_per_topic: int
    delay_seconds: float
    days_lookback: int


@dataclass
class FilterConfig:
    relevance_threshold: int
    borderline_min: int


@dataclass
class AppConfig:
    topics: list[SearchTopic]
    llm: LLMConfig
    scraper: ScraperConfig
    filter: FilterConfig
    db_path: Path
    chroma_path: Path
    pdf_dir: Path
    sota_dir: Path


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Load configuration from YAML file + environment variables."""
    load_dotenv()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    topics = [
        SearchTopic(
            name=t["name"],
            query=t["query"],
            categories=t.get("categories", []),
            research_profile=t.get("research_profile", ""),
        )
        for t in raw["topics"]
    ]

    llm_raw = raw["llm"]
    llm = LLMConfig(
        filter_model=llm_raw.get("filter_model", "gemini-2.5-flash"),
        reader_model=llm_raw.get("reader_model", "gemini-2.5-pro"),
        embedding_model=llm_raw.get("embedding_model", "text-embedding-004"),
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        max_concurrent=llm_raw.get("max_concurrent", 5),
        temperature=llm_raw.get("temperature", 0.3),
    )

    scraper_raw = raw.get("scraper", {})
    scraper = ScraperConfig(
        max_results_per_topic=scraper_raw.get("max_results_per_topic", 50),
        delay_seconds=scraper_raw.get("delay_seconds", 3.0),
        days_lookback=scraper_raw.get("days_lookback", 7),
    )

    filter_raw = raw.get("filter", {})
    filter_cfg = FilterConfig(
        relevance_threshold=filter_raw.get("relevance_threshold", 6),
        borderline_min=filter_raw.get("borderline_min", 4),
    )

    return AppConfig(
        topics=topics,
        llm=llm,
        scraper=scraper,
        filter=filter_cfg,
        db_path=Path(raw.get("db_path", "data/papers.db")),
        chroma_path=Path(raw.get("chroma_path", "data/chroma")),
        pdf_dir=Path(raw.get("pdf_dir", "data/pdfs")),
        sota_dir=Path(raw.get("sota_dir", "data/sota")),
    )
