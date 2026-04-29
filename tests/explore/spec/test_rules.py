"""Unit tests for the v1 spec rule catalog.

M1 covers 3 rules: read_paper_budget, no_repeated_exact_action, deadlock_abort.
Tests are deterministic — spec is a pure function layer.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.explore.actions import (
    ClusterRefreshAction,
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
    RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH,
    RULE_NO_REPEATED_EXACT_ACTION,
    RULE_QUERY_DIVERSITY,
    RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP,
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
# RULE_QUERY_DIVERSITY  (M2 step 2)
# —————————————————————————————————————————————————————————————


def test_query_diversity_skips_when_not_precomputed():
    """If orchestrator didn't pre-compute similarity, rule is a no-op."""
    state = make_state()
    # state._transient is empty
    action = SearchAction(query="any", reasoning="test filler for diversity")
    verdict = SpecEvaluator([RULE_QUERY_DIVERSITY]).evaluate(action, state)
    assert verdict.kind == "allow"


def test_query_diversity_allows_when_similarity_low():
    state = make_state()
    state._transient["query_max_similarity"] = 0.5
    action = SearchAction(query="any", reasoning="test filler for diversity")
    verdict = SpecEvaluator([RULE_QUERY_DIVERSITY]).evaluate(action, state)
    assert verdict.kind == "allow"


def test_query_diversity_blocks_when_similarity_high():
    state = make_state()
    state._transient["query_max_similarity"] = 0.95  # > 0.92 threshold
    action = SearchAction(query="any", reasoning="test filler for diversity")
    verdict = SpecEvaluator([RULE_QUERY_DIVERSITY]).evaluate(action, state)
    assert verdict.kind == "block"
    assert verdict.rule_name == "query_diversity"
    assert "0.95" in verdict.feedback


def test_query_diversity_skips_non_search_actions():
    state = make_state()
    state._transient["query_max_similarity"] = 0.99
    # Non-search action shouldn't be affected even if similarity field is high
    action = ReadPaperAction(
        arxiv_id="2401.00001", reasoning="test filler for diversity"
    )
    verdict = SpecEvaluator([RULE_QUERY_DIVERSITY]).evaluate(action, state)
    assert verdict.kind == "allow"


# —————————————————————————————————————————————————————————————
# RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP  (M2 step 2)
# —————————————————————————————————————————————————————————————


def _state_with_pool_size(n: int):
    """Helper: make a state whose pool_size == n (cheap synthetic entries)."""
    from datetime import date
    from src.explore.state import PaperRecord

    state = make_state()
    for i in range(n):
        aid = f"2401.{i:05d}"
        state.paper_pool[aid] = PaperRecord(
            arxiv_id=aid,
            title=f"Paper {i}",
            abstract="stub",
            authors=["A"],
            published=date(2024, 1, 1),
            categories=["cs.AI"],
            pdf_url="",
            first_seen_turn=1,
            source="search",
            is_noise=False,
        )
    return state


def test_warmup_rule_inactive_below_threshold():
    """pool_size <= QUERY_WARMUP_POOL_SIZE (50): broad search is allowed."""
    state = _state_with_pool_size(50)  # on the boundary (not strictly >)
    action = SearchAction(
        query="navigation", reasoning="test: still warming up"
    )
    verdict = SpecEvaluator(
        [RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP]
    ).evaluate(action, state)
    assert verdict.kind == "allow"


def test_warmup_rule_blocks_broad_search_after_warmup():
    state = _state_with_pool_size(51)
    action = SearchAction(
        query="navigation",
        source_tag="llm_generated",
        reasoning="test: broad search after warmup",
    )
    verdict = SpecEvaluator(
        [RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP]
    ).evaluate(action, state)
    assert verdict.kind == "block"
    assert verdict.rule_name == "query_must_be_specific_after_warmup"


def test_warmup_rule_allows_targeted_cluster_after_warmup():
    state = _state_with_pool_size(80)
    action = SearchAction(
        query="vln-ce recent methods",
        source_tag="cluster_targeted",
        targeted_cluster_slug="vln-ce",
        reasoning="test: targeted search",
    )
    verdict = SpecEvaluator(
        [RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP]
    ).evaluate(action, state)
    assert verdict.kind == "allow"


def test_warmup_rule_allows_classic_lookup_after_warmup():
    state = _state_with_pool_size(80)
    action = SearchAction(
        query="slam 2018 2021",
        source_tag="classic_lookup",
        reasoning="test: classic lookup source_tag exempts the rule",
    )
    verdict = SpecEvaluator(
        [RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP]
    ).evaluate(action, state)
    assert verdict.kind == "allow"


def test_warmup_rule_allows_benchmark_seeded_after_warmup():
    state = _state_with_pool_size(80)
    action = SearchAction(
        query="HM3D benchmark",
        source_tag="benchmark_seeded",
        reasoning="test: benchmark seeded source_tag exempts the rule",
    )
    verdict = SpecEvaluator(
        [RULE_QUERY_MUST_BE_SPECIFIC_AFTER_WARMUP]
    ).evaluate(action, state)
    assert verdict.kind == "allow"


# —————————————————————————————————————————————————————————————
# RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH  (M3)
# —————————————————————————————————————————————————————————————


def _state_with_papers_after_refresh(
    n_after: int, prev_refresh_turn: int = 1
):
    """State whose action_history contains a refresh at turn `prev_refresh_turn`,
    then `n_after` new papers added at later turns."""
    from datetime import date
    from src.explore.state import ActionRecord, PaperRecord

    state = make_state()
    # Synthesize an executed cluster_refresh record at turn=prev_refresh_turn
    state.action_history.append(
        ActionRecord(
            turn=prev_refresh_turn,
            action=ClusterRefreshAction(reasoning="prior refresh in fixture"),
            was_executed=True,
            spec_verdict="allow",
            outcome="success",
            outcome_summary="prior refresh",
        )
    )
    # Add papers with first_seen_turn > prev_refresh_turn
    for i in range(n_after):
        aid = f"24{i:04d}.{i:05d}"
        state.paper_pool[aid] = PaperRecord(
            arxiv_id=aid,
            title=f"Paper {i}",
            abstract="stub",
            authors=["A"],
            published=date(2024, 1, 1),
            categories=["cs.AI"],
            pdf_url="",
            first_seen_turn=prev_refresh_turn + 1,  # strictly after refresh
            source="search",
        )
    return state


def test_force_cluster_refresh_inactive_when_growth_below_threshold():
    state = _state_with_papers_after_refresh(n_after=14)  # < 15 threshold
    action = SearchAction(query="any", reasoning="test filler")
    verdict = SpecEvaluator(
        [RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH]
    ).evaluate(action, state)
    assert verdict.kind == "allow"


def test_force_cluster_refresh_fires_at_threshold():
    state = _state_with_papers_after_refresh(n_after=15)
    action = SearchAction(query="any", reasoning="test filler")
    verdict = SpecEvaluator(
        [RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH]
    ).evaluate(action, state)
    assert verdict.kind == "force"
    assert verdict.rule_name == "force_cluster_refresh_on_pool_growth"
    assert verdict.forced_action is not None
    assert verdict.forced_action.action_type == "cluster_refresh"


def test_force_cluster_refresh_does_not_force_on_refresh_itself():
    """The rule should NOT fire when the proposed action is already a refresh."""
    state = _state_with_papers_after_refresh(n_after=20)
    action = ClusterRefreshAction(
        reasoning="planner explicitly proposes a refresh"
    )
    verdict = SpecEvaluator(
        [RULE_FORCE_CLUSTER_REFRESH_ON_POOL_GROWTH]
    ).evaluate(action, state)
    assert verdict.kind == "allow"


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


def test_all_rules_registry_contains_milestones():
    names = {r.name for r in ALL_RULES}
    assert {
        # M1
        "read_paper_budget",
        "no_repeated_exact_action",
        "deadlock_abort",
        # M2
        "action_budget",
        "query_diversity",
        "query_must_be_specific_after_warmup",
        # M3
        "force_cluster_refresh_on_pool_growth",
    } <= names


def test_all_rules_have_unique_names():
    names = [r.name for r in ALL_RULES]
    assert len(names) == len(set(names))
