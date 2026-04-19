"""ExplorationState — the Explorer's authoritative data structure.

See docs/onboard-redesign/05-state-schema.md for the full spec.

Derived properties (is_saturated, consecutive_blocked_actions, etc.) live
on ExplorationState and are NOT persisted. All spec predicates and planner
context reads go through these properties, not the raw fields.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from src.explore.actions import Action, action_equal

# —————————————————————————————————————————————————————————————
# Sub-types
# —————————————————————————————————————————————————————————————


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    last_updated_at: datetime
    llm_tier: Literal["production", "budget", "dev"] = "production"
    code_version: str
    status: Literal["running", "completed", "cancelled", "failed"] = "running"
    termination_reason: Optional[str] = None
    citation_provider_degraded: bool = False


class SeedValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
    match_score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    used_as_anchor: bool


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    natural_language: str
    seed_arxiv_ids: list[str] = Field(default_factory=list)
    seed_validation: dict[str, SeedValidation] = Field(default_factory=dict)


class SkimResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmarks: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    skimmed_at: datetime


class PaperRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: date
    categories: list[str]
    pdf_url: str

    # Exploration provenance
    first_seen_turn: int
    source: Literal["search", "citation_expansion", "related", "seed"]
    source_query_id: Optional[str] = None
    source_paper_id: Optional[str] = None

    # Embedding reference (vector itself lives in ChromaDB)
    embedding_id: Optional[str] = None

    # Semantic Scholar signals
    citation_count: Optional[int] = None
    reference_count: Optional[int] = None
    citation_data_fetched_at: Optional[datetime] = None

    # LLM skim (from skim_abstract action)
    skim: Optional[SkimResult] = None

    # Clustering
    cluster_id: Optional[str] = None  # the cluster's slug
    is_noise: bool = False

    # Flags (seed_mismatch, deep_read_candidate, ...)
    flags: list[str] = Field(default_factory=list)


class QueryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str
    turn: int
    query_text: str
    categories: list[str]
    source: Literal[
        "user_intent_rewrite",
        "llm_generated",
        "cluster_targeted",
        "citation_seeded",
        "author_seeded",
        "benchmark_seeded",
        "classic_lookup",
    ]
    targeted_cluster_slug: Optional[str] = None
    query_embedding_id: Optional[str] = None

    n_results_raw: int = 0
    n_new_to_pool: int = 0
    executed_at: datetime


class LLMCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    purpose: str
    input_tokens: int
    output_tokens: int
    duration_ms: int


class ActionRecord(BaseModel):
    """One entry per Planner proposal. Includes blocked/rewritten cases (was_executed=False)."""
    model_config = ConfigDict(extra="forbid")

    turn: int  # only incremented for executed actions
    action: Action  # the action that was actually taken (post-rewrite/force)
    was_executed: bool
    original_proposed_action: Optional[Action] = None  # original before rewrite/force
    spec_verdict: Literal["allow", "block", "rewrite", "warn", "force"]
    spec_feedback: Optional[str] = None
    spec_rules_fired: list[str] = Field(default_factory=list)

    executed_at: Optional[datetime] = None
    outcome: Literal["success", "skipped", "failed", "not_executed"] = "not_executed"
    outcome_summary: str = ""
    duration_ms: int = 0

    llm_calls: list[LLMCallRecord] = Field(default_factory=list)


class Cluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    display_label: str
    description: str

    paper_ids: list[str]
    size: int

    centroid_paper_id: Optional[str] = None
    representative_paper_ids: list[str] = Field(default_factory=list)

    shared_benchmarks: list[str] = Field(default_factory=list)
    top_authors: list[str] = Field(default_factory=list)
    year_range: tuple[int, int]
    density: Literal["dense", "sparse", "mixed"]

    inherited_from_slug: Optional[str] = None  # != slug means it was renamed
    first_seen_in_snapshot: str

    user_edits: list[dict[str, Any]] = Field(default_factory=list)  # EditRecord; kept loose for v1


class ClusterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    generated_at: datetime
    generated_after_turn: int
    n_papers_at_time: int
    algorithm: str = "hdbscan"
    params: dict[str, Any] = Field(default_factory=dict)

    clusters: list[Cluster]
    noise_paper_ids: list[str] = Field(default_factory=list)

    prev_snapshot_id: Optional[str] = None


class Counters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_counter: dict[str, list[str]] = Field(default_factory=dict)
    author_counter: dict[str, list[str]] = Field(default_factory=dict)
    venue_counter: dict[str, list[str]] = Field(default_factory=dict)

    benchmark_aliases: dict[str, str] = Field(default_factory=dict)


class CoverageQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer_available: bool
    evidence: str
    gap_description: Optional[str] = None


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    generated_after_turn: int
    questions: list[CoverageQuestion]
    passes: bool
    unanswered_count: int


class BudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_budget_seconds: int = 900
    elapsed_seconds: float = 0.0

    action_budget: int = 60
    actions_used: int = 0

    read_paper_budget: int = 3
    read_papers_used: int = 0

    llm_tokens_used: dict[str, int] = Field(default_factory=dict)
    llm_cost_estimate_usd: float = 0.0

    semantic_scholar_quota_remaining: Optional[int] = None


# —————————————————————————————————————————————————————————————
# Top-level state
# —————————————————————————————————————————————————————————————


class ExplorationState(BaseModel):
    """The Explorer's authoritative state. Checkpointed per-action as JSON."""
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    metadata: RunMetadata

    intent: Intent
    feedback: Optional[str] = None  # refine mode

    paper_pool: dict[str, PaperRecord] = Field(default_factory=dict)
    query_log: list[QueryRecord] = Field(default_factory=list)
    action_history: list[ActionRecord] = Field(default_factory=list)

    cluster_snapshot: Optional[ClusterSnapshot] = None
    counters: Counters = Field(default_factory=Counters)

    coverage_report: Optional[CoverageReport] = None
    budget: BudgetState = Field(default_factory=BudgetState)

    # —————————————————————————————————————————————————————
    # Transient runtime state (NOT serialized).
    # Orchestrator pre-computes data for spec predicates to read
    # synchronously (e.g., query embedding similarity).
    # —————————————————————————————————————————————————————
    _transient: dict = PrivateAttr(default_factory=dict)

    # —————————————————————————————————————————————————————
    # Derived properties (NOT persisted; spec predicates read these)
    # —————————————————————————————————————————————————————

    @property
    def pool_size(self) -> int:
        return len(self.paper_pool)

    @property
    def turn(self) -> int:
        """Number of actions actually executed (incl. forced/rewritten)."""
        return sum(1 for r in self.action_history if r.was_executed)

    @property
    def consecutive_blocked_actions(self) -> int:
        count = 0
        for record in reversed(self.action_history):
            if not record.was_executed:
                count += 1
            else:
                break
        return count

    def new_paper_ratio_last_n_rounds(self, n: int = 3) -> float:
        """Ratio of new papers brought in by the last n *executed* search-like actions."""
        recent = [r for r in reversed(self.action_history) if r.was_executed][:n]
        # Count new papers attributable to these actions via query_log
        # For M1 we fall back to a simple aggregate from query_log tail
        recent_queries = self.query_log[-n:]
        if not recent_queries:
            return 1.0  # no data yet = treat as "unsaturated"
        total_raw = sum(q.n_results_raw for q in recent_queries)
        total_new = sum(q.n_new_to_pool for q in recent_queries)
        return total_new / total_raw if total_raw > 0 else 0.0

    @property
    def is_saturated(self) -> bool:
        from src.explore.spec.constants import (
            SATURATION_RATIO_THRESHOLD,
            SATURATION_WINDOW,
        )
        return self.new_paper_ratio_last_n_rounds(SATURATION_WINDOW) < SATURATION_RATIO_THRESHOLD

    def papers_since_last_cluster_refresh(self) -> int:
        """How many papers added since the most recent ClusterRefreshAction."""
        if not self.action_history:
            return self.pool_size
        last_refresh_turn = None
        for r in reversed(self.action_history):
            if r.was_executed and r.action.action_type == "cluster_refresh":
                last_refresh_turn = r.turn
                break
        if last_refresh_turn is None:
            return self.pool_size
        return sum(1 for p in self.paper_pool.values() if p.first_seen_turn > last_refresh_turn)

    def previous_executed_action(self) -> Optional[Action]:
        for r in reversed(self.action_history):
            if r.was_executed:
                return r.action
        return None

    def last_action_equal(self, action: Action) -> bool:
        prev = self.previous_executed_action()
        if prev is None:
            return False
        return action_equal(action, prev)

    def recent_query_ids(self, n: int = 3) -> list[str]:
        """Last n query_ids from query_log (for diversity rule pre-compute)."""
        return [q.query_id for q in self.query_log[-n:]]
