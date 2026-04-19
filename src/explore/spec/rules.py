"""Spec rule catalog.

M1 subset:
  - read_paper_budget (budget enforcement)
  - no_repeated_exact_action (anti-loop)
  - deadlock_abort (escape hatch for rule deadlock)

M2 additions:
  - action_budget (hard stop on total action count — safe early-stopping
    for real runs before saturation-based stop rules land in M4)

Remaining rules (time_budget, query_diversity, query_must_be_specific_after_warmup,
no_premature_stop_saturation, no_premature_stop_coverage,
force_cluster_refresh_on_pool_growth, require_coverage_audit_before_stop,
deadlock_escalate) arrive in later milestones as their state dependencies
(clustering, coverage audit, query embeddings) are built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal, Optional

from src.explore.actions import (
    CoverageAuditAction,
    ReadPaperAction,
    SearchAction,
    StopAction,
)
from src.explore.spec.constants import (
    DEADLOCK_ABORT_THRESHOLD,
    QUERY_DIVERSITY_THRESHOLD,
    QUERY_WARMUP_POOL_SIZE,
    READ_PAPER_BUDGET_DEFAULT,
)
from src.explore.spec.evaluator import Verdict

if TYPE_CHECKING:
    from src.explore.actions import Action
    from src.explore.state import ExplorationState


Predicate = Callable[["ExplorationState", "Action"], bool]


@dataclass
class Rule:
    """A spec rule: trigger + predicates + verdict constructor."""
    name: str
    description: str
    applies_to: Optional[list[type]] = None  # None = any Action subclass
    predicates: list[Predicate] = field(default_factory=list)
    verdict_fn: Callable[["ExplorationState", "Action"], Verdict] = None  # type: ignore[assignment]
    severity: int = 0
    fail_policy: Literal["abort", "skip"] = "abort"


# —————————————————————————————————————————————————————————————
# Predicate helpers (will move to src/explore/spec/predicates/ once library grows)
# —————————————————————————————————————————————————————————————


def _read_paper_budget_exceeded(state, action) -> bool:
    return state.budget.read_papers_used >= state.budget.read_paper_budget


def _action_budget_exceeded(state, action) -> bool:
    return state.budget.actions_used >= state.budget.action_budget


def _action_equals_previous_executed(state, action) -> bool:
    return state.last_action_equal(action)


def _consecutive_blocked_geq_abort(state, action) -> bool:
    return state.consecutive_blocked_actions >= DEADLOCK_ABORT_THRESHOLD


def _query_too_similar_to_recent(state, action) -> bool:
    """Reads state._transient['query_max_similarity'] set by orchestrator pre-eval.

    Returns True if the proposed query is too similar to recent queries.
    If similarity wasn't pre-computed (no embedding_store configured), treats
    as not-similar so the rule doesn't fire spuriously.
    """
    if not isinstance(action, SearchAction):
        return False
    sim = state._transient.get("query_max_similarity")
    if sim is None:
        return False
    return sim > QUERY_DIVERSITY_THRESHOLD


def _query_must_be_specific_after_warmup(state, action) -> bool:
    """After pool > warmup size, search must be targeted or use a specific source_tag."""
    if not isinstance(action, SearchAction):
        return False
    if state.pool_size <= QUERY_WARMUP_POOL_SIZE:
        return False
    is_broad = action.targeted_cluster_slug is None and action.source_tag in (
        "llm_generated",
        "user_intent_rewrite",
    )
    return is_broad


# —————————————————————————————————————————————————————————————
# Rule definitions
# —————————————————————————————————————————————————————————————


RULE_READ_PAPER_BUDGET = Rule(
    name="read_paper_budget",
    description="read_paper is capped at budget.read_paper_budget (default 3).",
    applies_to=[ReadPaperAction],
    predicates=[_read_paper_budget_exceeded],
    verdict_fn=lambda state, action: Verdict(
        kind="block",
        rule_name="read_paper_budget",
        feedback=(
            f"read_paper budget exhausted "
            f"({state.budget.read_papers_used}/{state.budget.read_paper_budget}). "
            f"Consider skim_abstract or coverage_audit instead."
        ),
    ),
    severity=10,
    fail_policy="abort",
)


RULE_NO_REPEATED_EXACT_ACTION = Rule(
    name="no_repeated_exact_action",
    description="Block actions structurally identical to the previous executed action.",
    applies_to=None,
    predicates=[_action_equals_previous_executed],
    verdict_fn=lambda state, action: Verdict(
        kind="block",
        rule_name="no_repeated_exact_action",
        feedback=(
            "This is structurally identical to your previous action. "
            "Try a different action type or different args."
        ),
    ),
    severity=3,
    fail_policy="abort",
)


RULE_QUERY_DIVERSITY = Rule(
    name="query_diversity",
    description=(
        "Block SearchAction whose query cosine-similarity to any of the "
        "most recent queries exceeds QUERY_DIVERSITY_THRESHOLD. Similarity "
        "is pre-computed by the orchestrator into state._transient."
    ),
    applies_to=[SearchAction],
    predicates=[_query_too_similar_to_recent],
    verdict_fn=lambda state, action: Verdict(
        kind="block",
        rule_name="query_diversity",
        feedback=(
            f"Query too similar to recent searches "
            f"(max cosine={state._transient.get('query_max_similarity', 0):.2f}, "
            f"threshold={QUERY_DIVERSITY_THRESHOLD}). Try a different angle: "
            f"target an under-explored cluster, use author/benchmark seeding, "
            f"or lookup classics."
        ),
    ),
    severity=5,
    fail_policy="skip",  # soft signal; if pre-compute fails, don't block run
)


RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP = Rule(
    name="query_must_be_specific_after_warmup",
    description=(
        f"After pool > {QUERY_WARMUP_POOL_SIZE} papers, a SearchAction must "
        f"target a specific cluster (targeted_cluster_slug) or use a "
        f"non-broad source_tag (classic_lookup / benchmark_seeded)."
    ),
    applies_to=[SearchAction],
    predicates=[_query_must_be_specific_after_warmup],
    verdict_fn=lambda state, action: Verdict(
        kind="block",
        rule_name="query_must_be_specific_after_warmup",
        feedback=(
            f"Pool has {state.pool_size} papers; broad searches no longer add "
            f"value. Target a specific cluster (via targeted_cluster_slug) or "
            f"use source_tag='classic_lookup' / 'benchmark_seeded'."
        ),
    ),
    severity=5,
    fail_policy="skip",
)


RULE_ACTION_BUDGET = Rule(
    name="action_budget",
    description=(
        "Total action count cap. Forces a stop when budget.actions_used >= "
        "budget.action_budget. Safe default early-stopper for real runs "
        "before saturation-based stop rules (M4) exist."
    ),
    applies_to=None,
    predicates=[_action_budget_exceeded],
    verdict_fn=lambda state, action: Verdict(
        kind="force",
        rule_name="action_budget",
        feedback=(
            f"Action budget exhausted "
            f"({state.budget.actions_used}/{state.budget.action_budget}). "
            f"Forcing stop."
        ),
        forced_action=StopAction(
            claimed_reason="budget_exhausted",
            reasoning="forced by action_budget rule",
        ),
    ),
    severity=20,
    fail_policy="abort",
)


RULE_DEADLOCK_ABORT = Rule(
    name="deadlock_abort",
    description=(
        f"After {DEADLOCK_ABORT_THRESHOLD} consecutive blocks, abort the run "
        f"— this indicates a spec design issue."
    ),
    applies_to=None,
    predicates=[_consecutive_blocked_geq_abort],
    verdict_fn=lambda state, action: Verdict(
        kind="force",
        rule_name="deadlock_abort",
        feedback=(
            f"Rule deadlock detected after {DEADLOCK_ABORT_THRESHOLD} consecutive blocks. "
            f"Aborting for inspection."
        ),
        forced_action=StopAction(
            claimed_reason="budget_exhausted",
            reasoning="aborted by deadlock_abort: too many consecutive blocked proposals",
        ),
    ),
    severity=25,  # highest: must beat all other rules (incl. stop-blocking rules)
    fail_policy="abort",
)


# —————————————————————————————————————————————————————————————
# Registry
# —————————————————————————————————————————————————————————————


ALL_RULES: list[Rule] = [
    # M1 subset
    RULE_READ_PAPER_BUDGET,
    RULE_NO_REPEATED_EXACT_ACTION,
    RULE_DEADLOCK_ABORT,
    # M2 additions
    RULE_ACTION_BUDGET,
    RULE_QUERY_DIVERSITY,
    RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP,
]
