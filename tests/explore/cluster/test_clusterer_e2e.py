"""End-to-end Clusterer test: real Gemini embeddings + real Flash labeling.

Bypasses ArXiv (uses synthetic PaperRecords) so the test only exercises:
  - EmbeddingStore.add_papers (real Gemini embed)
  - HDBSCAN over real embeddings
  - LLM batch labeling (real Flash)
  - ClusterSnapshot construction + paper.cluster_id propagation

Cost: ~25 embed calls (sub-cent) + 1 Flash labeling call (~$0.005).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.explore.cluster import Clusterer
from src.explore.embeddings import EmbeddingStore
from src.explore.state import PaperRecord
from src.llm.gemini_client import GeminiClient
from tests.explore.conftest import make_state


pytestmark = pytest.mark.llm


def _paper(aid: str, title: str, abstract: str) -> PaperRecord:
    return PaperRecord(
        arxiv_id=aid,
        title=title,
        abstract=abstract,
        authors=["Author"],
        published=date(2024, 1, 1),
        categories=["cs.RO"],
        pdf_url="",
        first_seen_turn=1,
        source="search",
        embedding_id=aid,
    )


def _build_synthetic_pool() -> list[PaperRecord]:
    """24 papers across 3 themes: VLN, ObjNav, SLAM."""
    vln = [
        _paper(
            f"24A.{i:05d}",
            f"Vision-Language Navigation Method {i}",
            f"Cross-modal grounding for navigation following natural-language "
            f"instructions in continuous environments. Variant #{i}.",
        )
        for i in range(8)
    ]
    objnav = [
        _paper(
            f"24B.{i:05d}",
            f"Zero-Shot Object Goal Navigation Approach {i}",
            f"Open-vocabulary object goal navigation using CLIP-based semantic "
            f"matching on HM3D and Habitat benchmarks. Variant #{i}.",
        )
        for i in range(8)
    ]
    slam = [
        _paper(
            f"24C.{i:05d}",
            f"Visual SLAM with Loop Closure {i}",
            f"Classical visual SLAM combining keypoint matching, bundle adjustment "
            f"and loop closure detection. Variant #{i}.",
        )
        for i in range(8)
    ]
    return vln + objnav + slam


async def test_clusterer_produces_snapshot_with_real_embeddings_and_labels(
    llm_client: GeminiClient, tmp_path: Path
):
    state = make_state(run_id="cluster-e2e")
    papers = _build_synthetic_pool()
    state.paper_pool = {p.arxiv_id: p for p in papers}

    embeddings = EmbeddingStore(
        run_id=state.metadata.run_id,
        llm=llm_client,
        chroma_path=tmp_path / "chroma",
    )

    # Embed everything in one batch
    await embeddings.add_papers(
        [
            {"arxiv_id": p.arxiv_id, "title": p.title, "abstract": p.abstract}
            for p in papers
        ]
    )

    clusterer = Clusterer(embeddings=embeddings, llm=llm_client)

    result = await clusterer.refresh(state)

    # —— Structural assertions ——
    assert state.cluster_snapshot is not None
    assert state.cluster_snapshot.n_papers_at_time == len(papers)
    assert result.n_clusters >= 1, "Expected at least one cluster from 24 papers"

    # All clustered papers have a cluster_id; noise papers have is_noise=True
    n_clustered = sum(
        1 for p in state.paper_pool.values() if p.cluster_id is not None
    )
    n_noise = sum(1 for p in state.paper_pool.values() if p.is_noise)
    assert n_clustered + n_noise == len(papers)

    # All cluster slugs are well-formed (validation already happened in labeler,
    # but double-check the snapshot fields)
    for c in state.cluster_snapshot.clusters:
        from src.explore.cluster.labeling import SLUG_PATTERN

        assert SLUG_PATTERN.match(c.slug), f"Bad slug: {c.slug!r}"
        assert c.size == len(c.paper_ids)
        assert c.centroid_paper_id in c.paper_ids
        assert all(rep in c.paper_ids for rep in c.representative_paper_ids)
        assert c.year_range[0] <= c.year_range[1]
        assert c.first_seen_in_snapshot == state.cluster_snapshot.snapshot_id

    # First-call: every cluster is "new"
    assert set(result.new_slugs) == {c.slug for c in state.cluster_snapshot.clusters}
    assert result.disappeared_slugs == []
    # No prev snapshot, so structural change rate is 0 (Jaccard is 0 over empty union of 0)
    # actually: prev_set = {} so union with new_set = new_set; intersection = {}
    # rate = 1 - 0/|new_set| = 1.0
    # this is fine — the "change rate" against null is 100% by definition

    embeddings.cleanup()


async def test_clusterer_inherits_slug_on_second_refresh(
    llm_client: GeminiClient, tmp_path: Path
):
    """A second refresh on (mostly) the same pool should preserve cluster slugs."""
    state = make_state(run_id="cluster-e2e-2")
    papers = _build_synthetic_pool()
    state.paper_pool = {p.arxiv_id: p for p in papers}

    embeddings = EmbeddingStore(
        run_id=state.metadata.run_id,
        llm=llm_client,
        chroma_path=tmp_path / "chroma",
    )
    await embeddings.add_papers(
        [
            {"arxiv_id": p.arxiv_id, "title": p.title, "abstract": p.abstract}
            for p in papers
        ]
    )
    clusterer = Clusterer(embeddings=embeddings, llm=llm_client)

    # First refresh
    first = await clusterer.refresh(state)
    first_slugs = {c.slug for c in state.cluster_snapshot.clusters}

    # Second refresh on (mostly) the same pool — add 1 trivial new paper
    extra = _paper(
        "24D.99999",
        "Sim-to-real for VLN",
        "Sim-to-real transfer for vision-language navigation policies.",
    )
    state.paper_pool[extra.arxiv_id] = extra
    await embeddings.add_papers(
        [{"arxiv_id": extra.arxiv_id, "title": extra.title, "abstract": extra.abstract}]
    )

    second = await clusterer.refresh(state)
    second_slugs = {c.slug for c in state.cluster_snapshot.clusters}

    # Most slugs should carry over. At least one inherited slug expected.
    inherited = sum(
        1 for c in state.cluster_snapshot.clusters if c.inherited_from_slug is not None
    )
    assert inherited >= 1, (
        f"Expected at least one slug to inherit from prior snapshot. "
        f"first_slugs={first_slugs}, second_slugs={second_slugs}"
    )

    embeddings.cleanup()


async def test_clusterer_raises_on_insufficient_pool(
    llm_client: GeminiClient, tmp_path: Path
):
    """Pool < 20 papers → InsufficientPoolError."""
    from src.explore.cluster import InsufficientPoolError

    state = make_state(run_id="cluster-tiny")
    # Only 5 papers
    papers = _build_synthetic_pool()[:5]
    state.paper_pool = {p.arxiv_id: p for p in papers}

    embeddings = EmbeddingStore(
        run_id=state.metadata.run_id,
        llm=llm_client,
        chroma_path=tmp_path / "chroma",
    )
    await embeddings.add_papers(
        [
            {"arxiv_id": p.arxiv_id, "title": p.title, "abstract": p.abstract}
            for p in papers
        ]
    )
    clusterer = Clusterer(embeddings=embeddings, llm=llm_client)

    with pytest.raises(InsufficientPoolError):
        await clusterer.refresh(state)

    embeddings.cleanup()
