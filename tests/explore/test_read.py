"""Deterministic tests for the read_paper handler + DeepReading conversion."""

from __future__ import annotations

from datetime import date
from typing import Optional

import pytest

from src.explore.actions import ReadPaperAction
from src.explore.executor import ActionExecutor
from src.explore.read import deep_reading_to_explore_reading
from src.explore.state import PaperRecord
from src.models import (
    DeepReading,
    ExperimentEntry as MainExperimentEntry,
    ExperimentTable,
    MethodResult,
)
from tests.explore.conftest import make_state


# —————————————————————————————————————————————————————————————
# deep_reading_to_explore_reading
# —————————————————————————————————————————————————————————————


def _sample_deep_reading(arxiv_id: str = "2401.00001") -> DeepReading:
    return DeepReading(
        arxiv_id=arxiv_id,
        problem_statement="Some problem.",
        proposed_method="A nice method using CLIP.",
        key_contributions=["Contribution 1", "Contribution 2"],
        experimental_setup="Trained on HM3D val unseen split.",
        main_results="Achieves 32.5% SR on HM3D-ObjNav.",
        limitations="Limited to indoor scenes.",
        comparison_to_prior_work="Better than ObjectNav-RL by 5 SR points.",
        experiment_table=ExperimentTable(
            arxiv_id=arxiv_id,
            entries=[
                MainExperimentEntry(
                    benchmark="HM3D-ObjNav",
                    setting="zero-shot val unseen",
                    metric="SR",
                    higher_is_better=True,
                    results=[
                        MethodResult(method_name="Ours", value=32.5, is_paper_method=True),
                        MethodResult(method_name="ObjectNav-RL", value=27.5, is_paper_method=False),
                    ],
                )
            ],
        ),
    )


def test_conversion_preserves_core_fields():
    deep = _sample_deep_reading("2401.00001")
    er = deep_reading_to_explore_reading("2401.00001", deep)
    assert er.arxiv_id == "2401.00001"
    assert "CLIP" in er.proposed_method
    assert "HM3D" in er.experimental_setup
    assert "32.5" in er.main_results
    assert len(er.benchmarks) == 1
    bench = er.benchmarks[0]
    assert bench.benchmark == "HM3D-ObjNav"
    assert bench.metric == "SR"
    assert bench.higher_is_better is True
    assert len(bench.results) == 2
    paper_method = [r for r in bench.results if r.is_paper_method][0]
    assert paper_method.method_name == "Ours"
    assert paper_method.value == 32.5


def test_conversion_drops_main_db_only_fields():
    """problem_statement / key_contributions etc are not on ExploreReading."""
    deep = _sample_deep_reading()
    er = deep_reading_to_explore_reading("2401.00001", deep)
    # ExploreReading should not expose these fields
    assert not hasattr(er, "problem_statement")
    assert not hasattr(er, "key_contributions")
    assert not hasattr(er, "limitations")
    assert not hasattr(er, "comparison_to_prior_work")


def test_conversion_handles_no_experiment_table():
    deep = DeepReading(
        arxiv_id="2401.00001",
        problem_statement="x",
        proposed_method="y",
        key_contributions=[],
        experimental_setup="z",
        main_results="w",
        limitations="",
        comparison_to_prior_work="",
        experiment_table=None,
    )
    er = deep_reading_to_explore_reading("2401.00001", deep)
    assert er.benchmarks == []
    assert er.proposed_method == "y"


# —————————————————————————————————————————————————————————————
# Executor _handle_read_paper
# —————————————————————————————————————————————————————————————


class _FakeExploreReader:
    """Stand-in for src.explore.read.ExploreReader."""

    def __init__(self, result):
        self.result = result
        self.calls: list[str] = []

    async def read(self, paper):
        self.calls.append(paper.arxiv_id)
        return self.result


def _paper(aid: str = "2401.00001") -> PaperRecord:
    return PaperRecord(
        arxiv_id=aid,
        title="Test Paper",
        abstract="abstract",
        authors=["A"],
        published=date(2024, 1, 1),
        categories=["cs.AI"],
        pdf_url="https://arxiv.org/pdf/2401.00001",
        first_seen_turn=1,
        source="search",
    )


async def test_read_paper_stub_when_no_reader_wired():
    state = make_state()
    state.paper_pool["2401.00001"] = _paper()
    executor = ActionExecutor()  # no reader
    action = ReadPaperAction(
        arxiv_id="2401.00001",
        reasoning="test: stub when reader not wired",
    )
    result = await executor.execute(action, state)
    assert result.success is True
    assert "stub" in result.summary
    assert state.budget.read_papers_used == 1  # still bumped for budget rule
    assert state.paper_pool["2401.00001"].explore_reading is None


async def test_read_paper_paper_not_in_pool_returns_failed():
    state = make_state()
    fake = _FakeExploreReader(deep_reading_to_explore_reading("?", _sample_deep_reading()))
    executor = ActionExecutor(reader=fake)  # type: ignore[arg-type]
    action = ReadPaperAction(
        arxiv_id="9999.99999",  # not in pool
        reasoning="test: missing paper",
    )
    result = await executor.execute(action, state)
    assert result.success is False
    assert result.error == "paper_not_in_pool"
    # Budget NOT consumed when paper isn't even in pool (no read attempted)
    assert state.budget.read_papers_used == 0


async def test_read_paper_success_updates_paper_and_counters():
    state = make_state()
    state.paper_pool["2401.00001"] = _paper()
    state.paper_pool["2401.00001"].flags = ["deep_read_candidate"]
    er_result = deep_reading_to_explore_reading(
        "2401.00001", _sample_deep_reading("2401.00001")
    )
    fake = _FakeExploreReader(er_result)
    executor = ActionExecutor(reader=fake)  # type: ignore[arg-type]
    action = ReadPaperAction(
        arxiv_id="2401.00001",
        reasoning="test: real read should populate paper.explore_reading",
    )
    result = await executor.execute(action, state)

    assert result.success is True
    assert result.details["n_benchmark_entries"] == 1
    paper = state.paper_pool["2401.00001"]
    assert paper.explore_reading is not None
    assert paper.explore_reading.proposed_method.startswith("A nice method")
    # benchmark_counter populated
    assert "HM3D-ObjNav" in state.counters.benchmark_counter
    assert "2401.00001" in state.counters.benchmark_counter["HM3D-ObjNav"]
    # deep_read_candidate flag removed after a successful read
    assert "deep_read_candidate" not in paper.flags
    # Budget consumed
    assert state.budget.read_papers_used == 1
    assert fake.calls == ["2401.00001"]


async def test_read_paper_consumes_budget_even_on_read_failure():
    """A reader that returns None still bumps the budget — prevents retry storms."""
    state = make_state()
    state.paper_pool["2401.00001"] = _paper()
    fake = _FakeExploreReader(None)  # simulates extract/parse/LLM failure
    executor = ActionExecutor(reader=fake)  # type: ignore[arg-type]
    action = ReadPaperAction(
        arxiv_id="2401.00001",
        reasoning="test: read failure still consumes budget",
    )
    result = await executor.execute(action, state)
    assert result.success is False
    assert result.error == "read_failed"
    assert state.budget.read_papers_used == 1


async def test_read_paper_dedup_in_benchmark_counter():
    """Two reads referencing the same benchmark only add one entry per arxiv_id."""
    state = make_state()
    state.paper_pool["2401.00001"] = _paper()
    er = deep_reading_to_explore_reading("2401.00001", _sample_deep_reading())
    # Pre-populate counter to simulate prior skim_abstract
    state.counters.benchmark_counter["HM3D-ObjNav"] = ["2401.00001"]
    fake = _FakeExploreReader(er)
    executor = ActionExecutor(reader=fake)  # type: ignore[arg-type]
    action = ReadPaperAction(arxiv_id="2401.00001", reasoning="test")
    await executor.execute(action, state)
    assert state.counters.benchmark_counter["HM3D-ObjNav"] == ["2401.00001"]
