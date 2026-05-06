"""Deterministic tests for derive_config + pick_anchor_paper_ids."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.configure.derive import (
    DEFAULT_CATEGORIES,
    derive_config,
    pick_anchor_paper_ids,
)
from src.configure.session import ConfigureSession
from src.explore.state import (
    BudgetState,
    Cluster,
    ClusterSnapshot,
    ExplorationState,
    Intent,
    PaperRecord,
    RunMetadata,
)


def test_derive_includes_only_selected_subareas(fm):
    session = ConfigureSession.from_field_map(fm)
    session.drop("vln-ce")
    cfg = derive_config(fm, session, intent_text="test")
    # Only one sub-area in the fixture, so dropping it leaves no topics
    assert cfg["topics"] == []


def test_derive_topic_uses_label_override(fm):
    session = ConfigureSession.from_field_map(fm)
    all_slugs = [sa.slug for sa in fm.sub_areas]
    session.rename("vln-ce", "VLN-CE (focused)", all_slugs)
    cfg = derive_config(fm, session, intent_text="test")
    assert cfg["topics"][0]["name"] == "VLN-CE (focused)"


def test_derive_query_quotes_multiword_label(fm):
    session = ConfigureSession.from_field_map(fm)
    cfg = derive_config(fm, session, intent_text="test")
    query = cfg["topics"][0]["query"]
    # The fixture's label is "Vision-Language Navigation (CE)", multi-word
    assert '"Vision-Language Navigation (CE)"' in query
    # Shared benchmarks "R2R" / "RxR" appear unquoted (single-token)
    assert "R2R" in query


def test_derive_research_profile_is_subarea_description(fm):
    session = ConfigureSession.from_field_map(fm)
    cfg = derive_config(fm, session, intent_text="test")
    sa = fm.sub_areas[0]
    assert cfg["topics"][0]["research_profile"] == sa.description


def test_derive_filter_section_from_threshold(fm):
    session = ConfigureSession.from_field_map(fm)
    session.set_threshold(8)
    cfg = derive_config(fm, session, intent_text="test")
    assert cfg["filter"]["relevance_threshold"] == 8
    assert cfg["filter"]["borderline_min"] == 6  # threshold - 2


def test_derive_filter_borderline_min_floor_is_2(fm):
    session = ConfigureSession.from_field_map(fm)
    session.set_threshold(3)
    cfg = derive_config(fm, session, intent_text="test")
    # max(threshold-2, 2) = max(1, 2) = 2
    assert cfg["filter"]["borderline_min"] == 2


def test_derive_preserves_unrelated_base_config_sections(fm):
    session = ConfigureSession.from_field_map(fm)
    base = {
        "db_path": "custom/path/papers.db",
        "scraper": {"max_results_per_topic": 100, "delay_seconds": 1.0, "days_lookback": 7},
    }
    cfg = derive_config(fm, session, intent_text="test", base_config=base)
    assert cfg["db_path"] == "custom/path/papers.db"
    assert cfg["scraper"]["max_results_per_topic"] == 100
    # Topics + filter still come from session, NOT base
    assert len(cfg["topics"]) == 1


def test_derive_categories_default_when_no_state(fm):
    session = ConfigureSession.from_field_map(fm)
    cfg = derive_config(fm, session, intent_text="test", state=None)
    assert cfg["topics"][0]["categories"] == DEFAULT_CATEGORIES


def test_derive_categories_from_state_pool_frequency(fm):
    """When state has cluster + paper categories, derive picks the most frequent."""
    now = datetime.now()
    state = ExplorationState(
        metadata=RunMetadata(
            run_id="r", started_at=now, last_updated_at=now, code_version="t"
        ),
        intent=Intent(natural_language="test"),
        budget=BudgetState(),
    )
    # 3 papers in the cluster: 2 cs.RO, 1 cs.CV — top is cs.RO
    for i, cats in enumerate([["cs.RO"], ["cs.RO", "cs.CV"], ["cs.CV"]]):
        aid = fm.sub_areas[0].representative_papers[i % 2].arxiv_id
        # use distinct ids so cluster.paper_ids list refers to all of them
        aid_unique = f"{aid}.{i}"
        state.paper_pool[aid_unique] = PaperRecord(
            arxiv_id=aid_unique,
            title="t",
            abstract="a",
            authors=["A"],
            published=date(2024, 1, 1),
            categories=cats,
            pdf_url="",
            first_seen_turn=1,
            source="search",
        )
    state.cluster_snapshot = ClusterSnapshot(
        snapshot_id="s",
        generated_at=now,
        generated_after_turn=1,
        n_papers_at_time=3,
        clusters=[
            Cluster(
                slug="vln-ce",
                display_label="x",
                description="d",
                paper_ids=list(state.paper_pool.keys()),
                size=3,
                centroid_paper_id=list(state.paper_pool.keys())[0],
                representative_paper_ids=[],
                year_range=(2024, 2024),
                density="dense",
                first_seen_in_snapshot="s",
            )
        ],
    )
    session = ConfigureSession.from_field_map(fm)
    cfg = derive_config(fm, session, intent_text="test", state=state)
    assert cfg["topics"][0]["categories"][0] == "cs.RO"


# —————————————————————————————————————————————————————————————
# pick_anchor_paper_ids
# —————————————————————————————————————————————————————————————


def test_pick_anchors_filters_to_selected_slugs(fm):
    session = ConfigureSession.from_field_map(fm)
    out = pick_anchor_paper_ids(fm, session)
    assert "vln-ce" in out
    # The fixture has 1 anchor for vln-ce
    assert out["vln-ce"] == ["2401.00001"]


def test_pick_anchors_skips_dropped_slugs(fm):
    session = ConfigureSession.from_field_map(fm)
    session.drop("vln-ce")
    out = pick_anchor_paper_ids(fm, session)
    assert out == {}


def test_pick_anchors_caps_per_session_count(fm):
    """Only return min(available, anchor_count) per slug."""
    session = ConfigureSession.from_field_map(fm)
    all_slugs = [sa.slug for sa in fm.sub_areas]
    session.set_anchor_count("vln-ce", 0, all_slugs)
    out = pick_anchor_paper_ids(fm, session)
    assert out.get("vln-ce") == []
