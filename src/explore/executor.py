"""Action executor: handles each Action type's side effects on state.

M1 ships stub handlers for every action type — they return fake results
and don't touch the network / filesystem / ChromaDB. Real handlers land
in M2+ per docs/onboard-redesign/06-action-system.md "ActionDetails" section.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.explore.actions import (
    ClusterRefreshAction,
    CoverageAuditAction,
    FetchCitationsAction,
    FetchRelatedAction,
    ReadPaperAction,
    SearchAction,
    SearchByAuthorAction,
    SkimAbstractAction,
    StopAction,
)
from src.explore.state import LLMCallRecord

if TYPE_CHECKING:
    from src.explore.actions import Action
    from src.explore.state import ExplorationState


logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """What an executor handler returns. Orchestrator uses this to build ActionRecord."""
    success: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    error: str | None = None


class ActionExecutor:
    """Dispatches actions to their handlers."""

    async def execute(
        self, action: "Action", state: "ExplorationState"
    ) -> ActionResult:
        start = datetime.now()
        handler_name = f"_handle_{action.action_type}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            return ActionResult(
                success=False,
                summary=f"No handler for {action.action_type}",
                error=f"no_handler:{action.action_type}",
            )
        try:
            result = await handler(action, state)
        except Exception as e:
            logger.exception("Handler %s raised", handler_name)
            return ActionResult(
                success=False,
                summary=f"{action.action_type} failed: {e}",
                error=str(e),
            )
        result.duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        return result

    # —————————————————————————————————————————————————————
    # M1 stubs — return fake results, don't touch the outside world
    # —————————————————————————————————————————————————————

    async def _handle_search(self, action: SearchAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] search: {action.query!r} (0 fake results)",
            details={"query_id": "stub", "n_new": 0},
        )

    async def _handle_search_by_author(self, action: SearchByAuthorAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] search_by_author: {action.author_name!r}",
        )

    async def _handle_fetch_citations(self, action: FetchCitationsAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] fetch_citations: {action.arxiv_id} ({action.direction})",
        )

    async def _handle_fetch_related(self, action: FetchRelatedAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] fetch_related: {action.arxiv_id}",
        )

    async def _handle_cluster_refresh(self, action: ClusterRefreshAction, state):
        return ActionResult(
            success=True,
            summary="[stub] cluster_refresh: no-op",
        )

    async def _handle_skim_abstract(self, action: SkimAbstractAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] skim_abstract: {action.arxiv_id}",
        )

    async def _handle_read_paper(self, action: ReadPaperAction, state):
        state.budget.read_papers_used += 1
        return ActionResult(
            success=True,
            summary=f"[stub] read_paper: {action.arxiv_id} "
            f"(read_papers_used now {state.budget.read_papers_used})",
        )

    async def _handle_coverage_audit(self, action: CoverageAuditAction, state):
        return ActionResult(
            success=True,
            summary="[stub] coverage_audit: no-op",
        )

    async def _handle_stop(self, action: StopAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] stop requested: claimed_reason={action.claimed_reason}",
        )
