"""Deterministic tests for the coverage_audit logic.

run_coverage_audit() is a pure function over ExplorationState; it doesn't
call any LLM. These tests exercise each branch of its decision tree.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.explore.coverage import CLASSIC_YEAR_THRESHOLD, run_coverage_audit
from src.explore.state import Cluster, ClusterSnapshot, PaperRecord
from tests.explore.conftest import make_state


def _cluster(
    slug: str,
    *,
    benchmarks: list[str] = (),
    authors: list[str] = (),
    year_range: tuple[int, int] = (2024, 2024),
    paper_ids: list[str] = ("p1",),
    snapshot_id: str = "snap",
):
    return Cluster(
        slug=slug,
        display_label=slug,
        description="test cluster",
        paper_ids=list(paper_ids),
        size=len(paper_ids),
        centroid_paper_id=paper_ids[0] if paper_ids else None,
        representative_paper_ids=list(paper_ids)[:3],
        shared_benchmarks=list(benchmarks),
        top_authors=list(authors),
        year_range=year_range,
        density="dense",
        first_seen_in_snapshot=snapshot_id,
    )


def _state_with_clusters(clusters: list[Cluster]):
    state = make_state()
    state.cluster_snapshot = ClusterSnapshot(
        snapshot_id="snap",
        generated_at=datetime.now(),
        generated_after_turn=1,
        n_papers_at_time=sum(c.size for c in clusters),
        clusters=clusters,
    )
    return state


# —————————————————————————————————————————————————————————————
# Q1: cluster_snapshot must exist
# —————————————————————————————————————————————————————————————


def test_no_snapshot_audit_fails():
    state = make_state()
    report = run_coverage_audit(state)
    assert report.passes is False
    assert report.unanswered_count >= 1
    assert "No cluster_snapshot" in report.questions[0].evidence


def test_empty_clusters_audit_fails():
    state = make_state()
    state.cluster_snapshot = ClusterSnapshot(
        snapshot_id="empty",
        generated_at=datetime.now(),
        generated_after_turn=1,
        n_papers_at_time=0,
        clusters=[],
    )
    report = run_coverage_audit(state)
    assert report.passes is False
    assert "no clusters" in report.questions[0].evidence


# —————————————————————————————————————————————————————————————
# Full pass case
# —————————————————————————————————————————————————————————————


def test_audit_passes_when_all_clusters_complete():
    state = _state_with_clusters(
        [
            _cluster(
                "vln-ce",
                benchmarks=["R2R", "RxR"],
                authors=["Wang L."],
                year_range=(2020, 2024),  # has classic
            ),
            _cluster(
                "objnav",
                benchmarks=["HM3D"],
                authors=["Chen S."],
                year_range=(2019, 2024),
            ),
        ]
    )
    report = run_coverage_audit(state)
    assert report.passes is True
    assert report.unanswered_count == 0
    assert all(q.answer_available for q in report.questions)


# —————————————————————————————————————————————————————————————
# Per-question failure cases
# —————————————————————————————————————————————————————————————


def test_audit_fails_when_cluster_missing_benchmarks():
    state = _state_with_clusters(
        [
            _cluster("vln-ce", benchmarks=["R2R"], authors=["A"], year_range=(2020, 2024)),
            _cluster("objnav", benchmarks=[], authors=["B"], year_range=(2020, 2024)),
        ]
    )
    report = run_coverage_audit(state)
    assert report.passes is False
    bench_q = next(q for q in report.questions if "benchmark" in q.question.lower())
    assert bench_q.answer_available is False
    assert "objnav" in bench_q.gap_description


def test_audit_fails_when_no_classic_baseline():
    state = _state_with_clusters(
        [
            _cluster(
                "vln-ce",
                benchmarks=["R2R"],
                authors=["A"],
                year_range=(2024, 2025),  # ALL after threshold
            ),
        ]
    )
    report = run_coverage_audit(state)
    assert report.passes is False
    classic_q = next(q for q in report.questions if "classic" in q.question.lower())
    assert classic_q.answer_available is False
    assert "vln-ce" in classic_q.gap_description
    assert str(CLASSIC_YEAR_THRESHOLD) in classic_q.gap_description


def test_audit_fails_when_cluster_missing_authors():
    state = _state_with_clusters(
        [
            _cluster(
                "vln-ce",
                benchmarks=["R2R"],
                authors=[],
                year_range=(2020, 2024),
            )
        ]
    )
    report = run_coverage_audit(state)
    assert report.passes is False
    author_q = next(q for q in report.questions if "author" in q.question.lower())
    assert author_q.answer_available is False
    assert "vln-ce" in author_q.gap_description


def test_audit_partial_pass_unanswered_count_reflects_gaps():
    """One gap → unanswered_count = 1, passes = False."""
    state = _state_with_clusters(
        [
            _cluster(
                "vln-ce",
                benchmarks=[],  # gap
                authors=["A"],
                year_range=(2020, 2024),
            )
        ]
    )
    report = run_coverage_audit(state)
    assert report.passes is False
    assert report.unanswered_count == 1
    answered = [q for q in report.questions if q.answer_available]
    unanswered = [q for q in report.questions if not q.answer_available]
    assert len(unanswered) == 1
    assert len(answered) == 3  # Q1 sub-areas, Q3 classics, Q4 authors all pass


# —————————————————————————————————————————————————————————————
# Audit always uses current state.turn
# —————————————————————————————————————————————————————————————


def test_audit_records_generation_turn():
    state = _state_with_clusters([_cluster("c", benchmarks=["B"], authors=["A"])])
    # Bump turn artificially via action_history
    from src.explore.state import ActionRecord
    from src.explore.actions import ClusterRefreshAction

    state.action_history.append(
        ActionRecord(
            turn=7,
            action=ClusterRefreshAction(reasoning="..."),
            was_executed=True,
            spec_verdict="allow",
            outcome="success",
        )
    )
    report = run_coverage_audit(state)
    assert report.generated_after_turn == state.turn == 1
    # NB: our state's `turn` is derived from len of executed history; one record => 1
