"""End-to-end synthesize test: ExplorationState → FieldMap (real Pro call).

Builds a complete synthetic ExplorationState with a populated cluster_snapshot
and counters, runs synthesize() against real Gemini Pro, and verifies the
returned FieldMap is structurally valid and references only real arxiv_ids.

Cost: ~1 Pro call per test (~$0.03-0.05).
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from src.config import LLMConfig
from src.explore.state import (
    ActionRecord,
    BudgetState,
    Cluster,
    ClusterSnapshot,
    Counters,
    CoverageQuestion,
    CoverageReport,
    ExplorationState,
    Intent,
    PaperRecord,
    QueryRecord,
    RunMetadata,
)
from src.explore.actions import SearchAction
from src.llm.gemini_client import GeminiClient
from src.synthesize import (
    SynthesisError,
    render_field_map,
    synthesize,
    validate_citations,
)


pytestmark = pytest.mark.llm


@pytest.fixture
def llm_client():
    """Local llm fixture for synthesize tests (mirrors tests/explore/conftest)."""
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")
    return GeminiClient(
        LLMConfig(
            filter_model=os.getenv("GEMINI_FILTER_MODEL", "gemini-3-flash"),
            reader_model=os.getenv("GEMINI_READER_MODEL", "gemini-2.5-pro"),
            embedding_model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
            api_key=api_key,
            max_concurrent=3,
            temperature=0.3,
            base_url=os.getenv("GEMINI_BASE_URL") or None,
            embedding_api_key=os.getenv("GEMINI_EMBEDDING_API_KEY") or None,
            embedding_base_url=os.getenv("GEMINI_EMBEDDING_BASE_URL") or None,
        )
    )


def _paper(aid: str, title: str, abstract: str, year: int = 2024) -> PaperRecord:
    return PaperRecord(
        arxiv_id=aid,
        title=title,
        abstract=abstract,
        authors=["Author A", "Author B"],
        published=date(year, 1, 1),
        categories=["cs.RO"],
        pdf_url="",
        first_seen_turn=1,
        source="search",
        embedding_id=aid,
    )


def _build_synthetic_state() -> ExplorationState:
    """A fully populated state, ready for synthesize."""
    now = datetime.now()
    state = ExplorationState(
        metadata=RunMetadata(
            run_id="syn-e2e",
            started_at=now,
            last_updated_at=now,
            code_version="test",
            status="running",
        ),
        intent=Intent(
            natural_language=(
                "Embodied navigation in 3D environments — vision-language "
                "navigation and zero-shot object goal navigation."
            ),
        ),
        budget=BudgetState(elapsed_seconds=420.0),
        counters=Counters(
            benchmark_counter={"R2R": ["a1", "a2"], "HM3D-ObjNav": ["b1", "b2", "b3"]},
            author_counter={"Wang L.": ["a1", "a2", "a3"], "Chen S.": ["b1", "b2"]},
            venue_counter={"2024": ["a1", "a2", "b1"], "2023": ["a3", "b2"]},
        ),
    )

    # Populate paper_pool: 2 clusters' worth + 1 classic
    vln_papers = [
        _paper(
            "2401.00010",
            "Vision-Language Navigation in Continuous Environments",
            "We tackle vision-language navigation (VLN) where agents follow "
            "natural language instructions in unconstrained 3D environments. "
            "We benchmark on R2R and RxR.",
        ),
        _paper(
            "2401.00011",
            "Cross-View Matching for VLN",
            "Cross-view feature matching to ground language instructions for "
            "navigation tasks on R2R-CE.",
        ),
        _paper(
            "2401.00012",
            "Sim-to-real for VLN-CE",
            "Transfer learning from simulation to real-world for VLN-CE.",
        ),
    ]
    objnav_papers = [
        _paper(
            "2402.00010",
            "Zero-Shot ObjectGoal Navigation with CLIP",
            "Open-vocab object goal navigation using CLIP-based features on "
            "HM3D-ObjectNav benchmark.",
        ),
        _paper(
            "2402.00011",
            "Open-Vocab ObjNav Survey",
            "Open-vocabulary object goal navigation evaluated on HM3D ObjectNav.",
        ),
    ]
    classic = _paper(
        "1806.00001",
        "Original VLN: R2R Benchmark Paper",
        "Introducing Room-to-Room (R2R), a benchmark for vision-language "
        "navigation in photorealistic environments.",
        year=2018,
    )
    for p in vln_papers + objnav_papers + [classic]:
        state.paper_pool[p.arxiv_id] = p

    # cluster_snapshot
    state.cluster_snapshot = ClusterSnapshot(
        snapshot_id="snap-1",
        generated_at=now,
        generated_after_turn=4,
        n_papers_at_time=len(state.paper_pool),
        clusters=[
            Cluster(
                slug="vln-ce",
                display_label="Vision-Language Navigation (Continuous)",
                description="VLN agents in continuous environments",
                paper_ids=[p.arxiv_id for p in vln_papers] + [classic.arxiv_id],
                size=len(vln_papers) + 1,
                centroid_paper_id=vln_papers[0].arxiv_id,
                representative_paper_ids=[
                    vln_papers[0].arxiv_id,
                    vln_papers[1].arxiv_id,
                    classic.arxiv_id,
                ],
                shared_benchmarks=["R2R", "RxR"],
                top_authors=["Wang L."],
                year_range=(2018, 2024),
                density="dense",
                first_seen_in_snapshot="snap-1",
            ),
            Cluster(
                slug="objnav-zeroshot",
                display_label="Zero-Shot Object Goal Navigation",
                description="Open-vocabulary ObjNav",
                paper_ids=[p.arxiv_id for p in objnav_papers],
                size=len(objnav_papers),
                centroid_paper_id=objnav_papers[0].arxiv_id,
                representative_paper_ids=[p.arxiv_id for p in objnav_papers],
                shared_benchmarks=["HM3D-ObjNav"],
                top_authors=["Chen S."],
                year_range=(2024, 2024),
                density="dense",
                first_seen_in_snapshot="snap-1",
            ),
        ],
    )

    # Coverage report (passing)
    state.coverage_report = CoverageReport(
        generated_at=now,
        generated_after_turn=4,
        questions=[
            CoverageQuestion(
                question="What sub-areas does the field decompose into?",
                answer_available=True,
                evidence="2 clusters",
            ),
        ],
        passes=True,
        unanswered_count=0,
    )

    # 2 query records to give n_queries
    for i in range(2):
        state.query_log.append(
            QueryRecord(
                query_id=f"q-{i}",
                turn=i + 1,
                query_text=f"q{i}",
                categories=["cs.RO"],
                source="llm_generated",
                n_results_raw=5,
                n_new_to_pool=4,
                executed_at=now,
            )
        )

    # Action history with one executed search so state.turn > 0
    state.action_history.append(
        ActionRecord(
            turn=1,
            action=SearchAction(query="seed", reasoning="initial search for fixture"),
            was_executed=True,
            spec_verdict="allow",
            outcome="success",
            outcome_summary="+5 papers",
        )
    )

    return state


# —————————————————————————————————————————————————————————————
# Tests
# —————————————————————————————————————————————————————————————


async def test_synthesize_returns_valid_field_map(llm_client: GeminiClient):
    state = _build_synthetic_state()

    fm = await synthesize(state, llm_client)

    # FieldMap is structurally valid (pydantic checks ran)
    assert fm.header.intent_snippet
    assert fm.header.n_papers_surveyed == state.pool_size
    assert fm.header.n_queries == len(state.query_log)

    # Sub-areas should be ≥ 1 (we gave 2 clusters; LLM may merge to 1 in extreme cases)
    assert len(fm.sub_areas) >= 1

    # Every referenced arxiv_id is in the pool
    validate_citations(fm, state)  # would raise on hallucination

    # Slugs in sub_areas are real cluster slugs
    cluster_slugs = {c.slug for c in state.cluster_snapshot.clusters}
    for sa in fm.sub_areas:
        assert sa.slug in cluster_slugs


async def test_synthesize_renders_to_markdown(llm_client: GeminiClient):
    """Sanity that the produced FieldMap renders to non-trivial Markdown."""
    state = _build_synthetic_state()
    fm = await synthesize(state, llm_client)
    md = render_field_map(fm)
    assert md.startswith("# Field Map: ")
    assert "## Sub-areas" in md
    # At least one of our cluster slugs appears in the Markdown
    assert any(c.slug in md for c in state.cluster_snapshot.clusters)


async def test_synthesize_records_degraded_provider_in_notes(llm_client: GeminiClient):
    """When citation_provider_degraded flag is set, the LLM should add a note."""
    state = _build_synthetic_state()
    state.metadata.citation_provider_degraded = True

    fm = await synthesize(state, llm_client)
    notes_text = " ".join(fm.notes).lower()
    # We don't enforce exact wording, but expect SOME note acknowledging degradation
    assert any(
        marker in notes_text
        for marker in ("citation", "provider", "degraded", "unavailable", "incomplete")
    ), f"Expected a degradation-related note; got notes={fm.notes!r}"
