"""Unit tests for the v1 spec rule catalog.

M1 covers 3 rules: read_paper_budget, no_repeated_exact_action, deadlock_abort.
Tests are deterministic — spec is a pure function layer.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.explore.actions import (
    ReadPaperAction,
    SearchAction,
    StopAction,
)
from src.explore.spec import (
    ALL_RULES,
    SpecEvaluator,
    SpecPredicateError,
    Verdict,
)
from src.explore.spec.rules import (
    RULE_ACTION_BUDGET,
    RULE_DEADLOCK_ABORT,
    RULE_NO_REPEATED_EXACT_ACTION,
    RULE_READ_PAPER_BUDGET,
    Rule,
)
from src.explore.state import ActionRecord
from tests.explore.conftest import make_state


# —————————————————————————————————————————————————————————————
# RULE_READ_PAPER_BUDGET
# —————————————————————————————————————————————————————————————


def test_read_paper_budget_blocks_at_limit():
    state = make_state(read_papers_used=3, read_paper_budget=3)
    action = ReadPaperAction(
        arxiv_id="2401.00001",
        reasoning="test: expecting block since budget is exhausted",
    )
    verdict = SpecEvaluator([RULE_READ_PAPER_BUDGET]).evaluate(action, state)
    assert verdict.kind == "block"
    assert verdict.rule_name == "read_paper_budget"
    assert "exhausted" in verdict.feedback


def test_read_paper_budget_allows_below_limit():
    state = make_state(read_papers_used=2, read_paper_budget=3)
    action = ReadPaperAction(
        arxiv_id="2401.00001",
        reasoning="test: expecting allow, 2/3 used",
    )
    verdict = SpecEvaluator([RULE_READ_PAPER_BUDGET]).evaluate(action, state)
    assert verdict.kind == "allow"


def test_read_paper_budget_skips_non_read_actions():
    state = make_state(read_papers_used=3, read_paper_budget=3)
    action = SearchAction(
        query="anything",
        reasoning="test: read budget should not apply to search",
    )
    verdict = SpecEvaluator([RULE_READ_PAPER_BUDGET]).evaluate(action, state)
    assert verdict.kind == "allow"


# —————————————————————————————————————————————————————————————
# RULE_NO_REPEATED_EXACT_ACTION
# —————————————————————————————————————————————————————————————


def _executed_record(action) -> ActionRecord:
    return ActionRecord(
        turn=1,
        action=action,
        was_executed=True,
        spec_verdict="allow",
        executed_at=datetime.now(),
        outcome="success",
    )


def test_no_repeated_action_allows_first():
    state = make_state()
    action = SearchAction(
        query="vision language navigation",
        reasoning="test: first ever action should pass",
    )
    verdict = SpecEvaluator([RULE_NO_REPEATED_EXACT_ACTION]).evaluate(action, state)
    assert verdict.kind == "allow"


def test_no_repeated_action_blocks_duplicate():
    state = make_state()
    first = SearchAction(
        query="vision language navigation",
        reasoning="test: this is the first action",
    )
    state.action_history.append(_executed_record(first))
    # Same args, different reasoning — should still block
    duplicate = SearchAction(
        query="vision language navigation",
        reasoning="test: duplicate submission with different rationale",
    )
    verdict = SpecEvaluator([RULE_NO_REPEATED_EXACT_ACTION]).evaluate(duplicate, state)
    assert verdict.kind == "block"
    assert verdict.rule_name == "no_repeated_exact_action"


def test_no_repeated_action_allows_differing_args():
    state = make_state()
    first = SearchAction(
        query="vision language navigation",
        reasoning="test: first action for comparison",
    )
    state.action_history.append(_executed_record(first))
    different = SearchAction(
        query="embodied manipulation benchmarks",
        reasoning="test: different query should pass",
    )
    verdict = SpecEvaluator([RULE_NO_REPEATED_EXACT_ACTION]).evaluate(different, state)
    assert verdict.kind == "allow"


# —————————————————————————————————————————————————————————————
# RULE_DEADLOCK_ABORT
# —————————————————————————————————————————————————————————————


def _blocked_record(idx: int) -> ActionRecord:
    return ActionRecord(
        turn=0,
        action=SearchAction(
            query=f"blocked-{idx}",
            reasoning="test filler for blocked history entry",
        ),
        was_executed=False,
        spec_verdict="block",
        spec_feedback="test",
        outcome="not_executed",
    )


def test_deadlock_abort_inactive_below_threshold():
    state = make_state()
    for i in range(7):  # threshold is 8
        state.action_history.append(_blocked_record(i))
    action = SearchAction(query="any", reasoning="test filler")
    verdict = SpecEvaluator([RULE_DEADLOCK_ABORT]).evaluate(action, state)
    assert verdict.kind == "allow"


def test_deadlock_abort_triggers_at_threshold():
    state = make_state()
    for i in range(8):
        state.action_history.append(_blocked_record(i))
    action = SearchAction(query="any", reasoning="test filler")
    verdict = SpecEvaluator([RULE_DEADLOCK_ABORT]).evaluate(action, state)
    assert verdict.kind == "force"
    assert verdict.rule_name == "deadlock_abort"
    assert verdict.forced_action is not None
    assert verdict.forced_action.action_type == "stop"


def test_deadlock_counter_resets_after_executed_action():
    state = make_state()
    for i in range(8):
        state.action_history.append(_blocked_record(i))
    # An executed action in between resets the consecutive counter
    state.action_history.append(
        _executed_record(SearchAction(query="ok", reasoning="test filler"))
    )
    assert state.consecutive_blocked_actions == 0
    action = SearchAction(query="any", reasoning="test filler")
    verdict = SpecEvaluator([RULE_DEADLOCK_ABORT]).evaluate(action, state)
    assert verdict.kind == "allow"


# —————————————————————————————————————————————————————————————
# RULE_ACTION_BUDGET
# —————————————————————————————————————————————————————————————


def test_action_budget_inactive_below_limit():
    state = make_state(actions_used=59, action_budget=60)
    action = SearchAction(query="any", reasoning="test filler for action_budget")
    verdict = SpecEvaluator([RULE_ACTION_BUDGET]).evaluate(action, state)
    assert verdict.kind == "allow"


def test_action_budget_forces_stop_at_limit():
    state = make_state(actions_used=60, action_budget=60)
    action = SearchAction(query="any", reasoning="test filler for action_budget")
    verdict = SpecEvaluator([RULE_ACTION_BUDGET]).evaluate(action, state)
    assert verdict.kind == "force"
    assert verdict.rule_name == "action_budget"
    assert verdict.forced_action is not None
    assert verdict.forced_action.action_type == "stop"
    assert verdict.forced_action.claimed_reason == "budget_exhausted"


def test_action_budget_applies_even_to_stop_proposal():
    """Even if Planner proposes stop, action_budget still fires first (both force stop anyway)."""
    state = make_state(actions_used=60, action_budget=60)
    action = StopAction(
        claimed_reason="saturated",
        reasoning="test: planner proposes stop when budget also exhausted",
    )
    verdict = SpecEvaluator([RULE_ACTION_BUDGET]).evaluate(action, state)
    # rule applies_to=None so it still fires
    assert verdict.kind == "force"


# —————————————————————————————————————————————————————————————
# Arbitration: most-severe wins
# —————————————————————————————————————————————————————————————


def test_deadlock_abort_beats_read_paper_budget():
    """When both rules fire, deadlock_abort (force, severity 25) wins."""
    state = make_state(read_papers_used=3, read_paper_budget=3)
    for i in range(8):
        state.action_history.append(_blocked_record(i))

    action = ReadPaperAction(
        arxiv_id="2401.00001",
        reasoning="test: both rules should fire here",
    )
    verdict = SpecEvaluator(
        [RULE_READ_PAPER_BUDGET, RULE_DEADLOCK_ABORT]
    ).evaluate(action, state)

    assert verdict.kind == "force"
    assert verdict.rule_name == "deadlock_abort"
    # Both rules should appear in all_fired_rules
    assert "deadlock_abort" in verdict.all_fired_rules
    assert "read_paper_budget" in verdict.all_fired_rules


# —————————————————————————————————————————————————————————————
# fail_policy behavior
# —————————————————————————————————————————————————————————————


def test_fail_policy_abort_propagates():
    bad_rule = Rule(
        name="buggy",
        description="intentionally broken predicate",
        applies_to=None,
        predicates=[lambda s, a: s.nonexistent_field],  # type: ignore[attr-defined]
        verdict_fn=lambda s, a: Verdict(kind="block", rule_name="buggy"),
        fail_policy="abort",
    )
    action = SearchAction(query="any", reasoning="test filler")
    with pytest.raises(SpecPredicateError):
        SpecEvaluator([bad_rule]).evaluate(action, make_state())


def test_fail_policy_skip_silently_ignores_rule():
    bad_rule = Rule(
        name="buggy",
        description="intentionally broken predicate",
        applies_to=None,
        predicates=[lambda s, a: s.nonexistent_field],  # type: ignore[attr-defined]
        verdict_fn=lambda s, a: Verdict(kind="block", rule_name="buggy"),
        fail_policy="skip",
    )
    action = SearchAction(query="any", reasoning="test filler")
    verdict = SpecEvaluator([bad_rule]).evaluate(action, make_state())
    assert verdict.kind == "allow"


# —————————————————————————————————————————————————————————————
# Registry sanity
# —————————————————————————————————————————————————————————————


def test_all_rules_registry_contains_m1_m2_rules():
    names = {r.name for r in ALL_RULES}
    assert {
        "read_paper_budget",
        "no_repeated_exact_action",
        "deadlock_abort",
        "action_budget",
    } <= names


def test_all_rules_have_unique_names():
    names = [r.name for r in ALL_RULES]
    assert len(names) == len(set(names))
