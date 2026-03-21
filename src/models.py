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
class MethodResult:
    """A single method's score on one benchmark+setting+metric."""
    method_name: str
    value: float
    is_paper_method: bool  # True = proposed method, False = baseline


@dataclass
class ExperimentEntry:
    """All methods' results for one benchmark+setting+metric combination."""
    benchmark: str        # e.g. "HM3D ObjectNav"
    setting: str          # e.g. "zero-shot, val unseen"
    metric: str           # e.g. "SR", "SPL"
    higher_is_better: bool
    results: list[MethodResult] = field(default_factory=list)


@dataclass
class ExperimentTable:
    """Complete experiment results extracted from a paper."""
    arxiv_id: str
    entries: list[ExperimentEntry] = field(default_factory=list)
    details: str = ""  # Detailed experiment description (settings, training config, eval protocol, etc.)


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
    experiment_table: Optional[ExperimentTable] = None


@dataclass
class SOTAConflict:
    """A conflict between paper-reported and existing SOTA values."""
    method: str
    metric: str
    paper_value: float
    existing_value: float
    paper_source: str  # arxiv_id that reported existing_value


@dataclass
class SOTAUpdateAction:
    """A single action taken during SOTA update."""
    benchmark: str
    action: str  # "new_entry" | "updated" | "conflict_resolved"
    summary: str


@dataclass
class SOTAUpdateReport:
    """Report from processing one paper's experiment results."""
    arxiv_id: str
    actions: list[SOTAUpdateAction] = field(default_factory=list)
    conflicts_found: int = 0
    conflicts_resolved: int = 0


@dataclass
class ContributionDelta:
    """Contribution comparison against existing knowledge."""
    arxiv_id: str
    novel_contributions: list[str]
    incremental_improvements: list[str]
    contradicts_prior: list[str]
    overall_significance: str  # "breakthrough"|"significant"|"incremental"|"marginal"
