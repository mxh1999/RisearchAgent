import logging
from typing import Optional

from src.config import LLMConfig
from src.knowledge.knowledge_base import KnowledgeBase
from src.llm.gemini_client import GeminiClient
from src.models import ContributionDelta, DeepReading

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are an expert research analyst comparing a new paper against existing knowledge.

## New Paper
Title: {title}
Problem: {problem}
Method: {method}
Contributions: {contributions}
Results: {results}

## Existing Related Work in Knowledge Base
{existing_knowledge}

## Task
Compare the new paper against the existing knowledge and classify its contributions.

Respond in JSON:
{{
    "novel_contributions": ["<truly new ideas or approaches not seen in existing work>"],
    "incremental_improvements": ["<improvements that build on existing work without fundamental novelty>"],
    "contradicts_prior": ["<findings that contradict or challenge previous work, if any>"],
    "overall_significance": "<one of: breakthrough, significant, incremental, marginal>"
}}

Guidelines:
- "breakthrough": Fundamentally new approach or dramatically better results
- "significant": Important advance, new method with clear benefits
- "incremental": Modest improvement on existing approaches
- "marginal": Minimal contribution beyond existing work"""


class ContributionAnalyzer:
    """Analyzes a paper's contributions against the existing knowledge base."""

    def __init__(self, llm: GeminiClient, config: LLMConfig, kb: KnowledgeBase):
        self.llm = llm
        self.config = config
        self.kb = kb

    async def analyze(
        self, title: str, reading: DeepReading
    ) -> Optional[ContributionDelta]:
        """Compare a paper's contributions against existing knowledge."""
        try:
            # Retrieve related knowledge
            query = f"{title} {reading.problem_statement} {reading.proposed_method}"
            similar = await self.kb.query_similar(
                query, collection="paper_contributions", n=5
            )

            existing_text = "No existing related work found in knowledge base."
            if similar:
                existing_text = "\n\n".join(
                    f"[{i+1}] {entry['document']}"
                    for i, entry in enumerate(similar)
                )

            prompt = ANALYSIS_PROMPT.format(
                title=title,
                problem=reading.problem_statement,
                method=reading.proposed_method,
                contributions="\n".join(f"- {c}" for c in reading.key_contributions),
                results=reading.main_results,
                existing_knowledge=existing_text,
            )

            result = await self.llm.generate_json(
                prompt, model=self.config.reader_model
            )

            return ContributionDelta(
                arxiv_id=reading.arxiv_id,
                novel_contributions=result.get("novel_contributions", []),
                incremental_improvements=result.get("incremental_improvements", []),
                contradicts_prior=result.get("contradicts_prior", []),
                overall_significance=result.get("overall_significance", "marginal"),
            )

        except Exception as e:
            logger.error(f"Contribution analysis failed for {reading.arxiv_id}: {e}")
            return None
