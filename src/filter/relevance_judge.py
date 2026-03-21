import logging
from typing import Optional

from src.config import LLMConfig
from src.llm.gemini_client import GeminiClient
from src.models import Paper, RelevanceVerdict, SearchTopic

logger = logging.getLogger(__name__)

RELEVANCE_PROMPT = """You are an expert research paper relevance assessor.

Given a researcher's profile and a paper's title + abstract, score the paper's relevance from 0 to 10.

## Researcher's Profile
{research_profile}

## Paper
Title: {title}
Abstract: {abstract}

## Scoring Guide
- 9-10: Directly addresses the researcher's core problems/methods
- 7-8: Highly relevant, shares key techniques or problem domain
- 5-6: Moderately relevant, tangential connection
- 3-4: Weakly relevant, broad topic overlap only
- 0-2: Not relevant

Respond in JSON format:
{{
    "score": <int 0-10>,
    "justification": "<1-2 sentences explaining the score>",
    "key_topics": ["<topic1>", "<topic2>", ...]
}}"""


class RelevanceJudge:
    def __init__(self, llm: GeminiClient, config: LLMConfig):
        self.llm = llm
        self.config = config

    async def judge(
        self, paper: Paper, topic: SearchTopic
    ) -> Optional[RelevanceVerdict]:
        """Score a paper's relevance to a research topic."""
        try:
            prompt = RELEVANCE_PROMPT.format(
                research_profile=topic.research_profile,
                title=paper.title,
                abstract=paper.abstract,
            )

            result = await self.llm.generate_json(
                prompt, model=self.config.filter_model
            )

            return RelevanceVerdict(
                arxiv_id=paper.arxiv_id,
                score=int(result["score"]),
                justification=result["justification"],
                key_topics=result.get("key_topics", []),
            )
        except Exception as e:
            logger.error(f"Failed to judge {paper.arxiv_id}: {e}")
            return None

    async def judge_batch(
        self, papers: list[Paper], topic: SearchTopic
    ) -> list[RelevanceVerdict]:
        """Score a batch of papers. Returns only successful results."""
        import asyncio

        tasks = [self.judge(paper, topic) for paper in papers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        verdicts = []
        for paper, result in zip(papers, results):
            if isinstance(result, Exception):
                logger.error(f"Batch error for {paper.arxiv_id}: {result}")
            elif result is not None:
                verdicts.append(result)

        logger.info(f"Judged {len(verdicts)}/{len(papers)} papers")
        return verdicts
