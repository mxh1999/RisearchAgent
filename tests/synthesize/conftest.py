"""Test fixtures for tests/synthesize/."""

from __future__ import annotations

from datetime import datetime

from src.synthesize.types import (
    ActiveGroup,
    AnchorPaper,
    BenchmarkEntry,
    ClassicPaper,
    FieldMap,
    Header,
    OpenQuestion,
    PaperRef,
    SchoolOfThought,
    SubArea,
)


def make_minimal_field_map(**overrides) -> FieldMap:
    """Build a small but valid FieldMap useful as a render fixture."""
    fm = FieldMap(
        header=Header(
            intent_snippet="Embodied navigation",
            generated_at=datetime(2026, 5, 2, 12, 0, 0),
            n_papers_surveyed=42,
            n_queries=8,
            elapsed_seconds=300.0,
        ),
        sub_areas=[
            SubArea(
                slug="vln-ce",
                display_label="Vision-Language Navigation (CE)",
                description=(
                    "Continuous-environment vision-language navigation: "
                    "agents follow natural-language instructions in unconstrained 3D scenes."
                ),
                representative_papers=[
                    PaperRef(arxiv_id="2401.00001", title="VLN-CE Method A"),
                    PaperRef(arxiv_id="2401.00002", title="VLN-CE Method B"),
                ],
                shared_benchmarks=["R2R", "RxR"],
                active_authors=["Wang L.", "Chen S."],
                year_range=(2020, 2024),
            )
        ],
        dominant_benchmarks=[
            BenchmarkEntry(
                name="R2R",
                task="Vision-language navigation",
                n_papers=18,
                associated_subarea_slugs=["vln-ce"],
            )
        ],
        schools_of_thought=[],
        classic_baselines=[
            ClassicPaper(
                arxiv_id="1806.00001",
                title="Original VLN Paper",
                year=2018,
                why_classic="Introduced the R2R benchmark and the VLN task formulation.",
            )
        ],
        active_groups=[
            ActiveGroup(name="Wang L.", n_papers=12, associated_subarea_slugs=["vln-ce"])
        ],
        open_questions=[
            OpenQuestion(
                question="How to transfer learned policies sim-to-real reliably?",
                evidence_papers=[
                    PaperRef(arxiv_id="2401.00002", title="VLN-CE Method B"),
                ],
            )
        ],
        anchor_papers=[
            AnchorPaper(
                arxiv_id="2401.00001",
                title="VLN-CE Method A",
                cluster_slug="vln-ce",
                rationale="High citation, central to vln-ce cluster.",
            )
        ],
        notes=[],
    )
    return fm.model_copy(update=overrides) if overrides else fm
