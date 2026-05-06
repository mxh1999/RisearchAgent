"""ConfigureSession — mutable user choices accumulated during the
interactive Configure stage. Pure data class; no I/O.

Per docs/onboard-redesign/12-configure.md. M8 v1 supports:
  - select / drop a slug
  - rename display_label
  - set threshold
  - set per-cluster anchor count

Deferred (M8 v1.1+):
  - merge two clusters into one config topic (needs LLM call to derive query)
  - split a cluster into sub-clusters (needs mini-HDBSCAN)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.synthesize.types import FieldMap


DEFAULT_RELEVANCE_THRESHOLD = 6
DEFAULT_ANCHOR_COUNT_PER_CLUSTER = 3


@dataclass
class ConfigureSession:
    """User-mutable state during the Configure interactive loop."""

    selected_slugs: set[str] = field(default_factory=set)
    label_overrides: dict[str, str] = field(default_factory=dict)  # slug -> new display_label
    relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD
    anchor_count: dict[str, int] = field(default_factory=dict)  # slug -> n
    dirty: bool = False  # True after any mutation; reset by accept()

    @classmethod
    def from_field_map(cls, fm: FieldMap) -> "ConfigureSession":
        """Build defaults: select all sub-areas, threshold=6, anchor_count=3 each."""
        return cls(
            selected_slugs={sa.slug for sa in fm.sub_areas},
            label_overrides={},
            relevance_threshold=DEFAULT_RELEVANCE_THRESHOLD,
            anchor_count={
                sa.slug: DEFAULT_ANCHOR_COUNT_PER_CLUSTER for sa in fm.sub_areas
            },
            dirty=False,
        )

    # —— Mutators ————————————————————————————————————

    def select(self, slugs: list[str], all_subareas: list[str]) -> None:
        """Replace selected_slugs. all_subareas constrains valid slug names."""
        unknown = [s for s in slugs if s not in all_subareas]
        if unknown:
            raise ValueError(f"Unknown slugs: {unknown}")
        self.selected_slugs = set(slugs)
        self.dirty = True

    def select_all(self, all_subareas: list[str]) -> None:
        self.selected_slugs = set(all_subareas)
        self.dirty = True

    def select_none(self) -> None:
        self.selected_slugs = set()
        self.dirty = True

    def drop(self, slug: str) -> None:
        self.selected_slugs.discard(slug)
        self.dirty = True

    def rename(self, slug: str, label: str, all_subareas: list[str]) -> None:
        if slug not in all_subareas:
            raise ValueError(f"Unknown slug: {slug}")
        if not label.strip():
            raise ValueError("Label cannot be empty")
        self.label_overrides[slug] = label.strip()
        self.dirty = True

    def set_threshold(self, n: int) -> None:
        if not (0 <= n <= 10):
            raise ValueError("Threshold must be in [0, 10]")
        self.relevance_threshold = n
        self.dirty = True

    def set_anchor_count(self, slug: str, n: int, all_subareas: list[str]) -> None:
        if slug not in all_subareas:
            raise ValueError(f"Unknown slug: {slug}")
        if n < 0:
            raise ValueError("anchor count must be >= 0")
        self.anchor_count[slug] = n
        self.dirty = True

    def mark_committed(self) -> None:
        self.dirty = False

    # —— Accessors ————————————————————————————————

    def label_for(self, slug: str, default: str) -> str:
        """Return user-overridden label or fall back to FieldMap default."""
        return self.label_overrides.get(slug, default)

    def is_selected(self, slug: str) -> bool:
        return slug in self.selected_slugs


__all__ = [
    "ConfigureSession",
    "DEFAULT_RELEVANCE_THRESHOLD",
    "DEFAULT_ANCHOR_COUNT_PER_CLUSTER",
]
