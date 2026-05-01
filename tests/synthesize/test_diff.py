"""Deterministic tests for FieldMap diff (refine flow)."""

from __future__ import annotations

from src.synthesize import diff_field_maps, render_diff_markdown
from src.synthesize.types import (
    BenchmarkEntry,
    PaperRef,
    SubArea,
)
from tests.synthesize.conftest import make_minimal_field_map


def _sa(slug: str, label: str, n_reps: int) -> SubArea:
    return SubArea(
        slug=slug,
        display_label=label,
        description="A sub-area sufficient for diff tests.",
        representative_papers=[
            PaperRef(arxiv_id=f"24{slug[:2]:02s}.{i:05d}", title=f"{label} {i}")
            for i in range(n_reps)
        ],
        shared_benchmarks=[],
        active_authors=[],
        year_range=(2024, 2024),
    )


def test_diff_no_changes():
    fm = make_minimal_field_map()
    d = diff_field_maps(fm, fm)
    assert d.new_subareas == []
    assert d.removed_subareas == []
    assert d.grown_subareas == []
    assert d.shrunk_subareas == []
    md = render_diff_markdown(d)
    assert "No structural changes" in md


def test_diff_new_subarea():
    old = make_minimal_field_map()
    new = old.model_copy(deep=True)
    new.sub_areas = [*new.sub_areas, _sa("video-nav", "Video navigation", 4)]
    d = diff_field_maps(old, new)
    assert len(d.new_subareas) == 1
    assert d.new_subareas[0].slug == "video-nav"
    md = render_diff_markdown(d)
    assert "## New sub-areas" in md
    assert "video-nav" in md


def test_diff_removed_subarea():
    old = make_minimal_field_map()
    new = old.model_copy(deep=True)
    new.sub_areas = []  # all sub-areas removed
    d = diff_field_maps(old, new)
    assert len(d.removed_subareas) == 1
    assert d.removed_subareas[0].slug == "vln-ce"
    md = render_diff_markdown(d)
    assert "## Removed sub-areas" in md


def test_diff_grown_and_shrunk_subareas():
    old = make_minimal_field_map()  # vln-ce has 2 reps
    new = old.model_copy(deep=True)
    # Replace sub-areas: vln-ce grows to 3 reps; add a shrunk sub-area
    new.sub_areas = [
        SubArea(
            slug="vln-ce",
            display_label="Vision-Language Navigation (CE)",
            description=old.sub_areas[0].description,
            representative_papers=[
                PaperRef(arxiv_id=f"24A{i}", title=f"new rep {i}") for i in range(3)
            ],
            shared_benchmarks=[],
            active_authors=[],
            year_range=(2020, 2025),
        ),
    ]
    d = diff_field_maps(old, new)
    assert len(d.grown_subareas) == 1
    grew = d.grown_subareas[0]
    assert grew.slug == "vln-ce"
    assert grew.n_old == 2 and grew.n_new == 3
    md = render_diff_markdown(d)
    assert "## Grown sub-areas" in md
    assert "+1" in md or "→ 3" in md


def test_diff_new_benchmarks():
    old = make_minimal_field_map()
    new = old.model_copy(deep=True)
    new.dominant_benchmarks = [
        *new.dominant_benchmarks,
        BenchmarkEntry(
            name="HM3D-ObjNav",
            task="Object goal navigation",
            n_papers=12,
            associated_subarea_slugs=["vln-ce"],
        ),
    ]
    d = diff_field_maps(old, new)
    assert len(d.new_benchmarks) == 1
    assert d.new_benchmarks[0].name == "HM3D-ObjNav"
    md = render_diff_markdown(d)
    assert "## New benchmarks" in md
    assert "HM3D-ObjNav" in md


def test_diff_removed_benchmarks_listed():
    old = make_minimal_field_map()  # has R2R
    new = old.model_copy(deep=True)
    new.dominant_benchmarks = []
    d = diff_field_maps(old, new)
    assert "R2R" in d.removed_benchmarks
    md = render_diff_markdown(d)
    assert "## Removed benchmarks" in md
    assert "R2R" in md
