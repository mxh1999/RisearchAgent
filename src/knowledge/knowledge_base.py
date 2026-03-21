import logging
from pathlib import Path

import chromadb

from src.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """ChromaDB-backed vector knowledge base with 3 collections."""

    COLLECTIONS = ["paper_contributions", "paper_methods", "research_context"]

    def __init__(self, chroma_path: Path, llm: GeminiClient):
        self.llm = llm
        self._client = chromadb.PersistentClient(path=str(chroma_path))
        self._collections = {
            name: self._client.get_or_create_collection(name)
            for name in self.COLLECTIONS
        }

    async def add_contribution(
        self, arxiv_id: str, title: str, contributions: list[str]
    ) -> None:
        """Add paper contributions to the knowledge base."""
        if not contributions:
            return
        text = f"Paper: {title}\nContributions:\n" + "\n".join(
            f"- {c}" for c in contributions
        )
        embeddings = await self.llm.embed([text])
        self._collections["paper_contributions"].upsert(
            ids=[arxiv_id],
            embeddings=embeddings,
            documents=[text],
            metadatas=[{"arxiv_id": arxiv_id, "title": title}],
        )

    async def add_method(
        self, arxiv_id: str, title: str, method_description: str
    ) -> None:
        """Add method description to the knowledge base."""
        if not method_description:
            return
        text = f"Paper: {title}\nMethod: {method_description}"
        embeddings = await self.llm.embed([text])
        self._collections["paper_methods"].upsert(
            ids=[arxiv_id],
            embeddings=embeddings,
            documents=[text],
            metadatas=[{"arxiv_id": arxiv_id, "title": title}],
        )

    async def add_context(
        self, arxiv_id: str, title: str, context_text: str
    ) -> None:
        """Add related work / context to the knowledge base."""
        if not context_text:
            return
        text = f"Paper: {title}\nContext: {context_text}"
        embeddings = await self.llm.embed([text])
        self._collections["research_context"].upsert(
            ids=[arxiv_id],
            embeddings=embeddings,
            documents=[text],
            metadatas=[{"arxiv_id": arxiv_id, "title": title}],
        )

    async def query_similar(
        self, query_text: str, collection: str = "paper_contributions", n: int = 5
    ) -> list[dict]:
        """Find similar entries in a collection."""
        embeddings = await self.llm.embed([query_text])
        results = self._collections[collection].query(
            query_embeddings=embeddings,
            n_results=n,
        )

        entries = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else None
                entries.append({
                    "document": doc,
                    "metadata": meta,
                    "distance": distance,
                })
        return entries

    async def store_reading(
        self, arxiv_id: str, title: str, contributions: list[str],
        method: str, context: str
    ) -> None:
        """Store all knowledge from a deep reading."""
        await self.add_contribution(arxiv_id, title, contributions)
        await self.add_method(arxiv_id, title, method)
        await self.add_context(arxiv_id, title, context)
        logger.info(f"Stored knowledge for {arxiv_id}")
