"""Shared test fixtures for tests/explore/."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from src.config import LLMConfig
from src.explore.state import (
    BudgetState,
    ExplorationState,
    Intent,
    RunMetadata,
)
from src.llm.gemini_client import GeminiClient


def make_state(
    *,
    run_id: str = "test-run",
    read_papers_used: int = 0,
    read_paper_budget: int = 3,
    actions_used: int = 0,
    action_budget: int = 60,
    time_budget_seconds: int = 900,
    elapsed_seconds: float = 0.0,
) -> ExplorationState:
    """Minimal ExplorationState for unit tests."""
    now = datetime.now()
    return ExplorationState(
        metadata=RunMetadata(
            run_id=run_id,
            started_at=now,
            last_updated_at=now,
            code_version="test",
            status="running",
        ),
        intent=Intent(natural_language="test intent"),
        budget=BudgetState(
            read_papers_used=read_papers_used,
            read_paper_budget=read_paper_budget,
            actions_used=actions_used,
            action_budget=action_budget,
            time_budget_seconds=time_budget_seconds,
            elapsed_seconds=elapsed_seconds,
        ),
    )


@pytest.fixture
def state():
    """A baseline state with no history, small budget."""
    return make_state()


def make_llm_client_from_env() -> GeminiClient:
    """Build a GeminiClient from .env (GEMINI_API_KEY + optional GEMINI_BASE_URL).

    Skips the surrounding test if the key is missing — function-scoped because
    GeminiClient.__init__ creates an asyncio.Semaphore bound to the current
    event loop, and pytest-asyncio uses a fresh loop per test.
    """
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")

    return GeminiClient(
        LLMConfig(
            # gemini-3-flash (3rd-gen) replaces gemini-2.5-flash; some providers
            # don't carry 2.5-flash any more. Override at the test level if you
            # need a specific model.
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


@pytest.fixture
def llm_client():
    """Test fixture for a real GeminiClient. See make_llm_client_from_env."""
    return make_llm_client_from_env()
