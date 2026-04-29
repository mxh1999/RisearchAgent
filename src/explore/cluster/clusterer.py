"""Clusterer entry point.

Pipeline (per docs/onboard-redesign/09-clusterer.md):
  1. Pull paper embeddings from EmbeddingStore
  2. Run HDBSCAN
  3. Build per-cluster derived views (representatives, year_range, density,
     shared_benchmarks, top_authors)
  4. LLM batch label (with prev-snapshot context for slug stability)
  5. Build ClusterSnapshot
  6. Update paper_pool entries (paper.cluster_id, paper.is_noise)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import numpy as np

from src.explore.cluster.algorithm import (
    MIN_POOL_SIZE_FOR_CLUSTERING,
    assemble_raw_clusters,
    run_hdbscan,
)
from src.explore.cluster.labeling import label_clusters
from src.explore.state import Cluster, ClusterSnapshot

if TYPE_CHECKING:
    from src.explore.cluster.algorithm import RawCluster
    from src.explore.cluster.labeling import ClusterLabel
    from src.explore.embeddings import EmbeddingStore
    from src.explore.state import ExplorationState
    from src.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


class InsufficientPoolError(RuntimeError):
    """Raised when refresh is invoked but pool < MIN_POOL_SIZE_FOR_CLUSTERING."""


@dataclass
class ClusterRefreshResult:
    """Summary returned to Executor for inclusion in ActionResult."""
    snapshot_id: str
    n_clusters: int
    new_slugs: list[str]            # slugs not present in prev snapshot
    disappeared_slugs: list[str]    # slugs in prev but not in new
    structural_change_rate: float   # 1 - jaccard(prev_slugs, new_slugs)
    n_noise: int
    used_fallback_labels: bool


class Clusterer:
    """Per-run clustering coordinator. Constructed once, refresh() called many times."""

    def __init__(
        self,
        embeddings: "EmbeddingStore",
        llm: "GeminiClient",
        *,
        labeling_model: Optional[str] = None,
    ):
        self.embeddings = embeddings
        self.llm = llm
        self.labeling_model = labeling_model  # None → default to filter_model in label_clusters

    async def refresh(self, state: "ExplorationState") -> ClusterRefreshResult:
        """Re-cluster the entire pool and replace state.cluster_snapshot.

        Raises InsufficientPoolError when pool < MIN_POOL_SIZE_FOR_CLUSTERING;
        the caller (Executor) maps this to a clean "skipped" ActionResult.
        """
        if state.pool_size < MIN_POOL_SIZE_FOR_CLUSTERING:
            raise InsufficientPoolError(
                f"pool_size={state.pool_size} < MIN_POOL_SIZE_FOR_CLUSTERING="
                f"{MIN_POOL_SIZE_FOR_CLUSTERING}"
            )

        prev_snapshot = state.cluster_snapshot

        # 1. Pull embeddings (only papers that have an embedding_id set — i.e.
        #    those added via real ExplorerSearcher path with EmbeddingStore wired).
        arxiv_ids: list[str] = [
            aid for aid, p in state.paper_pool.items() if p.embedding_id is not None
        ]
        if len(arxiv_ids) < MIN_POOL_SIZE_FOR_CLUSTERING:
            raise InsufficientPoolError(
                f"only {len(arxiv_ids)} papers have embeddings (need >= "
                f"{MIN_POOL_SIZE_FOR_CLUSTERING}); is EmbeddingStore wired?"
            )

        ids_present, embedding_list = self.embeddings.get_paper_embeddings(arxiv_ids)
        embeddings_arr = np.asarray(embedding_list, dtype=np.float64)
        # Re-align arxiv_ids with what ChromaDB actually returned (in case some missing)
        arxiv_ids = list(ids_present)

        if embeddings_arr.shape[0] < MIN_POOL_SIZE_FOR_CLUSTERING:
            raise InsufficientPoolError(
                f"ChromaDB returned only {embeddings_arr.shape[0]} embeddings"
            )

        # 2. HDBSCAN
        hdbscan_result = run_hdbscan(embeddings_arr)

        # 3. Build raw clusters + noise
        raw_clusters, noise_paper_ids = assemble_raw_clusters(
            arxiv_ids=arxiv_ids,
            embeddings=embeddings_arr,
            hdbscan_result=hdbscan_result,
            paper_records=state.paper_pool,
        )

        # 4. LLM batch label (one Flash call). Returns same-order ClusterLabels.
        #    On any failure, falls back to placeholder labels — never raises.
        used_fallback = False
        if not raw_clusters:
            labels: list = []
        else:
            labels = await label_clusters(
                raw_clusters=raw_clusters,
                prev_snapshot=prev_snapshot,
                paper_pool=state.paper_pool,
                llm=self.llm,
                model=self.labeling_model,
            )
            # Detect fallback: all slugs match cluster-N pattern with sequential
            used_fallback = all(
                labels[i].slug == f"cluster-{i}" and labels[i].inherited_from_slug is None
                for i in range(len(labels))
            ) and len(labels) >= 1

        # 5. Build ClusterSnapshot
        snapshot_id = f"snap-{uuid.uuid4().hex[:8]}"
        clusters = self._build_clusters(
            raw_clusters=raw_clusters,
            labels=labels,
            prev_snapshot=prev_snapshot,
            snapshot_id=snapshot_id,
        )

        new_snapshot = ClusterSnapshot(
            snapshot_id=snapshot_id,
            generated_at=datetime.now(),
            generated_after_turn=state.turn,
            n_papers_at_time=embeddings_arr.shape[0],
            algorithm="hdbscan",
            params={
                "min_cluster_size": int(hdbscan_result.labels.size and 5),
                "metric": "cosine",
            },
            clusters=clusters,
            noise_paper_ids=noise_paper_ids,
            prev_snapshot_id=prev_snapshot.snapshot_id if prev_snapshot else None,
        )

        # 6. Update state.paper_pool: cluster_id + is_noise
        slug_by_aid: dict[str, str] = {}
        for c in clusters:
            for aid in c.paper_ids:
                slug_by_aid[aid] = c.slug
        for aid, paper in state.paper_pool.items():
            paper.cluster_id = slug_by_aid.get(aid)
            paper.is_noise = aid in noise_paper_ids

        # Replace snapshot atomically (state field is the single source of truth)
        state.cluster_snapshot = new_snapshot

        # 7. Compute summary metrics
        prev_slug_set = (
            {c.slug for c in prev_snapshot.clusters} if prev_snapshot else set()
        )
        new_slug_set = {c.slug for c in clusters}
        new_slugs = sorted(new_slug_set - prev_slug_set)
        disappeared_slugs = sorted(prev_slug_set - new_slug_set)
        union = prev_slug_set | new_slug_set
        intersection = prev_slug_set & new_slug_set
        structural_change_rate = (
            1.0 - (len(intersection) / len(union)) if union else 0.0
        )

        return ClusterRefreshResult(
            snapshot_id=snapshot_id,
            n_clusters=len(clusters),
            new_slugs=new_slugs,
            disappeared_slugs=disappeared_slugs,
            structural_change_rate=structural_change_rate,
            n_noise=len(noise_paper_ids),
            used_fallback_labels=used_fallback,
        )

    # —————————————————————————————————————————————————————

    def _build_clusters(
        self,
        raw_clusters: list["RawCluster"],
        labels: list["ClusterLabel"],
        prev_snapshot: Optional[ClusterSnapshot],
        snapshot_id: str,
    ) -> list[Cluster]:
        prev_by_slug: dict[str, Cluster] = (
            {c.slug: c for c in prev_snapshot.clusters} if prev_snapshot else {}
        )

        clusters: list[Cluster] = []
        for rc, label in zip(raw_clusters, labels):
            inherited_slug = label.inherited_from_slug
            first_seen = (
                prev_by_slug[inherited_slug].first_seen_in_snapshot
                if inherited_slug and inherited_slug in prev_by_slug
                else snapshot_id
            )
            clusters.append(
                Cluster(
                    slug=label.slug,
                    display_label=label.display_label,
                    description=label.description,
                    paper_ids=rc.paper_ids,
                    size=len(rc.paper_ids),
                    centroid_paper_id=rc.centroid_paper_id,
                    representative_paper_ids=rc.representative_paper_ids,
                    shared_benchmarks=rc.shared_benchmarks,
                    top_authors=rc.top_authors,
                    year_range=rc.year_range,
                    density=rc.density,
                    inherited_from_slug=inherited_slug,
                    first_seen_in_snapshot=first_seen,
                    user_edits=[],
                )
            )
        return clusters
