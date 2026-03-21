from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SearchTopic:
    """ArXiv search topic with research profile for relevance filtering."""
    name: str
    query: str
    categories: list[str]
    research_profile: str = ""


@dataclass
class Paper:
    """ArXiv paper metadata."""
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    pdf_url: str
    published: datetime
    categories: list[str]
    source_topic: str


@dataclass
class RelevanceVerdict:
    """LLM relevance scoring result."""
    arxiv_id: str
    score: int  # 0-10
    justification: str
    key_topics: list[str]


@dataclass
class BenchmarkResult:
    """A single benchmark result extracted from a paper."""
    benchmark_name: str
    metric_name: str
    value: float
    unit: str
    is_sota: bool = False


@dataclass
class DeepReading:
    """Full-text LLM analysis of a paper."""
    arxiv_id: str
    problem_statement: str
    proposed_method: str
    key_contributions: list[str]
    experimental_setup: str
    main_results: str
    limitations: str
    comparison_to_prior_work: str
    extracted_benchmarks: list[BenchmarkResult] = field(default_factory=list)


@dataclass
class SOTAEntry:
    """State-of-the-art tracking entry."""
    field: str
    benchmark: str
    metric: str
    best_value: float
    best_method: str
    best_paper_id: str
    previous_best_value: Optional[float] = None
    previous_best_method: Optional[str] = None


@dataclass
class ContributionDelta:
    """Contribution comparison against existing knowledge."""
    arxiv_id: str
    novel_contributions: list[str]
    incremental_improvements: list[str]
    contradicts_prior: list[str]
    overall_significance: str  # "breakthrough"|"significant"|"incremental"|"marginal"
