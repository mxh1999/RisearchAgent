"""Integration tests for the ArXiv-backed search handler.

These hit real ArXiv (no auth, no cost, but requires network).
Marked @pytest.mark.network so they are skipped in default CI runs.

Embedding-dependent behavior (EmbeddingStore path) is covered separately
under @pytest.mark.llm since it requires a Gemini API key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.explore.actions import SearchAction, StopAction
from src.explore.crawl import ExplorerSearcher
from src.explore.executor import ActionExecutor
from src.explore.orchestrator import Explorer
from src.explore.planner import MockPlanner
from src.explore.spec import SpecEvaluator
from src.explore.spec.rules import RULE_ACTION_BUDGET
from tests.explore.conftest import make_state


pytestmark = pytest.mark.network


async def test_search_adds_papers_to_pool(tmp_path: Path):
    """A real ArXiv query should populate paper_pool and query_log."""
    state = make_state(run_id="arxiv-search", action_budget=5)
    searcher = ExplorerSearcher(delay_seconds=1.0)
    executor = ActionExecutor(searcher=searcher, embeddings=None)

    script = [
        SearchAction(
            query="zero-shot object navigation",
            categories=["cs.RO"],
            max_results=5,
            reasoning="test: probe real ArXiv; expect 1-5 recent papers",
        ),
        StopAction(
            claimed_reason="saturated",
            reasoning="test: stop after first search in this fixture",
        ),
    ]

    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=executor,
        evaluator=SpecEvaluator([RULE_ACTION_BUDGET]),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    assert final.metadata.status == "completed"
    assert 1 <= len(final.paper_pool) <= 5
    assert len(final.query_log) == 1

    q = final.query_log[0]
    assert q.query_text == "zero-shot object navigation"
    assert q.n_results_raw >= 1
    assert q.n_new_to_pool == q.n_results_raw  # empty pool, all new

    for p in final.paper_pool.values():
        assert p.source == "search"
        assert p.source_query_id == q.query_id
        assert p.first_seen_turn >= 1
        assert p.is_noise is False
        assert p.embedding_id is None  # no EmbeddingStore configured


async def test_search_dedupes_existing_papers(tmp_path: Path):
    """Same query + same args -> all 2nd-call results are dupes of the 1st."""
    state = make_state(run_id="arxiv-dedupe", action_budget=5)
    searcher = ExplorerSearcher(delay_seconds=1.0)
    executor = ActionExecutor(searcher=searcher, embeddings=None)

    # Identical args across both searches so ArXiv returns the same result set.
    # We don't load RULE_NO_REPEATED_EXACT_ACTION here so both fire normally.
    common_kwargs = dict(
        query="zero-shot object navigation",
        categories=["cs.RO"],
        max_results=3,
        sort_by="relevance",
    )
    script = [
        SearchAction(
            **common_kwargs,
            reasoning="test: first search populates pool",
        ),
        SearchAction(
            **common_kwargs,
            reasoning="test: second identical search should dedupe fully",
        ),
        StopAction(claimed_reason="saturated", reasoning="test: stop"),
    ]

    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=executor,
        evaluator=SpecEvaluator([RULE_ACTION_BUDGET]),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    assert final.metadata.status == "completed"
    assert len(final.query_log) == 2

    q1, q2 = final.query_log
    assert q1.n_new_to_pool == q1.n_results_raw  # first time: all new
    assert q2.n_results_raw == q1.n_results_raw  # same query same results
    assert q2.n_new_to_pool == 0  # all dupes


async def test_executor_without_searcher_falls_back_to_stub(tmp_path: Path):
    """Sanity: without searcher/embeddings, search handler still works (stub)."""
    state = make_state(run_id="no-deps", action_budget=5)
    executor = ActionExecutor()  # no deps

    script = [
        SearchAction(
            query="anything",
            reasoning="test: without searcher, should get stub result",
        ),
        StopAction(claimed_reason="saturated", reasoning="test: stop"),
    ]
    explorer = Explorer(
        state=state,
        planner=MockPlanner(script),
        executor=executor,
        evaluator=SpecEvaluator([RULE_ACTION_BUDGET]),
        checkpoint_dir=tmp_path,
    )
    final = await explorer.run()

    assert final.metadata.status == "completed"
    assert final.paper_pool == {}
    # The search action record exists and is marked as successful stub.
    search_records = [
        r for r in final.action_history if r.action.action_type == "search"
    ]
    assert len(search_records) == 1
    assert search_records[0].was_executed is True
    assert "stub" in search_records[0].outcome_summary
