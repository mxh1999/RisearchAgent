"""End-to-end integration test for M2 Explorer.

Runs the full loop with real dependencies:
  - LLMPlanner (Gemini Flash — cheap, good enough for pipeline validation)
  - ExplorerSearcher (real ArXiv)
  - EmbeddingStore (real Gemini embeddings + ChromaDB)
  - Full spec rule catalog

Validates that the independently-tested components actually compose. M3
(clustering) and beyond will build on this integration path.

Cost: ~$0.01-0.03 per run (Flash-only).
Runtime: ~30-60s depending on ArXiv latency and Planner decisions.

Marked @pytest.mark.llm (combines network + LLM) so it's skipped by default.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import LLMConfig
from src.explore.crawl import ExplorerSearcher
from src.explore.embeddings import EmbeddingStore
from src.explore.executor import ActionExecutor
from src.explore.orchestrator import Explorer
from src.explore.planner import LLMPlanner
from src.explore.spec import ALL_RULES, SpecEvaluator
from src.llm.gemini_client import GeminiClient
from tests.explore.conftest import make_state


pytestmark = [pytest.mark.llm, pytest.mark.network]


@pytest.fixture
def llm_client():
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")

    return GeminiClient(
        LLMConfig(
            filter_model="gemini-2.5-flash",
            reader_model="gemini-2.5-pro",
            embedding_model="gemini-embedding-001",
            api_key=api_key,
            max_concurrent=3,
            temperature=0.3,
        )
    )


async def test_e2e_short_run_completes_and_populates_pool(
    llm_client: GeminiClient, tmp_path: Path
):
    """Full pipeline: Planner → Spec → Executor → State → Checkpoint.

    Uses a tight action_budget so the action_budget rule reliably terminates
    the run within a bounded number of Planner turns (no saturation-based
    stop yet — that's M4).
    """
    state = make_state(
        run_id="e2e-short",
        action_budget=4,  # deliberately small; action_budget rule force-stops at limit
        read_paper_budget=0,  # no deep reads in e2e (keep cost low)
    )
    state.intent.natural_language = (
        "Zero-shot object goal navigation in embodied agents, "
        "especially LLM-assisted planners."
    )

    searcher = ExplorerSearcher(delay_seconds=1.0)
    embeddings = EmbeddingStore(
        run_id=state.metadata.run_id,
        llm=llm_client,
        chroma_path=tmp_path / "chroma",
    )
    executor = ActionExecutor(searcher=searcher, embeddings=embeddings)

    # Flash planner — cheaper than Pro, enough to exercise the structure.
    planner = LLMPlanner(llm_client, model=llm_client.config.filter_model)

    explorer = Explorer(
        state=state,
        planner=planner,
        executor=executor,
        evaluator=SpecEvaluator(ALL_RULES),
        checkpoint_dir=tmp_path / "state",
    )

    final = await explorer.run()

    # —————————————————————————————————————————————————————
    # Structural assertions (don't depend on planner strategy variations)
    # —————————————————————————————————————————————————————
    assert final.metadata.status == "completed", (
        f"Run did not complete cleanly: status={final.metadata.status}, "
        f"reason={final.metadata.termination_reason}"
    )

    # action_budget caps us at action_budget actions, so at least 1 run happened
    assert final.turn >= 1
    # Either action_budget force-stopped us (most likely) or planner proposed stop;
    # either way, terminal record exists
    assert final.action_history, "No actions in history"
    last = final.action_history[-1]
    assert last.was_executed is True

    # At least one search happened, and at least one paper entered the pool
    search_records = [
        r for r in final.action_history if r.action.action_type == "search"
    ]
    assert search_records, "Planner never proposed a search in the e2e run"
    assert len(final.paper_pool) > 0, (
        "Pool is empty after e2e; searcher/executor integration broken?"
    )

    # Papers have the full provenance chain
    for p in final.paper_pool.values():
        assert p.source == "search"
        assert p.source_query_id is not None
        assert p.embedding_id is not None  # EmbeddingStore was configured
        assert p.first_seen_turn >= 1

    # Query log parallels search actions
    assert len(final.query_log) == len(search_records)

    # Checkpoint file exists and is re-loadable with the exact same state
    from src.explore.checkpoint import load_checkpoint

    checkpoint_file = tmp_path / "state" / f"{state.metadata.run_id}.json"
    assert checkpoint_file.exists()
    reloaded = load_checkpoint(checkpoint_file)
    assert reloaded.metadata.run_id == final.metadata.run_id
    assert reloaded.pool_size == final.pool_size
    assert len(reloaded.action_history) == len(final.action_history)

    # Cleanup embedding collections
    embeddings.cleanup()
