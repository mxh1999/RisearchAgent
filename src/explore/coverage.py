"""Coverage audit: deterministic self-check producing a CoverageReport.

Per docs/onboard-redesign/01-explorer-design.md and 07, coverage_audit
asks 4 standard questions. M4 makes this **deterministic** — no LLM call
— because each question can be answered by inspecting the cluster_snapshot
fields the Clusterer already populates:

  Q1. What sub-areas does the field decompose into?
       → answered if cluster_snapshot exists and clusters.length >= 1
  Q2. What are the dominant benchmarks per sub-area?
       → answered if every cluster has at least one shared_benchmark
  Q3. What are the classic baselines per sub-area?
       → answered (approximately) if every cluster has year_range[0] <= 2022
  Q4. Who are the active authors / groups per sub-area?
       → answered if every cluster has at least one top_author

Skipping LLM here keeps the audit fast, cheap, deterministic, and easy to
test. A future M5+ enhancement could overlay LLM judgment for more nuanced
"is this enough?" decisions; for now structural answers are enough to gate
stop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.explore.state import CoverageQuestion, CoverageReport

if TYPE_CHECKING:
    from src.explore.state import ExplorationState


logger = logging.getLogger(__name__)


CLASSIC_YEAR_THRESHOLD = 2022


def run_coverage_audit(state: "ExplorationState") -> CoverageReport:
    """Compute a fresh CoverageReport from the current state."""
    questions: list[CoverageQuestion] = []
    snap = state.cluster_snapshot

    # —— Q1: sub-areas exist? ——
    if snap is None or not snap.clusters:
        questions.append(
            CoverageQuestion(
                question="What sub-areas does the field decompose into?",
                answer_available=False,
                evidence=(
                    "No cluster_snapshot yet"
                    if snap is None
                    else "cluster_snapshot exists but has no clusters"
                ),
                gap_description=(
                    "Run cluster_refresh after the pool grows to >= 20 papers."
                ),
            )
        )
        # Without clusters, the remaining questions can't be answered either.
        # Append a single "needs clusters" gate for Q2-Q4 to keep the report tight.
        questions.append(
            CoverageQuestion(
                question="(Q2-Q4 require cluster_snapshot.)",
                answer_available=False,
                evidence="—",
                gap_description="Resolve Q1 first.",
            )
        )
        return _finalize(state, questions)

    cluster_summary = ", ".join(c.slug for c in snap.clusters)
    questions.append(
        CoverageQuestion(
            question="What sub-areas does the field decompose into?",
            answer_available=True,
            evidence=(
                f"cluster_snapshot has {len(snap.clusters)} labeled clusters: "
                f"{cluster_summary}"
            ),
        )
    )

    # —— Q2: dominant benchmark per cluster ——
    missing_bench = [c.slug for c in snap.clusters if not c.shared_benchmarks]
    if not missing_bench:
        questions.append(
            CoverageQuestion(
                question="What are the dominant benchmarks per sub-area?",
                answer_available=True,
                evidence=(
                    "Every cluster has at least one shared benchmark "
                    "(populated by skim_abstract)."
                ),
            )
        )
    else:
        questions.append(
            CoverageQuestion(
                question="What are the dominant benchmarks per sub-area?",
                answer_available=False,
                evidence=(
                    f"{len(snap.clusters) - len(missing_bench)}/"
                    f"{len(snap.clusters)} clusters have shared_benchmarks"
                ),
                gap_description=(
                    f"No shared benchmarks for clusters: {missing_bench}. "
                    f"Run skim_abstract on representatives of these clusters."
                ),
            )
        )

    # —— Q3: classic baseline per cluster (year proxy) ——
    missing_classics = [
        c.slug
        for c in snap.clusters
        if c.year_range[0] > CLASSIC_YEAR_THRESHOLD
    ]
    if not missing_classics:
        questions.append(
            CoverageQuestion(
                question=(
                    "What are the classic baselines per sub-area? "
                    f"(approx: any paper from <= {CLASSIC_YEAR_THRESHOLD})"
                ),
                answer_available=True,
                evidence="Every cluster's year_range starts at or before 2022.",
            )
        )
    else:
        questions.append(
            CoverageQuestion(
                question=(
                    "What are the classic baselines per sub-area? "
                    f"(approx: any paper from <= {CLASSIC_YEAR_THRESHOLD})"
                ),
                answer_available=False,
                evidence=(
                    f"{len(snap.clusters) - len(missing_classics)}/"
                    f"{len(snap.clusters)} clusters reach back to "
                    f"{CLASSIC_YEAR_THRESHOLD} or earlier"
                ),
                gap_description=(
                    f"Clusters without classic baselines: {missing_classics}. "
                    f"Search with source_tag=classic_lookup and "
                    f"date_range covering 2018-{CLASSIC_YEAR_THRESHOLD}."
                ),
            )
        )

    # —— Q4: active authors per cluster ——
    missing_authors = [c.slug for c in snap.clusters if not c.top_authors]
    if not missing_authors:
        questions.append(
            CoverageQuestion(
                question="Who are the active authors per sub-area?",
                answer_available=True,
                evidence="Every cluster has at least one top_author.",
            )
        )
    else:
        questions.append(
            CoverageQuestion(
                question="Who are the active authors per sub-area?",
                answer_available=False,
                evidence=(
                    f"{len(snap.clusters) - len(missing_authors)}/"
                    f"{len(snap.clusters)} clusters have top_authors"
                ),
                gap_description=(
                    f"Clusters with empty top_authors: {missing_authors}. "
                    f"This usually means very small clusters; consider "
                    f"more searches or a cluster_refresh."
                ),
            )
        )

    return _finalize(state, questions)


def _finalize(state: "ExplorationState", questions: list[CoverageQuestion]) -> CoverageReport:
    unanswered_count = sum(1 for q in questions if not q.answer_available)
    return CoverageReport(
        generated_at=datetime.now(),
        generated_after_turn=state.turn,
        questions=questions,
        passes=unanswered_count == 0,
        unanswered_count=unanswered_count,
    )


__all__ = ["run_coverage_audit", "CLASSIC_YEAR_THRESHOLD"]
