"""T1 LLM tests for cluster labeling — real Gemini Flash calls.

Per docs/onboard-redesign/09 testing strategy. Marked @pytest.mark.llm.

Validates that the labeling prompt produces:
  - Correct number of labels (one per RawCluster)
  - Slug format compliance after normalization
  - Unique slugs in batch
  - Inheritance respected when paper-overlap is high

Cost: ~$0.005 per test (one Flash call each).
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from src.config import LLMConfig
from src.explore.cluster.algorithm import RawCluster
from src.explore.cluster.labeling import SLUG_PATTERN, label_clusters
from src.explore.state import Cluster, ClusterSnapshot, PaperRecord
from src.llm.gemini_client import GeminiClient


pytestmark = pytest.mark.llm


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


def _paper(aid: str, title: str, abstract: str) -> PaperRecord:
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


def _vln_papers() -> list[PaperRecord]:
    return [
        _paper(
            "2401.00001",
            "Vision-Language Navigation in Continuous Environments",
            "We tackle vision-language navigation (VLN) in unconstrained environments…",
        ),
        _paper(
            "2401.00002",
            "Sim2Real for VLN-CE",
            "Continuous-environment VLN benchmark transfer to real robots…",
        ),
        _paper(
            "2401.00003",
            "Cross-View Matching for Visual Navigation",
            "We use cross-view matching to ground language instructions for navigation…",
        ),
    ]


def _objnav_papers() -> list[PaperRecord]:
    return [
        _paper(
            "2402.00001",
            "Zero-Shot Object Goal Navigation with CLIP",
            "Zero-shot object goal navigation (ObjNav) using CLIP-based semantics…",
        ),
        _paper(
            "2402.00002",
            "Open-Vocabulary ObjNav in HM3D",
            "Open-vocab object goal navigation evaluated on HM3D ObjectNav…",
        ),
    ]


def _raw_cluster(temp_id: int, papers: list[PaperRecord]) -> RawCluster:
    ids = [p.arxiv_id for p in papers]
    return RawCluster(
        temp_id=temp_id,
        paper_ids=ids,
        centroid_paper_id=ids[0],
        representative_paper_ids=ids,
        shared_benchmarks=[],
        top_authors=[],
        year_range=(2024, 2024),
        density="dense",
        mean_probability=0.9,
    )


# —————————————————————————————————————————————————————————————
# Tests
# —————————————————————————————————————————————————————————————


async def test_label_two_clusters_unique_and_well_formed(llm_client):
    vln_papers = _vln_papers()
    objnav_papers = _objnav_papers()
    raw_clusters = [
        _raw_cluster(0, vln_papers),
        _raw_cluster(1, objnav_papers),
    ]
    pool = {p.arxiv_id: p for p in vln_papers + objnav_papers}

    labels = await label_clusters(
        raw_clusters=raw_clusters,
        prev_snapshot=None,
        paper_pool=pool,
        llm=llm_client,
    )

    assert len(labels) == 2
    # Slug format
    for l in labels:
        assert SLUG_PATTERN.match(l.slug), f"Bad slug format: {l.slug!r}"
    # Uniqueness
    assert labels[0].slug != labels[1].slug
    # Display labels and descriptions are non-empty
    for l in labels:
        assert l.display_label.strip()
        assert l.description.strip()


async def test_label_inherits_when_papers_overlap_heavily(llm_client):
    """When new cluster's papers are mostly the same as a prev cluster, slug should be reused."""
    vln_papers = _vln_papers()
    pool = {p.arxiv_id: p for p in vln_papers}

    prev = ClusterSnapshot(
        snapshot_id="prev",
        generated_at=datetime.now(),
        generated_after_turn=1,
        n_papers_at_time=len(vln_papers),
        clusters=[
            Cluster(
                slug="vln-ce",
                display_label="VLN-CE",
                description="Continuous-environment vision-language navigation",
                paper_ids=[p.arxiv_id for p in vln_papers],
                size=len(vln_papers),
                centroid_paper_id=vln_papers[0].arxiv_id,
                representative_paper_ids=[p.arxiv_id for p in vln_papers],
                shared_benchmarks=[],
                top_authors=[],
                year_range=(2024, 2024),
                density="dense",
                first_seen_in_snapshot="prev",
            )
        ],
    )

    raw = _raw_cluster(0, vln_papers)
    labels = await label_clusters(
        raw_clusters=[raw],
        prev_snapshot=prev,
        paper_pool=pool,
        llm=llm_client,
    )

    assert len(labels) == 1
    # Strong expectation: the slug is `vln-ce` (inherited)
    # Mild fallback: at minimum, inherited_from_slug is set, even if LLM picked
    # a slightly different slug (which our validation would reject).
    assert (
        labels[0].slug == "vln-ce" or labels[0].inherited_from_slug == "vln-ce"
    ), (
        f"Expected inheritance from 'vln-ce' (paper overlap = 100%), "
        f"got slug={labels[0].slug!r}, "
        f"inherited_from={labels[0].inherited_from_slug!r}"
    )
