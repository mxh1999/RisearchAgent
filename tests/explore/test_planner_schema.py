"""T1 schema tests for LLMPlanner — real Gemini calls.

Per docs/onboard-redesign/08 three-tier testing:
  T1 (this file): deterministic *structural* assertions on real LLM output.
      - Valid JSON matching Action discriminated union
      - No hallucinated arxiv_ids (references must exist in paper_pool)
      - No hallucinated cluster_slugs

Uses Flash tier by default (cheaper) since these tests don't judge
reasoning quality — they only check structure. A schema bug shows up on
Flash just as clearly as on Pro.

Run with: pytest -m llm
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Iterable

import pytest

from src.config import LLMConfig
from src.explore.actions import (
    FetchCitationsAction,
    FetchRelatedAction,
    ReadPaperAction,
    SearchAction,
    SkimAbstractAction,
)
from src.explore.planner import LLMPlanner, LLMPlannerError
from src.explore.state import PaperRecord
from src.llm.gemini_client import GeminiClient
from tests.explore.conftest import make_state


pytestmark = pytest.mark.llm


# —————————————————————————————————————————————————————————————
# Fixtures
# —————————————————————————————————————————————————————————————


@pytest.fixture
def llm_client():
    """Build a GeminiClient from the user's .env.

    Function-scoped because GeminiClient.__init__ creates an asyncio.Semaphore
    bound to the current event loop, and pytest-asyncio uses a fresh loop
    per test by default.

    Skipped if GEMINI_API_KEY is missing.
    """
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")

    return GeminiClient(
        LLMConfig(
            filter_model="gemini-2.5-flash",
            reader_model="gemini-2.5-pro",
            embedding_model="gemini-embedding-001",
            api_key=api_key,
            max_concurrent=3,
            temperature=0.3,
        )
    )


@pytest.fixture
def flash_planner(llm_client):
    """Planner backed by Flash (cheaper) — sufficient for schema-level tests."""
    return LLMPlanner(llm_client, model=llm_client.config.filter_model)


def _extract_arxiv_ids(action) -> list[str]:
    """Return any arxiv_id referenced in the action's args."""
    t = action.action_type
    if t in ("fetch_citations", "fetch_related", "skim_abstract", "read_paper"):
        return [action.arxiv_id]
    return []


def _extract_cluster_slugs(action) -> list[str]:
    if action.action_type == "search" and action.targeted_cluster_slug:
        return [action.targeted_cluster_slug]
    return []


def _paper(aid: str, title: str) -> PaperRecord:
    return PaperRecord(
        arxiv_id=aid,
        title=title,
        abstract="(abstract stub for test)",
        authors=["Test Author"],
        published=date(2024, 1, 1),
        categories=["cs.AI"],
        pdf_url=f"https://arxiv.org/pdf/{aid}",
        first_seen_turn=1,
        source="search",
    )


# —————————————————————————————————————————————————————————————
# T1 tests
# —————————————————————————————————————————————————————————————


async def test_propose_returns_valid_action_from_empty_state(flash_planner):
    """Schema is enforced by LLMPlanner itself via pydantic. Must not raise."""
    state = make_state()
    state.intent.natural_language = (
        "I'm interested in embodied navigation, especially zero-shot ObjNav."
    )
    action = await flash_planner.propose(state)
    # If we got here, JSON was valid and mapped to a concrete Action subclass.
    assert action.action_type in {
        "search",
        "search_by_author",
        "fetch_citations",
        "fetch_related",
        "cluster_refresh",
        "skim_abstract",
        "read_paper",
        "coverage_audit",
        "stop",
    }
    assert len(action.reasoning) >= 1


async def test_no_hallucinated_arxiv_id(flash_planner):
    """Any arxiv_id referenced by the proposed action must be in the pool."""
    state = make_state()
    state.intent.natural_language = "Vision-language navigation."
    # Seed a small pool — planner may choose to fetch_citations from one of these,
    # but must not invent IDs.
    for aid, title in [
        ("2401.12345", "VLN with Transformers"),
        ("2403.67890", "Embodied LLM Planner"),
        ("2311.11111", "HM3D ObjNav Benchmark"),
    ]:
        state.paper_pool[aid] = _paper(aid, title)

    action = await flash_planner.propose(state)

    referenced_ids = _extract_arxiv_ids(action)
    for aid in referenced_ids:
        assert aid in state.paper_pool, (
            f"Planner hallucinated arxiv_id {aid!r}. Pool has: "
            f"{list(state.paper_pool.keys())}"
        )


async def test_no_hallucinated_cluster_slug(flash_planner):
    """If the planner sets targeted_cluster_slug, it must be a real slug."""
    state = make_state()
    state.intent.natural_language = "Navigation"
    # No cluster_snapshot → any cluster_slug would be a hallucination
    action = await flash_planner.propose(state)

    slugs = _extract_cluster_slugs(action)
    # Without a snapshot, planner should NOT set targeted_cluster_slug.
    for slug in slugs:
        pytest.fail(
            f"Planner set targeted_cluster_slug={slug!r} but state has no "
            f"cluster_snapshot — that's a hallucination."
        )


async def test_reasoning_non_empty(flash_planner):
    state = make_state()
    state.intent.natural_language = "Multimodal retrieval."
    action = await flash_planner.propose(state)
    assert action.reasoning.strip(), "Reasoning should not be empty/whitespace"


