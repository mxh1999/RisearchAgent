"""End-to-end runner helpers wiring up Explore / Synthesize / Configure.

These are the pieces a CLI command (run.py) calls. Kept out of run.py so
they can be exercised in tests without subprocess overhead.

Path conventions (per docs/onboard-redesign/05 + 10):
    data/explore/state/<run_id>.json          — exploration state
    data/explore/logs/<run_id>.log            — orchestrator event log
    data/explore/chroma/                      — ChromaDB store (per-run collection)
    data/explore/pdfs/                        — PDF cache for read_paper
    data/explore/field_maps/<run_id>.json     — synthesized FieldMap
    data/explore/field_maps/<run_id>.md       — rendered Markdown
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import LLMConfig
from src.explore.checkpoint import checkpoint_path_for, load_checkpoint
from src.explore.citations import CitationProvider, make_provider_from_env
from src.explore.cluster import Clusterer
from src.explore.crawl import ExplorerSearcher
from src.explore.embeddings import EmbeddingStore
from src.explore.executor import ActionExecutor
from src.explore.orchestrator import Explorer
from src.explore.planner import LLMPlanner
from src.explore.read import ExploreReader
from src.explore.spec import ALL_RULES, SpecEvaluator
from src.explore.state import (
    BudgetState,
    ExplorationState,
    Intent,
    RunMetadata,
)
from src.llm.gemini_client import GeminiClient
from src.synthesize import (
    FieldMap,
    SynthesisError,
    render_field_map,
    synthesize,
)


logger = logging.getLogger(__name__)


# —————————————————————————————————————————————————————————————
# Path helpers
# —————————————————————————————————————————————————————————————


def explore_data_root() -> Path:
    return Path("data/explore")


def state_path(run_id: str) -> Path:
    return explore_data_root() / "state" / f"{run_id}.json"


def log_path(run_id: str) -> Path:
    return explore_data_root() / "logs" / f"{run_id}.log"


def field_map_json_path(run_id: str) -> Path:
    return explore_data_root() / "field_maps" / f"{run_id}.json"


def field_map_md_path(run_id: str) -> Path:
    return explore_data_root() / "field_maps" / f"{run_id}.md"


def make_run_id() -> str:
    """YYYYMMDD-HHMMSS-<6 hex> — sortable + unique."""
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


# —————————————————————————————————————————————————————————————
# Explore stage
# —————————————————————————————————————————————————————————————


async def run_explore(
    *,
    intent_text: str,
    seed_arxiv_ids: Optional[list[str]] = None,
    llm_config: LLMConfig,
    run_id: Optional[str] = None,
    time_budget_seconds: int = 900,
    action_budget: int = 60,
    read_paper_budget: int = 3,
    enable_clusterer: bool = True,
    enable_reader: bool = False,  # off by default — Pro deep reads are expensive
) -> ExplorationState:
    """Run a full Explorer end-to-end with all real dependencies wired in.

    Returns the final ExplorationState (also persisted to checkpoint).
    """
    run_id = run_id or make_run_id()
    logger.info("[runner] explore run_id=%s", run_id)

    llm = GeminiClient(llm_config)

    state = ExplorationState(
        metadata=RunMetadata(
            run_id=run_id,
            started_at=datetime.now(),
            last_updated_at=datetime.now(),
            code_version="explore-v1",
        ),
        intent=Intent(
            natural_language=intent_text,
            seed_arxiv_ids=list(seed_arxiv_ids or []),
        ),
        budget=BudgetState(
            time_budget_seconds=time_budget_seconds,
            action_budget=action_budget,
            read_paper_budget=read_paper_budget,
        ),
    )

    searcher = ExplorerSearcher(delay_seconds=3.0)
    embeddings = EmbeddingStore(
        run_id=run_id,
        llm=llm,
        chroma_path=explore_data_root() / "chroma",
    )
    clusterer = (
        Clusterer(embeddings=embeddings, llm=llm) if enable_clusterer else None
    )
    citations: CitationProvider = make_provider_from_env(_env_view())
    reader = (
        ExploreReader(
            llm=llm, config=llm_config, pdf_dir=explore_data_root() / "pdfs"
        )
        if enable_reader
        else None
    )

    executor = ActionExecutor(
        searcher=searcher,
        embeddings=embeddings,
        clusterer=clusterer,
        llm=llm,
        citations=citations,
        reader=reader,
    )
    planner = LLMPlanner(llm)
    evaluator = SpecEvaluator(ALL_RULES)

    explorer = Explorer(
        state=state,
        planner=planner,
        executor=executor,
        evaluator=evaluator,
        checkpoint_dir=explore_data_root() / "state",
    )
    final = await explorer.run()

    # Mirror the citation provider's degraded flag onto state metadata so
    # Synthesize can include a notes entry about it.
    if not citations.is_available() and not isinstance(citations.is_available, type(None)):  # type: ignore[arg-type]
        final.metadata.citation_provider_degraded = True

    return final


def _env_view() -> dict[str, str]:
    """Snapshot of the env vars Citation factory cares about."""
    import os
    keys = ("EXPLORE_CITATION_PROVIDER", "SEMANTIC_SCHOLAR_API_KEY")
    return {k: os.environ.get(k, "") for k in keys}


# —————————————————————————————————————————————————————————————
# Synthesize stage
# —————————————————————————————————————————————————————————————


async def run_synthesize(
    *,
    state: ExplorationState,
    llm_config: LLMConfig,
) -> tuple[FieldMap, Path, Path]:
    """Run synthesize on a (frozen) ExplorationState.

    Returns (field_map, json_path, md_path).
    """
    llm = GeminiClient(llm_config)
    fm = await synthesize(state, llm)

    json_p = field_map_json_path(state.metadata.run_id)
    md_p = field_map_md_path(state.metadata.run_id)
    json_p.parent.mkdir(parents=True, exist_ok=True)
    json_p.write_text(fm.model_dump_json(indent=2), encoding="utf-8")
    md_p.write_text(render_field_map(fm), encoding="utf-8")

    return fm, json_p, md_p


# —————————————————————————————————————————————————————————————
# Loaders for already-persisted artifacts
# —————————————————————————————————————————————————————————————


def load_state_for(run_id: str) -> ExplorationState:
    return load_checkpoint(state_path(run_id))


def load_field_map_for(run_id: str) -> FieldMap:
    raw = field_map_json_path(run_id).read_text(encoding="utf-8")
    return FieldMap.model_validate(json.loads(raw))


__all__ = [
    "run_explore",
    "run_synthesize",
    "load_state_for",
    "load_field_map_for",
    "make_run_id",
    "state_path",
    "log_path",
    "field_map_json_path",
    "field_map_md_path",
    "explore_data_root",
]
