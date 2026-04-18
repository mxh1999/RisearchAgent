"""Embedding storage for Explorer — thin wrapper over ChromaDB + GeminiClient.embed.

Per docs/onboard-redesign/05-state-schema.md OP-4, v1 uses one ChromaDB
collection per Explorer run ("explore_{run_id}"). No cross-run reuse —
simple, disposable. Cleanup happens on Explorer completion.

Used by:
  - Executor: store new papers after search/fetch
  - Spec rules (M2 step 2): query-diversity via cosine similarity to recent queries
  - Clusterer (M3): fetch all embeddings for HDBSCAN
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import chromadb

from src.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


class EmbeddingStore:
    """Per-run ChromaDB collection for paper & query embeddings.

    Uses cosine distance (hnsw:space=cosine). Distance is (1 - cosine_similarity)
    so range is [0, 2]. Callers convert via `similarity = 1 - distance`.
    """

    def __init__(
        self,
        run_id: str,
        llm: GeminiClient,
        chroma_path: Path = Path("data/explore/chroma"),
    ):
        self.run_id = run_id
        self.llm = llm
        self._client = chromadb.PersistentClient(path=str(chroma_path))

        # Papers collection (persistent for the run)
        self._papers = self._client.get_or_create_collection(
            name=f"explore_{run_id}_papers",
            metadata={"hnsw:space": "cosine"},
        )

        # Queries collection (for query_diversity rule; also per-run)
        self._queries = self._client.get_or_create_collection(
            name=f"explore_{run_id}_queries",
            metadata={"hnsw:space": "cosine"},
        )

    # —————————————————————————————————————————————————————
    # Paper embeddings
    # —————————————————————————————————————————————————————

    async def add_papers(self, papers: list[dict]) -> list[str]:
        """Batch-embed and upsert papers.

        Each paper dict must have: arxiv_id, title, abstract.
        Returns embedding_ids (same as arxiv_ids in this simple scheme).
        """
        if not papers:
            return []

        texts = [f"{p['title']}\n\n{p['abstract']}" for p in papers]
        ids = [p["arxiv_id"] for p in papers]

        embeddings = await self.llm.embed(texts)
        self._papers.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {"arxiv_id": p["arxiv_id"], "title": p["title"]} for p in papers
            ],
        )
        logger.debug("[embeddings] added %d papers", len(papers))
        return ids

    def get_paper_embeddings(
        self, arxiv_ids: list[str]
    ) -> tuple[list[str], list[list[float]]]:
        """Fetch embeddings for the given ids. Used by Clusterer (M3)."""
        if not arxiv_ids:
            return [], []
        result = self._papers.get(ids=arxiv_ids, include=["embeddings"])
        return result["ids"], list(result["embeddings"])

    # —————————————————————————————————————————————————————
    # Query embeddings (for diversity rule)
    # —————————————————————————————————————————————————————

    async def add_query(self, query_id: str, query_text: str) -> str:
        """Embed a query and store it. Returns embedding_id (== query_id)."""
        embeddings = await self.llm.embed([query_text])
        self._queries.upsert(
            ids=[query_id],
            embeddings=embeddings,
            documents=[query_text],
        )
        return query_id

    async def max_similarity_to_recent_queries(
        self, query_text: str, recent_query_ids: list[str]
    ) -> float:
        """Compute max cosine similarity of `query_text` vs the given recent queries.

        Used by RULE_QUERY_DIVERSITY (M2 step 2). Returns 0.0 if no recent queries.
        """
        if not recent_query_ids:
            return 0.0

        # Embed the new query
        new_emb = (await self.llm.embed([query_text]))[0]

        # Fetch embeddings for recent queries
        result = self._queries.get(
            ids=recent_query_ids, include=["embeddings"]
        )
        if not result["embeddings"]:
            return 0.0

        # Compute max cosine similarity manually (avoid needing scipy/numpy as hard dep here)
        import math

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na * nb > 0 else 0.0

        return max(cosine(new_emb, e) for e in result["embeddings"])

    # —————————————————————————————————————————————————————
    # Lifecycle
    # —————————————————————————————————————————————————————

    def cleanup(self) -> None:
        """Delete both collections. Call on Explorer completion if cleanup desired."""
        for name in (f"explore_{self.run_id}_papers", f"explore_{self.run_id}_queries"):
            try:
                self._client.delete_collection(name)
            except Exception as e:
                logger.warning("[embeddings] delete_collection(%s) failed: %s", name, e)
