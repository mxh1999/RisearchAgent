"""Clusterer module: HDBSCAN over Gemini embeddings + LLM batch slug labeling.

See docs/onboard-redesign/09-clusterer.md for the design.

Public API:
  Clusterer.refresh(state) -> ClusterRefreshResult
"""

from src.explore.cluster.clusterer import (
    Clusterer,
    ClusterRefreshResult,
    InsufficientPoolError,
)

__all__ = ["Clusterer", "ClusterRefreshResult", "InsufficientPoolError"]
