import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.models import SearchTopic


DEFAULT_LLM_RESPONSE_FORMAT = "gpt"
DEFAULT_LLM_BASE_URL = "https://api.ikuncode.cc"
DEFAULT_LLM_API_KEY_ENV = "RISEARCHAGENT_API_KEY"
DEFAULT_LLM_MODEL = "gpt-5.6-sol"


@dataclass
class LLMConfig:
    filter_model: str
    reader_model: str
    api_key: str
    max_concurrent: int
    temperature: float
    embedding_model: str = ""  # Legacy pipeline only.
    response_format: str = DEFAULT_LLM_RESPONSE_FORMAT
    base_url: str = DEFAULT_LLM_BASE_URL
    api_key_env: str = DEFAULT_LLM_API_KEY_ENV


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
    response_format = llm_raw.get("response_format", DEFAULT_LLM_RESPONSE_FORMAT)
    default_api_key_env = (
        "GEMINI_API_KEY"
        if response_format == "gemini"
        else DEFAULT_LLM_API_KEY_ENV
    )
    api_key_env = llm_raw.get("api_key_env", default_api_key_env)
    llm = LLMConfig(
        filter_model=llm_raw.get("filter_model", DEFAULT_LLM_MODEL),
        reader_model=llm_raw.get("reader_model", DEFAULT_LLM_MODEL),
        embedding_model=llm_raw.get("embedding_model", ""),
        api_key=os.environ.get(api_key_env, ""),
        max_concurrent=llm_raw.get("max_concurrent", 5),
        temperature=llm_raw.get("temperature", 0.3),
        response_format=response_format,
        base_url=llm_raw.get("base_url", DEFAULT_LLM_BASE_URL),
        api_key_env=api_key_env,
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
