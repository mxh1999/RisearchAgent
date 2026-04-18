"""Integration tests for the Explorer main loop.

These drive the orchestrator with a MockPlanner through scripted scenarios
that exercise the spec verdicts (allow/block/force) and checkpoint logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.explore.actions import (
    ReadPaperAction,
    SearchAction,
    StopAction,
)
from src.explore.checkpoint import load_checkpoint
from src.explore.executor import ActionExecutor
from src.explore.orchestrator import Explorer
from src.explore.planner import MockPlanner
from src.explore.spec import ALL_RULES, SpecEvaluator
from tests.explore.conftest import make_state


@pytest.mark.asyncio
async def test_loop_executes_script_then_stops(tmp_path: Path):
    state = make_state(run_id="test-happy")
    script = [
        SearchAction(
            query="embodied navigation",
            reasoning="test: first broad search to seed the pool",
        ),
        SearchAction(
            query="vision language navigation",
            reasoning="test: second differentiated search",
        ),
        StopAction(
            claimed_reason="saturated",
            reasoning="test: declaring stop after two searches",
        ),
    ]
    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=ActionExecutor(),
        evaluator=SpecEvaluator(ALL_RULES),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    assert final.metadata.status == "completed"
    assert final.metadata.termination_reason == "saturated"
    assert final.turn == 3
    assert len(final.action_history) == 3
    assert all(r.was_executed for r in final.action_history)


@pytest.mark.asyncio
async def test_loop_blocks_read_paper_over_budget(tmp_path: Path):
    state = make_state(read_papers_used=3, read_paper_budget=3)
    script = [
        ReadPaperAction(
            arxiv_id="2401.00001",
            reasoning="test: this should be blocked (budget exhausted)",
        ),
        SearchAction(
            query="different query after block",
            reasoning="test: planner adapts after block",
        ),
        StopAction(
            claimed_reason="saturated",
            reasoning="test: clean exit",
        ),
    ]
    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=ActionExecutor(),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    assert final.metadata.status == "completed"
    # 3 history entries: 1 blocked + 2 executed
    assert len(final.action_history) == 3
    assert final.action_history[0].was_executed is False
    assert final.action_history[0].spec_verdict == "block"
    assert final.action_history[1].was_executed is True
    assert final.action_history[2].was_executed is True


@pytest.mark.asyncio
async def test_loop_force_stops_on_deadlock(tmp_path: Path):
    """After 8 consecutive identical repeated actions (all blocked), deadlock_abort fires."""
    state = make_state()

    # Script: same action repeated 10 times. After turn 1 executes, turn 2+ blocks
    # by no_repeated_exact_action, building up consecutive_blocked count until
    # deadlock_abort (>=8) fires and forces stop.
    identical = SearchAction(
        query="same query repeated",
        reasoning="test: identical action proposed repeatedly to trigger deadlock",
    )
    script = [identical] * 12  # more than enough
    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=ActionExecutor(),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    assert final.metadata.status == "completed"
    assert final.metadata.termination_reason == "budget_exhausted"
    # First was executed; then 8 blocked; then deadlock_abort forces stop
    executed = [r for r in final.action_history if r.was_executed]
    blocked = [r for r in final.action_history if not r.was_executed]
    assert len(executed) == 2  # first search + forced stop
    assert len(blocked) == 8
    # The forcing action record has spec_verdict=force
    force_records = [r for r in final.action_history if r.spec_verdict == "force"]
    assert len(force_records) == 1
    assert force_records[0].action.action_type == "stop"


@pytest.mark.asyncio
async def test_checkpoint_roundtrip(tmp_path: Path):
    state = make_state(run_id="roundtrip-test")
    script = [
        SearchAction(query="first", reasoning="test: first search for roundtrip"),
        StopAction(claimed_reason="saturated", reasoning="test: stop"),
    ]
    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=ActionExecutor(),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    # Read the checkpoint back
    path = tmp_path / "roundtrip-test.json"
    assert path.exists()
    reloaded = load_checkpoint(path)

    assert reloaded.metadata.run_id == final.metadata.run_id
    assert reloaded.metadata.status == "completed"
    assert len(reloaded.action_history) == len(final.action_history)
    # Action types survive the roundtrip
    assert [r.action.action_type for r in reloaded.action_history] == [
        r.action.action_type for r in final.action_history
    ]
