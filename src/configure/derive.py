"""Derive a config.yaml dict from a FieldMap + ConfigureSession.

Pure function — no LLM, no I/O. The Synthesize stage already produced
labels, descriptions, sub-area metadata; this is just the projection
into the main pipeline's config schema.

Per docs/onboard-redesign/12-configure.md "派生 config.yaml".
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from src.configure.session import ConfigureSession
from src.explore.state import ExplorationState
from src.synthesize.types import FieldMap, SubArea


# Default categories when state has no per-paper category info.
DEFAULT_CATEGORIES = ["cs.AI"]


def _categories_for_subarea(
    sa: SubArea, state: Optional[ExplorationState], top_k: int = 3
) -> list[str]:
    """Most frequent ArXiv categories among the cluster's papers."""
    if state is None or state.cluster_snapshot is None:
        return DEFAULT_CATEGORIES.copy()

    cluster = next(
        (c for c in state.cluster_snapshot.clusters if c.slug == sa.slug), None
    )
    if cluster is None:
        return DEFAULT_CATEGORIES.copy()

    counter: Counter = Counter()
    for aid in cluster.paper_ids:
        paper = state.paper_pool.get(aid)
        if paper is None:
            continue
        counter.update(paper.categories)
    if not counter:
        return DEFAULT_CATEGORIES.copy()
    return [cat for cat, _ in counter.most_common(top_k)]


def _query_for_subarea(sa: SubArea) -> str:
    """Heuristic query for the main pipeline's ArxivScraper.

    Combines the display_label with shared_benchmarks if present. Quotes
    multi-word terms to keep ArXiv's relevance ranking sane. We deliberately
    don't ask an LLM for a query in M8 v1 — the labels are already LLM-
    refined during Synthesize, and a quoted phrase is good enough for the
    main pipeline's daily crawl.
    """
    parts: list[str] = []
    label = sa.display_label.strip()
    # Wrap multi-word phrase in quotes, leave single tokens alone
    if " " in label:
        parts.append(f'"{label}"')
    elif label:
        parts.append(label)

    for bench in sa.shared_benchmarks[:2]:
        b = bench.strip()
        if not b:
            continue
        if " " in b:
            parts.append(f'"{b}"')
        else:
            parts.append(b)

    return " ".join(parts) if parts else sa.slug


def derive_config(
    fm: FieldMap,
    session: ConfigureSession,
    intent_text: str,
    *,
    state: Optional[ExplorationState] = None,
    base_config: Optional[dict] = None,
) -> dict:
    """Build a full config.yaml dict from session selections.

    base_config (optional): existing config.yaml to merge defaults from
    (preserves llm/scraper/path settings). The "topics" and "filter"
    sections are always replaced.
    """
    out: dict = dict(base_config or {})

    # Topics from selected sub-areas, preserving FieldMap order
    topics: list[dict] = []
    for sa in fm.sub_areas:
        if not session.is_selected(sa.slug):
            continue
        topics.append(
            {
                "name": session.label_for(sa.slug, sa.display_label),
                "query": _query_for_subarea(sa),
                "categories": _categories_for_subarea(sa, state),
                "research_profile": sa.description,
            }
        )

    out["topics"] = topics

    # Filter section
    threshold = session.relevance_threshold
    out["filter"] = {
        "relevance_threshold": threshold,
        "borderline_min": max(threshold - 2, 2),
    }

    # Sensible defaults for sections that don't get touched
    out.setdefault(
        "llm",
        {
            "filter_model": "gemini-2.5-flash",
            "reader_model": "gemini-2.5-pro",
            "embedding_model": "gemini-embedding-001",
            "max_concurrent": 5,
            "temperature": 0.3,
        },
    )
    out.setdefault(
        "scraper",
        {
            "max_results_per_topic": 20,
            "delay_seconds": 3.0,
            "days_lookback": 30,
        },
    )
    out.setdefault("db_path", "data/papers.db")
    out.setdefault("chroma_path", "data/chroma")
    out.setdefault("pdf_dir", "data/pdfs")
    out.setdefault("sota_dir", "data/sota")

    return out


def pick_anchor_paper_ids(
    fm: FieldMap, session: ConfigureSession
) -> dict[str, list[str]]:
    """Per selected slug, pick anchor arxiv_ids for SOTA seeding.

    Uses FieldMap.anchor_papers as the primary source — Synthesize already
    chose them based on citation × centrality. Filters to:
      - Slugs the user kept selected
      - Caps each slug to session.anchor_count[slug]

    Returns: {slug: [arxiv_id, ...]}
    """
    by_slug: dict[str, list[str]] = {}
    for ap in fm.anchor_papers:
        if ap.cluster_slug not in session.selected_slugs:
            continue
        by_slug.setdefault(ap.cluster_slug, []).append(ap.arxiv_id)

    # Cap per-cluster
    capped: dict[str, list[str]] = {}
    from src.configure.session import DEFAULT_ANCHOR_COUNT_PER_CLUSTER

    for slug, ids in by_slug.items():
        n = session.anchor_count.get(slug, DEFAULT_ANCHOR_COUNT_PER_CLUSTER)
        capped[slug] = ids[: max(n, 0)]
    return capped


__all__ = ["derive_config", "pick_anchor_paper_ids"]
