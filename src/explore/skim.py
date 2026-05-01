"""Skim abstract: extract benchmarks / methods / keywords via Flash LLM.

Per docs/onboard-redesign/06-action-system.md and 09-clusterer.md, the
output of skim populates:
  - paper.skim (SkimResult)
  - state.counters.benchmark_counter (per-benchmark inverted index)

Skim is intentionally cheap: 1 Flash call per call, ~500 input + 200 output
tokens. Planner controls when it's worthwhile (e.g. on a noise paper or a
cluster centroid lacking benchmarks).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field, ValidationError

from src.explore.state import SkimResult

if TYPE_CHECKING:
    from src.explore.state import PaperRecord
    from src.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


class _SkimSchema(BaseModel):
    """Strict pydantic schema for the LLM JSON output."""

    benchmarks: list[str] = Field(default_factory=list, max_length=10)
    methods: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=15)


SYSTEM_PROMPT = """\
You extract structured tags from a research paper's title + abstract.

Return JSON with three string arrays:
- "benchmarks": named datasets/benchmarks used or referenced (e.g. "HM3D",
  "R2R", "ImageNet", "Habitat-ObjectNav"). Use canonical names. Empty list
  if none mentioned.
- "methods": named methods or model families used (e.g. "CLIP", "BLIP-2",
  "Transformer", "DDPG", "GraphSAGE"). Empty list if no specific named
  method is mentioned.
- "keywords": 3-8 short topical keywords ("zero-shot navigation",
  "loop closure", "open-vocabulary"). No marketing language.

Output STRICT JSON only — no prose, no code fences:
{"benchmarks": [...], "methods": [...], "keywords": [...]}
"""


def _build_user_prompt(paper: "PaperRecord") -> str:
    abstract = (paper.abstract or "").strip()
    return f"Title: {paper.title}\n\nAbstract:\n{abstract}"


async def skim_paper(
    paper: "PaperRecord",
    llm: "GeminiClient",
    *,
    model: Optional[str] = None,
) -> Optional[SkimResult]:
    """Run a Flash skim. Returns SkimResult on success, None on parse failure.

    Failure is non-fatal: caller (Executor) records the action as success but
    paper.skim stays None so a future skim can retry.
    """
    model = model or llm.config.filter_model
    prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{_build_user_prompt(paper)}"

    try:
        raw = await llm.generate(prompt, model=model, json_mode=True)
        parsed = json.loads(raw)
        validated = _SkimSchema.model_validate(parsed)
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        logger.warning("[skim] parse failed for %s: %s", paper.arxiv_id, e)
        return None

    return SkimResult(
        benchmarks=[b.strip() for b in validated.benchmarks if b and b.strip()],
        methods=[m.strip() for m in validated.methods if m and m.strip()],
        keywords=[k.strip() for k in validated.keywords if k and k.strip()],
        skimmed_at=datetime.now(),
    )


__all__ = ["skim_paper"]
