"""LLM-driven batch labeling of cluster slugs / display labels.

Per docs/onboard-redesign/09-clusterer.md "LLM 批量 Labeling".

Single Gemini Flash call per refresh:
  - Sees ALL new clusters together (so it can ensure unique slugs)
  - Sees previous snapshot's slugs + reps (so it can reuse when content
    overlaps ≥ 50% — the stability mechanism)

Validation after the call:
  - Slug format: ^[a-z0-9]+(-[a-z0-9]+){0,2}$
  - Slug uniqueness within the new batch
  - Inheritance claim: if a slug is claimed inherited, paper-overlap
    Jaccard with the prev cluster must be ≥ 0.3 (else strip the claim)

Failure fallback (LLM down / malformed):
  - Use placeholder slugs cluster-0, cluster-1, ...
  - Standard label/description templates
  - Log warning into state.metadata; do NOT abort the run (clustering
    is supportive infra, not safety-critical).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.explore.cluster.algorithm import RawCluster
    from src.explore.state import Cluster, ClusterSnapshot, PaperRecord
    from src.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){0,2}$")
INHERIT_JACCARD_MIN = 0.3
PAPER_OVERLAP_MIN_FOR_REUSE = 0.5  # documented threshold, used in prompt


@dataclass
class ClusterLabel:
    """LLM's per-cluster output (post-validation)."""
    slug: str
    display_label: str
    description: str
    inherited_from_slug: Optional[str]


SYSTEM_PROMPT = """\
You label research-paper clusters produced by HDBSCAN.

For each cluster you receive, output a `slug` (machine id), a
`display_label` (human-readable), a one-sentence `description`, and
`inherited_from_previous_slug` (the previous cluster id this one continues,
or null).

## Slug Format (STRICT)
- Lowercase ASCII letters, digits, and hyphens only.
- 1 to 3 hyphen-separated tokens.
- Pattern: `^[a-z0-9]+(-[a-z0-9]+){0,2}$`
- Good: `zero-shot-objnav`, `vln-ce`, `slam-classical`, `llm-planner`
- Bad: `ZeroShotNav`, `zero_shot_objnav`, `zero-shot-object-goal-navigation`

## Stability Rule
If a new cluster's representative papers overlap ≥ 50% with one of the
previous-snapshot clusters, REUSE that previous slug verbatim and set
`inherited_from_previous_slug` to the old slug. Otherwise generate a new
slug and set `inherited_from_previous_slug` to null.

## Uniqueness Rule
All slugs in a single output array must be distinct. If two new clusters
would naturally get the same slug, pick a more specific slug for one of
them (e.g. `vln` vs `vln-ce`, not `vln` and `vln-2`).

## Output
Return STRICTLY a JSON array, one object per cluster, in the same order
as the input "New Clusters" list. No prose before or after.

```
[
  {"slug": "...", "display_label": "...", "description": "...",
   "inherited_from_previous_slug": "..." | null},
  ...
]
```
"""


def build_user_prompt(
    raw_clusters: list["RawCluster"],
    prev_snapshot: Optional["ClusterSnapshot"],
    paper_pool: dict[str, "PaperRecord"],
) -> str:
    parts: list[str] = []

    if prev_snapshot and prev_snapshot.clusters:
        parts.append("## Previous Snapshot Slugs (for continuity)\n")
        for c in prev_snapshot.clusters:
            parts.append(f"- slug: `{c.slug}` ({c.size} papers)")
            parts.append("  representative papers:")
            for aid in c.representative_paper_ids[:3]:
                p = paper_pool.get(aid)
                title = p.title if p else "(missing)"
                parts.append(f"    - {aid}: {title[:90]}")
        parts.append("")

    parts.append("## New Clusters to Label\n")
    for i, rc in enumerate(raw_clusters):
        parts.append(
            f"### Cluster {i} ({len(rc.paper_ids)} papers, "
            f"year_range {rc.year_range[0]}-{rc.year_range[1]}, "
            f"density={rc.density})"
        )
        parts.append("representative papers:")
        for aid in rc.representative_paper_ids[:5]:
            p = paper_pool.get(aid)
            if p is None:
                continue
            abstract_excerpt = (p.abstract or "").replace("\n", " ")[:300]
            parts.append(f"  - {aid}: {p.title[:90]}")
            parts.append(f"    abstract_excerpt: {abstract_excerpt}")
        if rc.shared_benchmarks:
            parts.append(f"shared_benchmarks: {', '.join(rc.shared_benchmarks)}")
        if rc.top_authors:
            parts.append(f"top_authors: {', '.join(rc.top_authors)}")
        parts.append("")

    parts.append(
        "Output the JSON array now (one object per cluster, in the same order):"
    )

    return "\n".join(parts)


def normalize_slug(raw: str) -> Optional[str]:
    """Best-effort coerce LLM slug to canonical form. Returns None if unsalvageable."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s:
        return None
    # Cap to 3 tokens
    parts = s.split("-")[:3]
    s = "-".join(parts)
    if SLUG_PATTERN.match(s):
        return s
    return None


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def validate_inheritance(
    new_paper_ids: list[str],
    claimed_slug: Optional[str],
    prev_snapshot: Optional["ClusterSnapshot"],
) -> Optional[str]:
    """Drop the inheritance claim if Jaccard with the named prev cluster < 0.3."""
    if claimed_slug is None or prev_snapshot is None:
        return None
    prev = next((c for c in prev_snapshot.clusters if c.slug == claimed_slug), None)
    if prev is None:
        return None  # claimed a slug that doesn't exist
    j = jaccard(set(new_paper_ids), set(prev.paper_ids))
    return claimed_slug if j >= INHERIT_JACCARD_MIN else None


def fallback_labels(raw_clusters: list["RawCluster"]) -> list[ClusterLabel]:
    return [
        ClusterLabel(
            slug=f"cluster-{i}",
            display_label=f"Cluster {i}",
            description="Auto-generated placeholder (LLM labeling unavailable).",
            inherited_from_slug=None,
        )
        for i, _ in enumerate(raw_clusters)
    ]


async def label_clusters(
    raw_clusters: list["RawCluster"],
    prev_snapshot: Optional["ClusterSnapshot"],
    paper_pool: dict[str, "PaperRecord"],
    llm: "GeminiClient",
    *,
    model: Optional[str] = None,
) -> list[ClusterLabel]:
    """Label all raw clusters in one LLM call. Returns same-order labels.

    Falls back to placeholder labels (cluster-0, cluster-1, ...) on:
      - LLM call failure
      - Malformed JSON
      - Wrong array length
    Validation always runs (slug normalization, uniqueness, inheritance).
    """
    if not raw_clusters:
        return []

    user_prompt = build_user_prompt(raw_clusters, prev_snapshot, paper_pool)
    full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    model = model or llm.config.filter_model

    try:
        raw = await llm.generate(full_prompt, model=model, json_mode=True)
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning("[cluster.labeling] LLM call failed: %s — using fallback", e)
        return fallback_labels(raw_clusters)

    if not isinstance(parsed, list) or len(parsed) != len(raw_clusters):
        logger.warning(
            "[cluster.labeling] LLM returned wrong shape "
            "(expected list of %d, got %r) — fallback",
            len(raw_clusters),
            type(parsed).__name__,
        )
        return fallback_labels(raw_clusters)

    # Per-cluster validation
    used_slugs: set[str] = set()
    out: list[ClusterLabel] = []
    for i, (entry, rc) in enumerate(zip(parsed, raw_clusters)):
        if not isinstance(entry, dict):
            logger.warning("[cluster.labeling] entry %d not a dict — fallback", i)
            return fallback_labels(raw_clusters)

        slug = normalize_slug(entry.get("slug", ""))
        if slug is None or slug in used_slugs:
            slug = f"cluster-{i}"
            disambig = 1
            while slug in used_slugs:
                slug = f"cluster-{i}-{disambig}"
                disambig += 1
        used_slugs.add(slug)

        display_label = (
            (entry.get("display_label") or "").strip() or slug.replace("-", " ").title()
        )
        description = (
            (entry.get("description") or "").strip() or "(no description provided)"
        )
        inherited = validate_inheritance(
            rc.paper_ids,
            entry.get("inherited_from_previous_slug"),
            prev_snapshot,
        )

        out.append(
            ClusterLabel(
                slug=slug,
                display_label=display_label,
                description=description,
                inherited_from_slug=inherited,
            )
        )

    return out


__all__ = [
    "SLUG_PATTERN",
    "ClusterLabel",
    "build_user_prompt",
    "normalize_slug",
    "jaccard",
    "validate_inheritance",
    "fallback_labels",
    "label_clusters",
]
