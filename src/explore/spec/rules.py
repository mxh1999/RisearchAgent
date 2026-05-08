"""Spec rule catalog.

M1: read_paper_budget, no_repeated_exact_action, deadlock_abort.
M2: action_budget, time_budget, query_diversity,
    query_must_be_specific_after_warmup.
M3: force_cluster_refresh_on_pool_growth.
M4: no_premature_stop_saturation, no_premature_stop_coverage,
    require_coverage_audit_before_stop, deadlock_escalate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal, Optional

from src.explore.actions import (
    ClusterRefreshAction,
    CoverageAuditAction,
    ReadPaperAction,
    SearchAction,
    StopAction,
)
from src.explore.spec.constants import (
    DEADLOCK_ABORT_THRESHOLD,
    DEADLOCK_ESCALATE_THRESHOLD,
    FORCE_CLUSTER_REFRESH_DELTA,
    QUERY_DIVERSITY_THRESHOLD,
    QUERY_WARMUP_POOL_SIZE,
    READ_PAPER_BUDGET_DEFAULT,
    SATURATION_RATIO_THRESHOLD,
    SATURATION_WINDOW,
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


def _time_budget_exceeded(state, action) -> bool:
    """Wall-clock budget hit. orchestrator updates elapsed_seconds at the top
    of every loop iteration before planner.propose, so this predicate sees
    fresh data."""
    return state.budget.elapsed_seconds >= state.budget.time_budget_seconds


def _action_equals_previous_executed(state, action) -> bool:
    return state.last_action_equal(action)


def _consecutive_blocked_geq_abort(state, action) -> bool:
    return state.consecutive_blocked_actions >= DEADLOCK_ABORT_THRESHOLD


def _action_is_not_cluster_refresh(state, action) -> bool:
    return not isinstance(action, ClusterRefreshAction)


def _pool_grew_since_last_refresh(state, action) -> bool:
    return state.papers_since_last_cluster_refresh() >= FORCE_CLUSTER_REFRESH_DELTA


def _not_saturated(state, action) -> bool:
    return not state.is_saturated


def _coverage_report_fails(state, action) -> bool:
    """Coverage audit ran but didn't pass.

    NB: deliberately split from `coverage_report is None` so this rule and
    REQUIRE_COVERAGE_AUDIT_BEFORE_STOP fire on disjoint conditions.
    """
    return (
        state.coverage_report is not None
        and state.coverage_report.unanswered_count > 0
    )


def _no_coverage_report(state, action) -> bool:
    return state.coverage_report is None


def _consecutive_blocked_geq_escalate(state, action) -> bool:
    return state.consecutive_blocked_actions >= DEADLOCK_ESCALATE_THRESHOLD


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


RULE_TIME_BUDGET = Rule(
    name="time_budget",
    description=(
        "Wall-clock cap. Forces a stop when budget.elapsed_seconds >= "
        "budget.time_budget_seconds. Without this, a 200-action run with "
        "expensive Pro calls overshoots the wall-clock budget by ~30-50%; "
        "action_budget alone is not sufficient."
    ),
    applies_to=None,
    predicates=[_time_budget_exceeded],
    verdict_fn=lambda state, action: Verdict(
        kind="force",
        rule_name="time_budget",
        feedback=(
            f"Time budget exhausted "
            f"({state.budget.elapsed_seconds:.0f}s/"
            f"{state.budget.time_budget_seconds}s). "
            f"Forcing stop."
        ),
        forced_action=StopAction(
            claimed_reason="budget_exhausted",
            reasoning="forced by time_budget rule",
        ),
    ),
    severity=20,
    fail_policy="abort",
)


RULE_NO_PREMATURE_STOP_SATURATION = Rule(
    name="no_premature_stop_saturation",
    description=(
        f"Block StopAction when the pool is not yet saturated "
        f"(new_paper_ratio over last {SATURATION_WINDOW} queries >= "
        f"{SATURATION_RATIO_THRESHOLD})."
    ),
    applies_to=[StopAction],
    predicates=[_not_saturated],
    verdict_fn=lambda state, action: Verdict(
        kind="block",
        rule_name="no_premature_stop_saturation",
        feedback=(
            f"Not saturated yet. new_paper_ratio over last "
            f"{SATURATION_WINDOW} queries = "
            f"{state.new_paper_ratio_last_n_rounds(SATURATION_WINDOW):.2f}, "
            f"target < {SATURATION_RATIO_THRESHOLD:.2f}. Keep exploring "
            f"(targeted searches, classic_lookup, fetch_citations on hubs)."
        ),
    ),
    severity=8,
    fail_policy="abort",
)


RULE_NO_PREMATURE_STOP_COVERAGE = Rule(
    name="no_premature_stop_coverage",
    description=(
        "Block StopAction when coverage_audit ran but unanswered_count > 0. "
        "(The 'never ran' case is handled by REQUIRE_COVERAGE_AUDIT_BEFORE_STOP.)"
    ),
    applies_to=[StopAction],
    predicates=[_coverage_report_fails],
    verdict_fn=lambda state, action: Verdict(
        kind="block",
        rule_name="no_premature_stop_coverage",
        feedback=(
            f"Coverage audit reports {state.coverage_report.unanswered_count} "
            f"unanswered question(s). Fill the gaps then re-audit. "
            f"Gaps: "
            + " | ".join(
                q.gap_description
                for q in (state.coverage_report.questions if state.coverage_report else [])
                if not q.answer_available and q.gap_description
            )
        ),
    ),
    severity=8,
    fail_policy="abort",
)


RULE_REQUIRE_COVERAGE_AUDIT_BEFORE_STOP = Rule(
    name="require_coverage_audit_before_stop",
    description=(
        "When StopAction is proposed but coverage_audit has never been run, "
        "rewrite the action to a CoverageAuditAction so the audit runs before "
        "any stop decision."
    ),
    applies_to=[StopAction],
    predicates=[_no_coverage_report],
    verdict_fn=lambda state, action: Verdict(
        kind="rewrite",
        rule_name="require_coverage_audit_before_stop",
        feedback=(
            "No coverage_audit on record. Running an audit first to surface "
            "any uncovered sub-areas before allowing stop."
        ),
        rewritten_action=CoverageAuditAction(
            reasoning="forced rewrite from stop by require_coverage_audit_before_stop"
        ),
    ),
    severity=9,
    fail_policy="abort",
)


RULE_DEADLOCK_ESCALATE = Rule(
    name="deadlock_escalate",
    description=(
        f"After {DEADLOCK_ESCALATE_THRESHOLD} consecutive blocked proposals, "
        f"force a coverage_audit so the planner sees fresh structural feedback "
        f"and can break the loop."
    ),
    applies_to=None,
    predicates=[_consecutive_blocked_geq_escalate],
    verdict_fn=lambda state, action: Verdict(
        kind="force",
        rule_name="deadlock_escalate",
        feedback=(
            f"{state.consecutive_blocked_actions} consecutive proposals blocked. "
            f"Forcing coverage_audit to expose gaps; review the report and try a "
            f"different angle next turn."
        ),
        forced_action=CoverageAuditAction(
            reasoning="forced by deadlock_escalate after consecutive blocks"
        ),
    ),
    severity=18,  # higher than block-rules but lower than deadlock_abort (25)
    fail_policy="abort",
)


RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH = Rule(
    name="force_cluster_refresh_on_pool_growth",
    description=(
        f"When the pool has grown by >= {FORCE_CLUSTER_REFRESH_DELTA} papers "
        f"since the last cluster_refresh, force one before the next non-refresh "
        f"action so subsequent decisions read a fresh snapshot."
    ),
    applies_to=None,
    predicates=[_action_is_not_cluster_refresh, _pool_grew_since_last_refresh],
    verdict_fn=lambda state, action: Verdict(
        kind="force",
        rule_name="force_cluster_refresh_on_pool_growth",
        feedback=(
            f"Pool grew by {state.papers_since_last_cluster_refresh()} papers "
            f"since last cluster_refresh; clustering view is stale. "
            f"Refreshing first."
        ),
        forced_action=ClusterRefreshAction(
            reasoning="forced by force_cluster_refresh_on_pool_growth",
            force=False,
        ),
    ),
    severity=15,
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
    RULE_TIME_BUDGET,
    RULE_QUERY_DIVERSITY,
    RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP,
    # M3 additions
    RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH,
    # M4 additions
    RULE_NO_PREMATURE_STOP_SATURATION,
    RULE_NO_PREMATURE_STOP_COVERAGE,
    RULE_REQUIRE_COVERAGE_AUDIT_BEFORE_STOP,
    RULE_DEADLOCK_ESCALATE,
]
