"""T1 schema tests for skim_paper — real Gemini Flash calls.

Validates that the skim prompt elicits well-formed SkimResult JSON for a
known abstract. Cost: ~$0.002 per test.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from src.config import LLMConfig
from src.explore.skim import skim_paper
from src.explore.state import PaperRecord
from src.llm.gemini_client import GeminiClient


pytestmark = pytest.mark.llm


@pytest.fixture
def llm_client():
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


def _hm3d_paper() -> PaperRecord:
    return PaperRecord(
        arxiv_id="2402.00001",
        title="Zero-Shot Object Goal Navigation with CLIP Features on HM3D",
        abstract=(
            "We tackle zero-shot Object Goal Navigation (ObjectNav) by using "
            "CLIP-based open-vocabulary semantic features. Our approach maps "
            "the agent's egocentric observations to a CLIP feature space, "
            "matches against goal categories, and uses a simple frontier-based "
            "exploration policy. We evaluate on the HM3D-ObjectNav benchmark "
            "(matterport reconstructions) and on Habitat-ObjectNav, comparing "
            "to ObjectNav-RL, PEANUT, and CoW baselines. We achieve 32.5% "
            "Success Rate and 16.1% SPL on HM3D val. The Transformer encoder "
            "we use is a ViT-B/16 from CLIP."
        ),
        authors=["A. Author", "B. Author"],
        published=date(2024, 2, 1),
        categories=["cs.RO", "cs.CV"],
        pdf_url="",
        first_seen_turn=1,
        source="search",
    )


async def test_skim_extracts_known_benchmarks_and_methods(llm_client):
    paper = _hm3d_paper()
    result = await skim_paper(paper, llm_client)

    assert result is not None, "skim_paper returned None — Flash output unparseable"
    # Must surface at least one of the well-known benchmarks named in abstract
    bench_text = " ".join(result.benchmarks).lower()
    assert any(
        marker in bench_text for marker in ("hm3d", "habitat", "objectnav")
    ), f"Expected HM3D/Habitat/ObjectNav in benchmarks; got {result.benchmarks!r}"

    # Methods should mention CLIP (the abstract's central method)
    method_text = " ".join(result.methods).lower()
    assert "clip" in method_text or any(
        "clip" in k.lower() for k in result.keywords
    ), f"Expected CLIP in methods or keywords; got methods={result.methods!r}, kw={result.keywords!r}"

    # Lists are bounded — schema enforces caps but verify the actual outputs are sane
    assert 1 <= len(result.benchmarks) <= 10
    assert len(result.methods) <= 10
    assert len(result.keywords) <= 15


async def test_skim_handles_short_abstract(llm_client):
    """Edge: very short abstract — output should still be valid (possibly empty lists)."""
    paper = PaperRecord(
        arxiv_id="2401.99999",
        title="A Short Note",
        abstract="We propose a small extension to method X.",
        authors=["X. Y."],
        published=date(2024, 1, 1),
        categories=["cs.LG"],
        pdf_url="",
        first_seen_turn=1,
        source="search",
    )
    result = await skim_paper(paper, llm_client)
    assert result is not None
    # No specific benchmarks/methods/keywords required — just well-formed
