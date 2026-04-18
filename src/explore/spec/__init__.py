"""Spec layer: runtime constraint rules for Planner proposals.

See docs/onboard-redesign/07-spec-rules.md.

Key principle: spec handles ONLY hard invariants (numeric / counter / field
existence). Soft judgments (query choice, direction) belong to Planner.
No LLM predicates — ever.
"""

from src.explore.spec.constants import (
    ACTION_BUDGET_DEFAULT,
    DEADLOCK_ABORT_THRESHOLD,
    DEADLOCK_ESCALATE_THRESHOLD,
    FORCE_CLUSTER_REFRESH_DELTA,
    QUERY_DIVERSITY_THRESHOLD,
    QUERY_DIVERSITY_WINDOW,
    QUERY_WARMUP_POOL_SIZE,
    READ_PAPER_BUDGET_DEFAULT,
    SATURATION_RATIO_THRESHOLD,
    SATURATION_WINDOW,
    TIME_BUDGET_SECONDS_DEFAULT,
)
from src.explore.spec.evaluator import (
    SpecEvaluator,
    SpecPredicateError,
    Verdict,
    VerdictKind,
)
from src.explore.spec.rules import ALL_RULES, Rule

__all__ = [
    "ALL_RULES",
    "Rule",
    "SpecEvaluator",
    "SpecPredicateError",
    "Verdict",
    "VerdictKind",
    # Constants
    "TIME_BUDGET_SECONDS_DEFAULT",
    "ACTION_BUDGET_DEFAULT",
    "READ_PAPER_BUDGET_DEFAULT",
    "QUERY_DIVERSITY_THRESHOLD",
    "QUERY_DIVERSITY_WINDOW",
    "QUERY_WARMUP_POOL_SIZE",
    "SATURATION_RATIO_THRESHOLD",
    "SATURATION_WINDOW",
    "FORCE_CLUSTER_REFRESH_DELTA",
    "DEADLOCK_ESCALATE_THRESHOLD",
    "DEADLOCK_ABORT_THRESHOLD",
]
