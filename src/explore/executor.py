"""Action executor: handles each Action type's side effects on state.

Dependencies (searcher, embeddings, clusterer, llm, citation_provider)
are injected at construction time. When omitted, handlers fall back to
stub / null behavior — this keeps the M1 test path and any future dry-run
mode working without touching the network.

Implemented per milestone:
  - M2: search (real ArXiv + embeddings + counter side effects)
  - M3: cluster_refresh (real Clusterer)
  - M4: skim_abstract (Flash extract; updates paper.skim + benchmark_counter)
  - M4: coverage_audit (deterministic structural check; no LLM)
  - M6: fetch_citations + fetch_related (Semantic Scholar)

Other actions are stubs until their milestone (M7 read_paper).
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
    from src.explore.citations import CitationProvider, RelatedPaper
    from src.explore.cluster import Clusterer
    from src.explore.crawl import ExplorerSearcher
    from src.explore.embeddings import EmbeddingStore
    from src.explore.read import ExploreReader
    from src.explore.state import ExplorationState
    from src.llm.gemini_client import GeminiClient


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
        llm: Optional["GeminiClient"] = None,
        citations: Optional["CitationProvider"] = None,
        reader: Optional["ExploreReader"] = None,
    ):
        self.searcher = searcher
        self.embeddings = embeddings
        self.clusterer = clusterer
        self.llm = llm
        self.citations = citations
        self.reader = reader

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

        # 4. Insert into paper_pool + update author / venue counters.
        # Use state.turn+1 because this action's turn increments *after* executor returns.
        action_turn = state.turn + 1
        for r in new_papers:
            aid = r["arxiv_id"]
            state.paper_pool[aid] = PaperRecord(
                arxiv_id=aid,
                title=r["title"],
                abstract=r["abstract"],
                authors=r["authors"],
                published=r["published"],
                categories=r["categories"],
                pdf_url=r["pdf_url"],
                first_seen_turn=action_turn,
                source="search",
                source_query_id=query_id,
                embedding_id=embed_map.get(aid),
                is_noise=False,
            )
            # author_counter: count first 3 authors per paper to deweight long lists
            for author in r["authors"][:3]:
                state.counters.author_counter.setdefault(author, []).append(aid)
            # venue_counter: bucket by published year (cheap proxy for venue)
            year_bucket = str(r["published"].year)
            state.counters.venue_counter.setdefault(year_bucket, []).append(aid)

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
        if self.citations is None or not self.citations.is_available():
            return ActionResult(
                success=True,
                summary=(
                    f"[stub] fetch_citations: {action.arxiv_id} "
                    f"(citation provider unavailable)"
                ),
                details={"stub": True},
            )

        related: list = []
        if action.direction in ("references", "both"):
            refs = await self.citations.get_references(
                action.arxiv_id, limit=action.max_results
            )
            related.extend(refs)
        if action.direction in ("cited_by", "both"):
            cits = await self.citations.get_citations(
                action.arxiv_id, limit=action.max_results
            )
            related.extend(cits)

        n_added = await self._ingest_related(
            related, source="citation_expansion", source_paper_id=action.arxiv_id, state=state
        )
        return ActionResult(
            success=True,
            summary=(
                f"fetch_citations({action.direction}): {action.arxiv_id} → "
                f"+{n_added} papers ({len(related)} returned)"
            ),
            details={
                "n_returned": len(related),
                "n_new": n_added,
                "direction": action.direction,
                "source_paper_id": action.arxiv_id,
            },
        )

    async def _handle_fetch_related(self, action: FetchRelatedAction, state):
        if self.citations is None or not self.citations.is_available():
            return ActionResult(
                success=True,
                summary=(
                    f"[stub] fetch_related: {action.arxiv_id} "
                    f"(citation provider unavailable)"
                ),
                details={"stub": True},
            )

        related = await self.citations.get_related(
            action.arxiv_id, limit=action.max_results
        )
        n_added = await self._ingest_related(
            related, source="related", source_paper_id=action.arxiv_id, state=state
        )
        return ActionResult(
            success=True,
            summary=f"fetch_related: {action.arxiv_id} → +{n_added} papers ({len(related)} returned)",
            details={
                "n_returned": len(related),
                "n_new": n_added,
                "source_paper_id": action.arxiv_id,
            },
        )

    # —————————————————————————————————————————————————————
    # Shared ingest path for citation/related results
    # —————————————————————————————————————————————————————

    async def _ingest_related(
        self,
        related: list["RelatedPaper"],
        *,
        source: str,
        source_paper_id: str,
        state: "ExplorationState",
    ) -> int:
        """Add new papers from a citation/related lookup to paper_pool.

        Skips papers without arxiv_id or without an abstract (we can't embed
        them, and they'd pollute the pool).

        Returns the count of papers added (post-dedup).
        """
        from datetime import date as _date
        from datetime import datetime as _datetime
        from src.explore.state import QueryRecord

        action_turn = state.turn + 1

        # Filter usable entries: must have arxiv_id, title, abstract.
        candidates = [
            rp
            for rp in related
            if rp.arxiv_id and rp.title and rp.abstract
            and rp.arxiv_id not in state.paper_pool
        ]
        if not candidates:
            return 0

        # Embed (if configured) — batched
        embed_map: dict[str, str] = {}
        if self.embeddings is not None:
            embed_payload = [
                {
                    "arxiv_id": rp.arxiv_id,
                    "title": rp.title,
                    "abstract": rp.abstract,
                }
                for rp in candidates
            ]
            embed_ids = await self.embeddings.add_papers(embed_payload)
            embed_map = dict(zip((rp.arxiv_id for rp in candidates), embed_ids))

        # Build a QueryRecord so saturation/turn tracking sees this batch too.
        query_id = f"q-{source[:3]}-{uuid.uuid4().hex[:6]}"
        # Map our "source" (paper.source) to QueryRecord.source
        qr_source = "citation_seeded" if source == "citation_expansion" else "author_seeded"
        # NB: "related" maps to "author_seeded" only as a coarse bucket; SS related
        # isn't truly author-seeded but the QueryRecord enum doesn't have a 'related'
        # variant. This is a small modeling debt — not worth a schema bump in M6.

        for rp in candidates:
            published = _date(rp.year, 1, 1) if rp.year else _date(2024, 1, 1)
            state.paper_pool[rp.arxiv_id] = PaperRecord(
                arxiv_id=rp.arxiv_id,
                title=rp.title,
                abstract=rp.abstract or "",
                authors=rp.authors or [],
                published=published,
                categories=[],  # SS doesn't return ArXiv categories
                pdf_url=f"https://arxiv.org/pdf/{rp.arxiv_id}",
                first_seen_turn=action_turn,
                source=source,  # "citation_expansion" or "related"
                source_query_id=query_id,
                source_paper_id=source_paper_id,
                embedding_id=embed_map.get(rp.arxiv_id),
                citation_count=rp.citation_count,
                citation_data_fetched_at=_datetime.now() if rp.citation_count is not None else None,
                is_noise=False,
            )
            for author in (rp.authors or [])[:3]:
                state.counters.author_counter.setdefault(author, []).append(rp.arxiv_id)
            state.counters.venue_counter.setdefault(str(published.year), []).append(rp.arxiv_id)

        state.query_log.append(
            QueryRecord(
                query_id=query_id,
                turn=action_turn,
                query_text=f"<{source}:{source_paper_id}>",
                categories=[],
                source=qr_source,
                targeted_cluster_slug=None,
                query_embedding_id=None,
                n_results_raw=len(related),
                n_new_to_pool=len(candidates),
                executed_at=_datetime.now(),
            )
        )
        return len(candidates)

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
        from src.explore.skim import skim_paper

        if self.llm is None:
            return ActionResult(
                success=True,
                summary=f"[stub] skim_abstract: {action.arxiv_id} (no llm wired)",
                details={"stub": True},
            )

        paper = state.paper_pool.get(action.arxiv_id)
        if paper is None:
            return ActionResult(
                success=False,
                summary=f"skim_abstract: {action.arxiv_id} not in paper_pool",
                error="paper_not_in_pool",
            )

        skim = await skim_paper(paper, self.llm)
        if skim is None:
            return ActionResult(
                success=False,
                summary=f"skim_abstract: {action.arxiv_id} parse failed",
                error="skim_parse_failed",
            )

        # Update paper.skim
        paper.skim = skim

        # Update benchmark_counter (per-benchmark inverted index)
        for bench in skim.benchmarks:
            # Cheap canonicalization: trim + casefold for the index key
            key = bench.strip()
            if not key:
                continue
            ids = state.counters.benchmark_counter.setdefault(key, [])
            if action.arxiv_id not in ids:
                ids.append(action.arxiv_id)

        return ActionResult(
            success=True,
            summary=(
                f"skim_abstract: {action.arxiv_id} -> "
                f"benchmarks={len(skim.benchmarks)}, methods={len(skim.methods)}, "
                f"keywords={len(skim.keywords)}"
            ),
            details={
                "n_benchmarks": len(skim.benchmarks),
                "n_methods": len(skim.methods),
                "n_keywords": len(skim.keywords),
            },
        )

    async def _handle_read_paper(self, action: ReadPaperAction, state):
        if self.reader is None:
            # Stub path: still bumps budget so RULE_READ_PAPER_BUDGET tests work
            # without a real reader configured.
            state.budget.read_papers_used += 1
            return ActionResult(
                success=True,
                summary=(
                    f"[stub] read_paper: {action.arxiv_id} "
                    f"(no reader wired; read_papers_used now "
                    f"{state.budget.read_papers_used})"
                ),
                details={"stub": True},
            )

        paper = state.paper_pool.get(action.arxiv_id)
        if paper is None:
            return ActionResult(
                success=False,
                summary=f"read_paper: {action.arxiv_id} not in paper_pool",
                error="paper_not_in_pool",
            )

        # Budget consumed regardless of read success — prevents retry storms
        # on a paper whose PDF is broken or whose reader trips repeatedly.
        state.budget.read_papers_used += 1

        explore_reading = await self.reader.read(paper)
        if explore_reading is None:
            return ActionResult(
                success=False,
                summary=f"read_paper: {action.arxiv_id} read failed",
                error="read_failed",
            )

        # Persist on the paper record
        paper.explore_reading = explore_reading
        if "deep_read_candidate" in paper.flags:
            paper.flags.remove("deep_read_candidate")

        # Update benchmark_counter from the extracted experiments — same
        # canonicalization as skim_abstract: trim the name, append arxiv_id
        # to the inverted index, dedupe.
        n_benchmark_entries = 0
        for exp in explore_reading.benchmarks:
            key = (exp.benchmark or "").strip()
            if not key:
                continue
            ids = state.counters.benchmark_counter.setdefault(key, [])
            if action.arxiv_id not in ids:
                ids.append(action.arxiv_id)
            n_benchmark_entries += 1

        return ActionResult(
            success=True,
            summary=(
                f"read_paper: {action.arxiv_id} → "
                f"{n_benchmark_entries} benchmark entries, "
                f"budget {state.budget.read_papers_used}/{state.budget.read_paper_budget}"
            ),
            details={
                "n_benchmark_entries": n_benchmark_entries,
                "method_summary": explore_reading.proposed_method[:200],
            },
        )

    async def _handle_coverage_audit(self, action: CoverageAuditAction, state):
        from src.explore.coverage import run_coverage_audit

        report = run_coverage_audit(state)
        state.coverage_report = report

        gaps = [
            q.gap_description
            for q in report.questions
            if not q.answer_available and q.gap_description
        ]
        return ActionResult(
            success=True,
            summary=(
                f"coverage_audit: passes={report.passes}, "
                f"unanswered={report.unanswered_count}/{len(report.questions)}"
            ),
            details={
                "passes": report.passes,
                "unanswered_count": report.unanswered_count,
                "gaps": gaps,
            },
        )

    async def _handle_stop(self, action: StopAction, state):
        return ActionResult(
            success=True,
            summary=f"stop requested: claimed_reason={action.claimed_reason}",
        )
