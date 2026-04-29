"""Action executor: handles each Action type's side effects on state.

Dependencies (searcher, embeddings) are injected at construction time. When
omitted, handlers fall back to stub behavior — this keeps the M1 test path
and any future dry-run mode working without touching the network.

M2 implements search and its side effects (embedding + paper_pool update).
Other actions remain stubs until their own milestone (M3 clustering, M4
coverage audit, M6 citations, M7 read_paper).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

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
from src.explore.state import LLMCallRecord, PaperRecord, QueryRecord

if TYPE_CHECKING:
    from src.explore.actions import Action
    from src.explore.cluster import Clusterer
    from src.explore.crawl import ExplorerSearcher
    from src.explore.embeddings import EmbeddingStore
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
    """Dispatches actions to their handlers.

    Deps are optional so that tests can use the executor without external
    services (they get stub behavior). In production, provide all deps
    that the actions used in this run will need.
    """

    def __init__(
        self,
        searcher: Optional["ExplorerSearcher"] = None,
        embeddings: Optional["EmbeddingStore"] = None,
        clusterer: Optional["Clusterer"] = None,
    ):
        self.searcher = searcher
        self.embeddings = embeddings
        self.clusterer = clusterer

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
    # Search (M2 — real implementation)
    # —————————————————————————————————————————————————————

    async def _handle_search(self, action: SearchAction, state):
        if self.searcher is None:
            return ActionResult(
                success=True,
                summary=f"[stub] search: {action.query!r} (searcher not configured)",
                details={"query_id": "stub", "n_new": 0, "stub": True},
            )

        # 1. Query ArXiv
        raw_results = await self.searcher.search(
            query=action.query,
            categories=action.categories,
            max_results=action.max_results,
            date_range=action.date_range,
            sort_by=action.sort_by,
        )

        # 2. Deduplicate against the pool
        new_papers = [r for r in raw_results if r["arxiv_id"] not in state.paper_pool]

        # 3. Embed + store (if EmbeddingStore is configured)
        query_id = f"q-{uuid.uuid4().hex[:8]}"
        embed_map: dict[str, str] = {}
        query_embedding_id: Optional[str] = None
        if self.embeddings is not None:
            if new_papers:
                embed_ids = await self.embeddings.add_papers(new_papers)
                embed_map = dict(zip((p["arxiv_id"] for p in new_papers), embed_ids))
            # Also store the query itself (for diversity checks later)
            query_embedding_id = await self.embeddings.add_query(query_id, action.query)

        # 4. Insert into paper_pool.
        # Use state.turn+1 because this action's turn increments *after* executor returns.
        action_turn = state.turn + 1
        for r in new_papers:
            state.paper_pool[r["arxiv_id"]] = PaperRecord(
                arxiv_id=r["arxiv_id"],
                title=r["title"],
                abstract=r["abstract"],
                authors=r["authors"],
                published=r["published"],
                categories=r["categories"],
                pdf_url=r["pdf_url"],
                first_seen_turn=action_turn,
                source="search",
                source_query_id=query_id,
                embedding_id=embed_map.get(r["arxiv_id"]),
                is_noise=False,
            )

        # 5. Record QueryRecord
        state.query_log.append(
            QueryRecord(
                query_id=query_id,
                turn=action_turn,
                query_text=action.query,
                categories=action.categories,
                source=action.source_tag,
                targeted_cluster_slug=action.targeted_cluster_slug,
                query_embedding_id=query_embedding_id,
                n_results_raw=len(raw_results),
                n_new_to_pool=len(new_papers),
                executed_at=datetime.now(),
            )
        )

        n_dupes = len(raw_results) - len(new_papers)
        return ActionResult(
            success=True,
            summary=f"search: +{len(new_papers)} papers ({n_dupes} dupes)",
            details={
                "query_id": query_id,
                "n_fetched": len(raw_results),
                "n_new": len(new_papers),
                "n_deduped": n_dupes,
            },
        )

    # —————————————————————————————————————————————————————
    # Remaining handlers — stubs until their milestones land
    # —————————————————————————————————————————————————————

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
        if self.clusterer is None:
            return ActionResult(
                success=True,
                summary="[stub] cluster_refresh: no Clusterer configured",
                details={"stub": True},
            )

        # Lazy import to avoid coupling Executor to clusterer at module load
        from src.explore.cluster import InsufficientPoolError

        try:
            result = await self.clusterer.refresh(state)
        except InsufficientPoolError as e:
            return ActionResult(
                success=True,
                summary=f"cluster_refresh: insufficient_papers ({e})",
                details={"status": "insufficient_papers", "reason": str(e)},
            )

        summary_bits = [
            f"clusters={result.n_clusters}",
            f"noise={result.n_noise}",
        ]
        if result.new_slugs:
            summary_bits.append(f"new={','.join(result.new_slugs)}")
        if result.disappeared_slugs:
            summary_bits.append(f"gone={','.join(result.disappeared_slugs)}")
        if result.used_fallback_labels:
            summary_bits.append("fallback_labels=True")

        return ActionResult(
            success=True,
            summary=f"cluster_refresh: {', '.join(summary_bits)}",
            details={
                "snapshot_id": result.snapshot_id,
                "n_clusters": result.n_clusters,
                "new_slugs": result.new_slugs,
                "disappeared_slugs": result.disappeared_slugs,
                "structural_change_rate": result.structural_change_rate,
                "n_noise": result.n_noise,
                "used_fallback_labels": result.used_fallback_labels,
            },
        )

    async def _handle_skim_abstract(self, action: SkimAbstractAction, state):
        return ActionResult(
            success=True,
            summary=f"[stub] skim_abstract: {action.arxiv_id} (M4)",
        )

    async def _handle_read_paper(self, action: ReadPaperAction, state):
        # Bumps the budget so the budget rule can be exercised with a stub.
        state.budget.read_papers_used += 1
        return ActionResult(
            success=True,
            summary=f"[stub] read_paper: {action.arxiv_id} "
            f"(read_papers_used now {state.budget.read_papers_used}) (M7)",
        )

    async def _handle_coverage_audit(self, action: CoverageAuditAction, state):
        return ActionResult(
            success=True,
            summary="[stub] coverage_audit: no-op (M4)",
        )

    async def _handle_stop(self, action: StopAction, state):
        return ActionResult(
            success=True,
            summary=f"stop requested: claimed_reason={action.claimed_reason}",
        )
