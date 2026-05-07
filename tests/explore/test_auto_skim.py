"""Tests for the auto-skim of cluster representatives during cluster_refresh.

Patches src.explore.skim.skim_paper to return canned SkimResults so we
exercise the executor code path deterministically.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.explore.executor import ActionExecutor
from src.explore.state import (
    Cluster,
    ClusterSnapshot,
    PaperRecord,
    SkimResult,
)
from tests.explore.conftest import make_state


def _paper(aid: str, title: str = "T", abstract: str = "Abstract about HM3D R2R."):
    return PaperRecord(
        arxiv_id=aid,
        title=title,
        abstract=abstract,
        authors=["A"],
        published=date(2024, 1, 1),
        categories=["cs.RO"],
        pdf_url="",
        first_seen_turn=1,
        source="search",
    )


def _state_with_clusters(papers: list[PaperRecord], cluster_specs: list[tuple[str, list[str]]]):
    """Build a state with clusters whose representative_paper_ids are given."""
    state = make_state()
    for p in papers:
        state.paper_pool[p.arxiv_id] = p
    state.cluster_snapshot = ClusterSnapshot(
        snapshot_id="snap",
        generated_at=datetime.now(),
        generated_after_turn=1,
        n_papers_at_time=len(papers),
        clusters=[
            Cluster(
                slug=slug,
                display_label=slug,
                description="d",
                paper_ids=reps,
                size=len(reps),
                centroid_paper_id=reps[0],
                representative_paper_ids=reps,
                year_range=(2024, 2024),
                density="dense",
                first_seen_in_snapshot="snap",
            )
            for slug, reps in cluster_specs
        ],
    )
    return state


class _FakeLLM:
    """Stand-in. We monkey-patch skim_paper so this never calls anything."""
    config = type("C", (), {"filter_model": "x"})()


def _canned_skim(benchmarks=("HM3D", "R2R")):
    def _factory(paper, llm, *, model=None):
        async def _aresult():
            return SkimResult(
                benchmarks=list(benchmarks),
                methods=["MethodX"],
                keywords=["nav"],
                skimmed_at=datetime.now(),
            )
        return _aresult()
    return _factory


# —————————————————————————————————————————————————————————————


async def test_auto_skim_skims_unskimmed_reps(monkeypatch):
    papers = [_paper("2401.00001"), _paper("2401.00002"), _paper("2401.00003")]
    state = _state_with_clusters(
        papers, [("vln", ["2401.00001", "2401.00002", "2401.00003"])]
    )
    monkeypatch.setattr(
        "src.explore.skim.skim_paper",
        _canned_skim(("HM3D", "R2R", "RxR")),
    )
    executor = ActionExecutor(llm=_FakeLLM())  # type: ignore[arg-type]

    n = await executor._auto_skim_cluster_reps(state, n_per_cluster=3)
    assert n == 3
    # All three papers now have skim
    assert all(p.skim is not None for p in state.paper_pool.values())
    # Counters populated with the benchmarks
    assert "HM3D" in state.counters.benchmark_counter
    assert "R2R" in state.counters.benchmark_counter
    assert len(state.counters.benchmark_counter["HM3D"]) == 3


async def test_auto_skim_caps_per_cluster(monkeypatch):
    papers = [_paper(f"2401.{i:05d}") for i in range(5)]
    state = _state_with_clusters(
        papers, [("vln", [p.arxiv_id for p in papers])]
    )
    monkeypatch.setattr(
        "src.explore.skim.skim_paper", _canned_skim(("HM3D",))
    )
    executor = ActionExecutor(llm=_FakeLLM())  # type: ignore[arg-type]
    n = await executor._auto_skim_cluster_reps(state, n_per_cluster=2)
    assert n == 2  # only first 2 reps of the cluster
    skimmed = sum(1 for p in state.paper_pool.values() if p.skim is not None)
    assert skimmed == 2


async def test_auto_skim_skips_already_skimmed(monkeypatch):
    papers = [_paper("2401.00001"), _paper("2401.00002")]
    # Pre-populate skim on the first paper
    papers[0].skim = SkimResult(
        benchmarks=["pre-existing"], methods=[], keywords=[], skimmed_at=datetime.now()
    )
    state = _state_with_clusters(papers, [("c", ["2401.00001", "2401.00002"])])
    monkeypatch.setattr(
        "src.explore.skim.skim_paper", _canned_skim(("HM3D",))
    )
    executor = ActionExecutor(llm=_FakeLLM())  # type: ignore[arg-type]
    n = await executor._auto_skim_cluster_reps(state, n_per_cluster=3)
    assert n == 1  # only the unskimmed one
    # The pre-existing skim wasn't overwritten
    assert papers[0].skim.benchmarks == ["pre-existing"]


async def test_auto_skim_skips_papers_without_abstract(monkeypatch):
    p1 = _paper("2401.00001", abstract="")  # no abstract
    p2 = _paper("2401.00002", abstract="ok")
    state = _state_with_clusters([p1, p2], [("c", ["2401.00001", "2401.00002"])])
    monkeypatch.setattr(
        "src.explore.skim.skim_paper", _canned_skim(("HM3D",))
    )
    executor = ActionExecutor(llm=_FakeLLM())  # type: ignore[arg-type]
    n = await executor._auto_skim_cluster_reps(state, n_per_cluster=3)
    assert n == 1
    assert p1.skim is None
    assert p2.skim is not None


async def test_auto_skim_no_llm_returns_zero():
    state = _state_with_clusters([_paper("2401.00001")], [("c", ["2401.00001"])])
    executor = ActionExecutor()  # no llm
    n = await executor._auto_skim_cluster_reps(state)
    assert n == 0


async def test_auto_skim_no_snapshot_returns_zero():
    state = make_state()
    # cluster_snapshot is None
    executor = ActionExecutor(llm=_FakeLLM())  # type: ignore[arg-type]
    n = await executor._auto_skim_cluster_reps(state)
    assert n == 0


async def test_auto_skim_skim_failure_doesnt_break(monkeypatch):
    """If skim_paper returns None (parse failure), counter stays clean."""
    papers = [_paper("2401.00001"), _paper("2401.00002")]
    state = _state_with_clusters(papers, [("c", ["2401.00001", "2401.00002"])])

    def _failing_skim(paper, llm, *, model=None):
        async def _r():
            return None  # simulate parse failure
        return _r()

    monkeypatch.setattr("src.explore.skim.skim_paper", _failing_skim)
    executor = ActionExecutor(llm=_FakeLLM())  # type: ignore[arg-type]
    n = await executor._auto_skim_cluster_reps(state)
    assert n == 0
    assert state.counters.benchmark_counter == {}
    assert all(p.skim is None for p in state.paper_pool.values())
