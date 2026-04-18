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
    StopAction,
)
from src.explore.spec.constants import (
    DEADLOCK_ABORT_THRESHOLD,
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
]
