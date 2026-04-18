"""Shared test fixtures for tests/explore/."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.explore.state import (
    BudgetState,
    ExplorationState,
    Intent,
    RunMetadata,
)


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
