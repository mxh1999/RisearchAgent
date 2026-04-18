"""Spec evaluator: runs all rules against a proposed action, arbitrates verdicts.

See docs/onboard-redesign/07-spec-rules.md sections "Verdict 仲裁" and "SpecEvaluator".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal, Optional

if TYPE_CHECKING:
    from src.explore.actions import Action
    from src.explore.spec.rules import Rule
    from src.explore.state import ExplorationState


logger = logging.getLogger(__name__)

VerdictKind = Literal["allow", "block", "rewrite", "warn", "force"]

VERDICT_KIND_SEVERITY: dict[str, int] = {
    "force": 4,
    "block": 3,
    "rewrite": 2,
    "warn": 1,
    "allow": 0,
}


@dataclass
class Verdict:
    """Spec's decision on a proposed action."""
    kind: VerdictKind
    rule_name: str
    feedback: Optional[str] = None
    rewritten_action: Optional["Action"] = None
    forced_action: Optional["Action"] = None
    all_fired_rules: list[str] = field(default_factory=list)


class SpecPredicateError(Exception):
    """Raised when a rule with fail_policy='abort' hits a predicate exception."""

    def __init__(self, rule_name: str, inner: Exception):
        self.rule_name = rule_name
        self.inner = inner
        super().__init__(f"Predicate of rule '{rule_name}' raised: {inner}")


class SpecEvaluator:
    """Evaluates Planner proposals against the rule catalog.

    Per-run instance; no cross-run state. Reads state + action, produces Verdict.
    Never mutates state.
    """

    def __init__(self, rules: list["Rule"]):
        self.rules = rules

    def evaluate(self, action: "Action", state: "ExplorationState") -> Verdict:
        fired: list[tuple["Rule", Verdict]] = []

        for rule in self.rules:
            # 1. Trigger matching
            if rule.applies_to is not None:
                if not any(isinstance(action, t) for t in rule.applies_to):
                    continue

            # 2. Predicate evaluation (AND across predicates)
            try:
                if not all(p(state, action) for p in rule.predicates):
                    continue
            except Exception as e:
                if rule.fail_policy == "abort":
                    raise SpecPredicateError(rule.name, e) from e
                logger.warning(
                    "Rule %s predicate raised (fail_policy=skip): %s", rule.name, e
                )
                continue

            # 3. Construct verdict
            fired.append((rule, rule.verdict_fn(state, action)))

        # 4. Arbitration
        if not fired:
            return Verdict(kind="allow", rule_name="__default__")

        fired.sort(
            key=lambda rv: (
                -VERDICT_KIND_SEVERITY[rv[1].kind],
                -rv[0].severity,
                rv[0].name,
            )
        )

        winner_rule, winner_verdict = fired[0]
        winner_verdict.all_fired_rules = [r.name for r, _ in fired]
        return winner_verdict
