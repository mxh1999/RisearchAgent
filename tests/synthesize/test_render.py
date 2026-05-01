"""Deterministic Markdown render tests for FieldMap.

render_field_map is a pure function — same input produces byte-identical
output. These tests pin the expected structure (section headers, link
format, table format) so changes are reviewed deliberately.
"""

from __future__ import annotations

from src.synthesize import render_field_map
from src.synthesize.types import FieldMap, Header
from datetime import datetime
from tests.synthesize.conftest import make_minimal_field_map


def test_render_minimal_includes_all_sections():
    fm = make_minimal_field_map()
    md = render_field_map(fm)

    # All section headings present
    assert "# Field Map: Embodied navigation" in md
    assert "## Sub-areas" in md
    assert "## Dominant Benchmarks" in md
    assert "## Classic Baselines" in md
    assert "## Active Groups" in md
    assert "## Open Questions" in md
    assert "## Anchor Papers (for SOTA seeding)" in md

    # Schools of thought omitted because the fixture has none
    assert "## Schools of Thought" not in md

    # arxiv links are well-formed
    assert "[2401.00001](https://arxiv.org/abs/2401.00001)" in md

    # Table header for benchmarks
    assert "| Benchmark | Task | Papers | Sub-areas |" in md


def test_render_includes_notes_when_present():
    fm = make_minimal_field_map()
    fm.notes = [
        "Citation provider was unavailable — Classic Baselines may be incomplete.",
        "Intent appears to span disjoint areas: VLN and SLAM.",
    ]
    md = render_field_map(fm)
    assert "> **Notes:**" in md
    assert "Citation provider was unavailable" in md
    assert "Intent appears to span disjoint areas" in md


def test_render_handles_empty_optional_sections():
    """A FieldMap with only header + sub_areas should still render cleanly."""
    fm = make_minimal_field_map()
    fm.dominant_benchmarks = []
    fm.classic_baselines = []
    fm.active_groups = []
    fm.open_questions = []
    fm.anchor_papers = []
    md = render_field_map(fm)
    # Required sections present
    assert "# Field Map:" in md
    assert "## Sub-areas" in md
    # Empty optional sections omitted entirely (not "## Section\n\n_(empty)_")
    assert "## Dominant Benchmarks" not in md
    assert "## Classic Baselines" not in md
    assert "## Active Groups" not in md
    assert "## Open Questions" not in md
    assert "## Anchor Papers" not in md


def test_render_no_subareas_shows_placeholder():
    """If sub_areas is empty (clusterer never ran), say so explicitly."""
    fm = make_minimal_field_map()
    fm.sub_areas = []
    md = render_field_map(fm)
    assert "## Sub-areas" in md
    assert "no sub-areas" in md.lower()


def test_render_is_deterministic_byte_identical():
    """Same input → byte-identical output."""
    fm = make_minimal_field_map()
    a = render_field_map(fm)
    b = render_field_map(fm)
    assert a == b


def test_render_links_use_arxiv_abs_url():
    fm = make_minimal_field_map()
    md = render_field_map(fm)
    # Anchor + Classic baselines + sub-area reps all use the same URL pattern
    for aid in ("2401.00001", "2401.00002", "1806.00001"):
        assert f"https://arxiv.org/abs/{aid}" in md


def test_render_subarea_layout_has_labels_and_year_range():
    fm = make_minimal_field_map()
    md = render_field_map(fm)
    assert "### `vln-ce` — Vision-Language Navigation (CE)" in md
    assert "**Year range:** 2020–2024" in md
    assert "**Shared benchmarks:** R2R, RxR" in md
    assert "**Active authors:** Wang L., Chen S." in md
