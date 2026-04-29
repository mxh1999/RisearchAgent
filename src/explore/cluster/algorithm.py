"""HDBSCAN clustering + per-cluster representative / metadata derivation.

Pure (non-LLM) algorithm layer. Deterministic given the same embeddings,
HDBSCAN params, and paper records — fully unit-testable without network.

See docs/onboard-redesign/09-clusterer.md sections "HDBSCAN 参数" and
"派生视图".
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

import hdbscan
import numpy as np

if TYPE_CHECKING:
    from src.explore.state import PaperRecord


logger = logging.getLogger(__name__)


# —— HDBSCAN parameters (per 09-clusterer.md) ——
CLUSTER_MIN_SIZE = 5
CLUSTER_MIN_SAMPLES = 3
CLUSTER_METRIC = "cosine"
MIN_POOL_SIZE_FOR_CLUSTERING = 20

# —— Derived view parameters ——
N_REPRESENTATIVES_PER_CLUSTER = 5
SHARED_BENCHMARK_MIN_PAPERS = 2
TOP_AUTHORS_PER_CLUSTER = 5

# —— Density classification ——
DENSITY_DENSE_THRESHOLD = 0.8
DENSITY_SPARSE_THRESHOLD = 0.4


@dataclass
class HDBSCANResult:
    """Raw HDBSCAN output, indexed by position in the input arxiv_ids list."""
    labels: np.ndarray  # int array; -1 = noise, others are cluster ids
    probabilities: np.ndarray  # per-point cluster membership probability


@dataclass
class RawCluster:
    """A cluster before LLM-driven labeling. Has all derived metrics."""
    temp_id: int  # raw HDBSCAN cluster id (used for ordering)
    paper_ids: list[str]
    centroid_paper_id: str
    representative_paper_ids: list[str]
    shared_benchmarks: list[str]
    top_authors: list[str]
    year_range: tuple[int, int]
    density: Literal["dense", "sparse", "mixed"]
    mean_probability: float


def run_hdbscan(
    embeddings: np.ndarray,
    *,
    min_cluster_size: int = CLUSTER_MIN_SIZE,
    min_samples: int = CLUSTER_MIN_SAMPLES,
) -> HDBSCANResult:
    """Run HDBSCAN with cosine distance on a (N, D) embedding matrix.

    HDBSCAN doesn't natively support cosine; we work around it by computing a
    precomputed distance matrix using cosine. For our scale (≤ 300 papers),
    the O(N²) distance matrix is fine (a few hundred KB).
    """
    if embeddings.shape[0] == 0:
        return HDBSCANResult(
            labels=np.array([], dtype=int),
            probabilities=np.array([], dtype=float),
        )

    # Cosine distance = 1 - cosine_similarity. Normalize then dot for similarity.
    # We hand-compute the distance matrix to avoid hdbscan's metric quirks.
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # avoid /0 for any zero vectors
    normalized = embeddings / norms
    similarity = normalized @ normalized.T
    # Clip to [-1, 1] to absorb tiny float rounding errors before subtraction
    similarity = np.clip(similarity, -1.0, 1.0)
    distance = 1.0 - similarity
    # Ensure exact symmetry & non-negative diagonal
    distance = (distance + distance.T) / 2.0
    np.fill_diagonal(distance, 0.0)
    # HDBSCAN requires double-precision when using metric='precomputed'
    distance = distance.astype(np.float64)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="precomputed",
        cluster_selection_method="eom",
    )
    clusterer.fit(distance)

    return HDBSCANResult(
        labels=np.asarray(clusterer.labels_),
        probabilities=np.asarray(clusterer.probabilities_),
    )


def select_representatives(
    cluster_embeddings: np.ndarray,
    cluster_paper_ids: list[str],
    n: int = N_REPRESENTATIVES_PER_CLUSTER,
) -> tuple[str, list[str]]:
    """Pick centroid paper + top-N representative papers by proximity to centroid.

    Returns (centroid_paper_id, representative_paper_ids) where the centroid
    is also the first element of representative_paper_ids.
    """
    assert len(cluster_paper_ids) > 0
    centroid = cluster_embeddings.mean(axis=0)
    centroid_norm = np.linalg.norm(centroid) or 1.0
    centroid_unit = centroid / centroid_norm

    # Compute cosine distance of each member to centroid
    member_norms = np.linalg.norm(cluster_embeddings, axis=1)
    member_norms = np.where(member_norms == 0, 1.0, member_norms)
    member_units = cluster_embeddings / member_norms[:, None]
    cos_sims = member_units @ centroid_unit
    cos_sims = np.clip(cos_sims, -1.0, 1.0)
    distances = 1.0 - cos_sims

    sort_idx = np.argsort(distances)
    sorted_ids = [cluster_paper_ids[i] for i in sort_idx]
    return sorted_ids[0], sorted_ids[: max(n, 1)]


def classify_density(probabilities: np.ndarray) -> Literal["dense", "sparse", "mixed"]:
    """HDBSCAN gives each point a cluster membership probability. Use mean."""
    if probabilities.size == 0:
        return "sparse"
    mean = float(probabilities.mean())
    if mean > DENSITY_DENSE_THRESHOLD:
        return "dense"
    if mean < DENSITY_SPARSE_THRESHOLD:
        return "sparse"
    return "mixed"


def derive_cluster_metadata(
    cluster_papers: list["PaperRecord"],
) -> tuple[list[str], list[str], tuple[int, int]]:
    """Compute (shared_benchmarks, top_authors, year_range) from member papers.

    - shared_benchmarks: from SkimResult, only those appearing in ≥ 2 papers.
      In M3 most papers won't have skim yet, so this will commonly be empty.
    - top_authors: top-K most frequent authors (counting only first 3 of each
      paper to deweight long author lists).
    - year_range: (min_year, max_year) over published dates.
    """
    benches: Counter = Counter()
    authors: Counter = Counter()
    years: list[int] = []

    for p in cluster_papers:
        if p.skim is not None:
            benches.update(p.skim.benchmarks)
        authors.update(p.authors[:3])
        years.append(p.published.year)

    shared_benchmarks = [
        b for b, cnt in benches.most_common(5) if cnt >= SHARED_BENCHMARK_MIN_PAPERS
    ]
    top_authors = [a for a, _ in authors.most_common(TOP_AUTHORS_PER_CLUSTER)]
    year_range = (min(years), max(years)) if years else (0, 0)

    return shared_benchmarks, top_authors, year_range


def assemble_raw_clusters(
    arxiv_ids: list[str],
    embeddings: np.ndarray,
    hdbscan_result: HDBSCANResult,
    paper_records: dict[str, "PaperRecord"],
) -> tuple[list[RawCluster], list[str]]:
    """Group HDBSCAN labels into RawCluster objects + collect noise points.

    Returns (sorted_clusters, noise_paper_ids). Clusters are sorted by
    descending size for stable ordering downstream.
    """
    labels = hdbscan_result.labels
    probs = hdbscan_result.probabilities
    raw_clusters: list[RawCluster] = []
    noise: list[str] = []

    unique_labels = sorted(set(int(l) for l in labels) - {-1})

    for label_id in unique_labels:
        member_idx = np.where(labels == label_id)[0]
        member_ids = [arxiv_ids[i] for i in member_idx]
        member_emb = embeddings[member_idx]
        member_probs = probs[member_idx]

        centroid_id, representatives = select_representatives(member_emb, member_ids)
        density = classify_density(member_probs)
        member_papers = [paper_records[aid] for aid in member_ids]
        shared_benchmarks, top_authors, year_range = derive_cluster_metadata(
            member_papers
        )

        raw_clusters.append(
            RawCluster(
                temp_id=int(label_id),
                paper_ids=member_ids,
                centroid_paper_id=centroid_id,
                representative_paper_ids=representatives,
                shared_benchmarks=shared_benchmarks,
                top_authors=top_authors,
                year_range=year_range,
                density=density,
                mean_probability=float(member_probs.mean()) if member_probs.size else 0.0,
            )
        )

    # Noise points
    noise_idx = np.where(labels == -1)[0]
    noise = [arxiv_ids[i] for i in noise_idx]

    # Sort clusters by descending size for stable downstream ordering
    raw_clusters.sort(key=lambda c: (-len(c.paper_ids), c.temp_id))

    return raw_clusters, noise


__all__ = [
    "CLUSTER_MIN_SIZE",
    "CLUSTER_MIN_SAMPLES",
    "MIN_POOL_SIZE_FOR_CLUSTERING",
    "HDBSCANResult",
    "RawCluster",
    "run_hdbscan",
    "select_representatives",
    "classify_density",
    "derive_cluster_metadata",
    "assemble_raw_clusters",
]
