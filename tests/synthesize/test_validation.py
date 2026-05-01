"""Deterministic tests for synthesizer's citation/slug validation."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.explore.state import (
    BudgetState,
    Cluster,
    ClusterSnapshot,
    ExplorationState,
    Intent,
    PaperRecord,
    RunMetadata,
)
from src.synthesize.synthesizer import (
    SynthesisError,
    _all_arxiv_ids_in_field_map,
    validate_citations,
)
from tests.synthesize.conftest import make_minimal_field_map


def _state_with_papers(arxiv_ids: list[str], cluster_slug: str = "vln-ce"):
    now = datetime.now()
    state = ExplorationState(
        metadata=RunMetadata(
            run_id="vtest",
            started_at=now,
            last_updated_at=now,
            code_version="test",
        ),
        intent=Intent(natural_language="test"),
        budget=BudgetState(),
    )
    for aid in arxiv_ids:
        state.paper_pool[aid] = PaperRecord(
            arxiv_id=aid,
            title=f"Title {aid}",
            abstract="abstract",
            authors=["A"],
            published=date(2024, 1, 1),
            categories=["cs.AI"],
            pdf_url="",
            first_seen_turn=1,
            source="search",
        )
    state.cluster_snapshot = ClusterSnapshot(
        snapshot_id="snap",
        generated_at=now,
        generated_after_turn=1,
        n_papers_at_time=len(arxiv_ids),
        clusters=[
            Cluster(
                slug=cluster_slug,
                display_label=cluster_slug,
                description="d",
                paper_ids=arxiv_ids,
                size=len(arxiv_ids),
                centroid_paper_id=arxiv_ids[0] if arxiv_ids else None,
                representative_paper_ids=arxiv_ids[:3],
                year_range=(2024, 2024),
                density="dense",
                first_seen_in_snapshot="snap",
            )
        ],
    )
    return state


def test_collect_arxiv_ids_from_field_map():
    fm = make_minimal_field_map()
    ids = _all_arxiv_ids_in_field_map(fm)
    # Sub-area reps + classics + open question evidence + anchor papers
    assert "2401.00001" in ids  # in sub_area, anchor
    assert "2401.00002" in ids  # in sub_area, open_questions
    assert "1806.00001" in ids  # classic baselines


def test_validate_citations_passes_when_all_in_pool():
    fm = make_minimal_field_map()
    state = _state_with_papers(["2401.00001", "2401.00002", "1806.00001"])
    validate_citations(fm, state)  # no raise


def test_validate_citations_rejects_hallucinated_id():
    fm = make_minimal_field_map()
    state = _state_with_papers(["2401.00001", "2401.00002"])  # 1806.* missing
    with pytest.raises(SynthesisError) as exc_info:
        validate_citations(fm, state)
    assert "1806.00001" in str(exc_info.value)
    assert "1806.00001" in exc_info.value.details["hallucinated_ids"]


def test_validate_citations_rejects_unknown_cluster_slug():
    fm = make_minimal_field_map()
    # Reset state to have a different cluster slug than the field_map references.
    state = _state_with_papers(
        ["2401.00001", "2401.00002", "1806.00001"], cluster_slug="totally-different"
    )
    with pytest.raises(SynthesisError) as exc_info:
        validate_citations(fm, state)
    assert "vln-ce" in str(exc_info.value)


def test_validate_citations_skips_slug_check_when_no_snapshot():
    """Without a cluster_snapshot we can't validate slugs — no spurious failure."""
    fm = make_minimal_field_map()
    state = _state_with_papers(["2401.00001", "2401.00002", "1806.00001"])
    state.cluster_snapshot = None
    validate_citations(fm, state)  # no raise


def test_field_map_pydantic_rejects_short_description():
    """Pydantic min_length on SubArea.description prevents trivial outputs."""
    from src.synthesize.types import SubArea, PaperRef
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubArea(
            slug="x",
            display_label="X",
            description="too short",  # < 20 chars
            representative_papers=[PaperRef(arxiv_id="2401.00001", title="t")],
            shared_benchmarks=[],
            active_authors=[],
            year_range=(2024, 2024),
        )
