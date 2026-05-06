"""Stage 1 of synthesize: ExplorationState → FieldMap (LLM Pro call).

Single Pro call per run. Strict pydantic validation on output. After parse,
runs `validate_citations` to reject any arxiv_id the LLM made up that isn't
actually in state.paper_pool — per docs/onboard-redesign/10-synthesize.md,
hallucinated IDs are fail-fast (one retry, then SynthesisError).

State render uses substantial chunks of the docs/onboard-redesign/08
prompt rendering helpers; a synthesize-specific user prompt is built on
top so the model sees the same field-shape it produces in the action
JSON contract.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import TypeAdapter, ValidationError

from src.synthesize.types import FieldMap

if TYPE_CHECKING:
    from src.explore.state import ExplorationState
    from src.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


_FIELD_MAP_ADAPTER: TypeAdapter[FieldMap] = TypeAdapter(FieldMap)


def _strip_code_fences(text: str) -> str:
    """Strip leading/trailing ```json ... ``` markdown fences if present.

    Same defensive parser as planner.py — Pro occasionally wraps JSON in
    fences even with response_mime_type=application/json.
    """
    s = text.strip()
    if not s:
        return s
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()
            s = s[: -3].rstrip()
    return s


class SynthesisError(RuntimeError):
    """Raised when the LLM output can't be turned into a valid FieldMap."""

    def __init__(self, message: str, raw_output: str = "", details: dict | None = None):
        super().__init__(message)
        self.raw_output = raw_output
        self.details = details or {}


SYSTEM_PROMPT = """\
You synthesize a research-field map from an Explorer's collected state.

You receive: the user's intent, every cluster (with slug + representatives
+ shared benchmarks + top authors + year range), and counters of frequently
seen benchmarks / authors / years. You produce a structured JSON object
that summarizes the field for a graduate student.

## Strict Rules

1. **Every arxiv_id you mention MUST appear in the input state.paper_pool.**
   You will be rejected if you invent IDs.
2. **Be objective.** No marketing language ("groundbreaking", "novel",
   "state-of-the-art"). No value judgments ("X is better than Y").
3. **Don't invent facts.** Only synthesize from what's in the state. If
   the state lacks information for a section (e.g. no clear schools of
   thought emerged), return an empty list for that section.
4. **Use cluster slugs verbatim** when referring to sub-areas in
   `associated_subarea_slugs`.
5. **All output text must be English** unless the user's intent itself is
   in another language.

## Output Schema

Output STRICTLY one JSON object matching this Pydantic schema (no prose,
no code fences). Field types:

```
{
  "header": {
    "intent_snippet": "<<= 200 chars summary of user intent>",
    "generated_at": "<ISO datetime>",
    "n_papers_surveyed": int,
    "n_queries": int,
    "elapsed_seconds": float
  },
  "sub_areas": [
    {
      "slug": "<existing cluster slug>",
      "display_label": "<human-readable>",
      "description": "<3-5 sentences, no marketing>",
      "representative_papers": [{"arxiv_id": "...", "title": "..."}],
      "shared_benchmarks": ["..."],
      "active_authors": ["..."],
      "year_range": [int, int]
    }
  ],
  "dominant_benchmarks": [
    {"name": "...", "task": "...", "n_papers": int,
     "associated_subarea_slugs": ["..."]}
  ],
  "schools_of_thought": [
    {"name": "...", "description": "...",
     "representative_papers": [{"arxiv_id": "...", "title": "..."}]}
  ],
  "classic_baselines": [
    {"arxiv_id": "...", "title": "...", "year": int, "why_classic": "..."}
  ],
  "active_groups": [
    {"name": "<author/lab>", "n_papers": int, "associated_subarea_slugs": ["..."]}
  ],
  "open_questions": [
    {"question": "...", "evidence_papers": [{"arxiv_id": "...", "title": "..."}]}
  ],
  "anchor_papers": [
    {"arxiv_id": "...", "title": "...", "cluster_slug": "...", "rationale": "..."}
  ],
  "notes": ["<warnings: provider degraded, intent disjoint, etc>"]
}
```

Sections you cannot fill (e.g. no schools of thought obviously emerged)
must be returned as `[]` — do not omit the field.
"""


# —————————————————————————————————————————————————————————————
# Public API
# —————————————————————————————————————————————————————————————


async def synthesize(
    state: "ExplorationState",
    llm: "GeminiClient",
    *,
    model: Optional[str] = None,
    max_retries: int = 1,
) -> FieldMap:
    """Run synthesize Stage 1. Returns validated FieldMap.

    Raises SynthesisError on schema failure or hallucinated arxiv_ids
    (after `max_retries`+1 attempts).
    """
    model = model or llm.config.reader_model

    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            user_prompt = _build_user_prompt(state)
            full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
            raw = await llm.generate(full_prompt, model=model, json_mode=True)
            field_map = _FIELD_MAP_ADAPTER.validate_json(_strip_code_fences(raw))
            # Header metadata is metadata, not content — override LLM's
            # values with the truth from state. (LLMs sometimes hallucinate
            # a generated_at timestamp from the past; we've seen 2024 dates
            # appear on a 2026 run.)
            field_map.header.generated_at = datetime.now()
            field_map.header.n_papers_surveyed = state.pool_size
            field_map.header.n_queries = len(state.query_log)
            field_map.header.elapsed_seconds = state.budget.elapsed_seconds
            validate_citations(field_map, state)
            return field_map
        except (ValidationError, SynthesisError) as e:
            last_err = e
            logger.warning(
                "[synthesize] attempt %d failed: %s", attempt + 1, str(e)[:200]
            )
            if attempt >= max_retries:
                if isinstance(e, SynthesisError):
                    raise
                raise SynthesisError(
                    f"FieldMap schema validation failed: {e}",
                    raw_output=raw if "raw" in dir() else "",
                ) from e

    raise SynthesisError(f"Unreachable; last error: {last_err}")


# —————————————————————————————————————————————————————————————
# Citation validation
# —————————————————————————————————————————————————————————————


def _all_arxiv_ids_in_field_map(fm: FieldMap) -> list[str]:
    """Collect every arxiv_id mentioned anywhere in the FieldMap."""
    ids: list[str] = []
    for sa in fm.sub_areas:
        ids.extend(p.arxiv_id for p in sa.representative_papers)
    for s in fm.schools_of_thought:
        ids.extend(p.arxiv_id for p in s.representative_papers)
    for c in fm.classic_baselines:
        ids.append(c.arxiv_id)
    for q in fm.open_questions:
        ids.extend(p.arxiv_id for p in q.evidence_papers)
    for a in fm.anchor_papers:
        ids.append(a.arxiv_id)
    return ids


def validate_citations(fm: FieldMap, state: "ExplorationState") -> None:
    """Reject hallucinated arxiv_ids. Raises SynthesisError on miss."""
    pool_ids = set(state.paper_pool.keys())
    referenced = _all_arxiv_ids_in_field_map(fm)
    halluc = [aid for aid in referenced if aid not in pool_ids]
    if halluc:
        raise SynthesisError(
            f"FieldMap references arxiv_ids not in state.paper_pool: "
            f"{halluc[:10]}{'...' if len(halluc) > 10 else ''}",
            details={"hallucinated_ids": halluc},
        )

    # Also flag any cluster slug referenced that doesn't exist in cluster_snapshot.
    if state.cluster_snapshot is not None:
        cluster_slugs = {c.slug for c in state.cluster_snapshot.clusters}
        referenced_slugs: set[str] = set()
        for sa in fm.sub_areas:
            referenced_slugs.add(sa.slug)
        for be in fm.dominant_benchmarks:
            referenced_slugs.update(be.associated_subarea_slugs)
        for ag in fm.active_groups:
            referenced_slugs.update(ag.associated_subarea_slugs)
        for ap in fm.anchor_papers:
            referenced_slugs.add(ap.cluster_slug)
        bad_slugs = referenced_slugs - cluster_slugs
        if bad_slugs:
            raise SynthesisError(
                f"FieldMap references unknown cluster slugs: {sorted(bad_slugs)}",
                details={"hallucinated_slugs": sorted(bad_slugs)},
            )


# —————————————————————————————————————————————————————————————
# User prompt rendering
# —————————————————————————————————————————————————————————————


def _build_user_prompt(state: "ExplorationState") -> str:
    parts: list[str] = []
    parts.append(f"## User Intent\n\n{state.intent.natural_language}")
    if state.intent.seed_arxiv_ids:
        parts.append("\n**Seed papers:**")
        for aid in state.intent.seed_arxiv_ids:
            sv = state.intent.seed_validation.get(aid)
            tag = ""
            if sv:
                tag = " (✓ anchor)" if sv.used_as_anchor else f" (match={sv.match_score:.2f})"
            parts.append(f"- `{aid}`{tag}")

    # Run summary (becomes Header)
    parts.append("")
    parts.append("## Run Summary")
    parts.append(f"- Papers surveyed: {state.pool_size}")
    parts.append(f"- Queries issued: {len(state.query_log)}")
    parts.append(f"- Elapsed: {state.budget.elapsed_seconds:.0f}s")

    # Cluster snapshot (full detail per cluster)
    snap = state.cluster_snapshot
    if snap is None or not snap.clusters:
        parts.append("\n## Cluster Snapshot\n\n_(no cluster_snapshot)_")
    else:
        parts.append("\n## Cluster Snapshot")
        for c in snap.clusters:
            parts.append(f"\n### `{c.slug}` — {c.display_label}")
            parts.append(f"size={c.size}  year_range={c.year_range[0]}-{c.year_range[1]}  density={c.density}")
            parts.append(f"description: {c.description}")
            if c.shared_benchmarks:
                parts.append(f"shared_benchmarks: {', '.join(c.shared_benchmarks)}")
            if c.top_authors:
                parts.append(f"top_authors: {', '.join(c.top_authors)}")
            parts.append("representative papers:")
            for aid in c.representative_paper_ids[:5]:
                p = state.paper_pool.get(aid)
                if p is None:
                    continue
                parts.append(f"- {aid}: {p.title}")
                excerpt = (p.abstract or "").replace("\n", " ")[:240]
                parts.append(f"  abstract_excerpt: {excerpt}")
        if snap.noise_paper_ids:
            parts.append(f"\nNoise: {len(snap.noise_paper_ids)} papers (not assigned to any cluster).")

    # Counters top 20
    parts.append("\n## Counters (top 20)")

    def fmt_counter(label: str, counter: dict[str, list[str]]) -> str:
        if not counter:
            return f"**{label}:** _(empty)_"
        items = sorted(counter.items(), key=lambda x: -len(x[1]))[:20]
        body = ", ".join(f"{k} ({len(v)})" for k, v in items)
        return f"**{label}:** {body}"

    parts.append(fmt_counter("Benchmarks", state.counters.benchmark_counter))
    parts.append(fmt_counter("Authors", state.counters.author_counter))
    parts.append(fmt_counter("Years", state.counters.venue_counter))

    # Coverage report
    if state.coverage_report is not None:
        parts.append("\n## Coverage Report (final audit)")
        parts.append(
            f"passes={state.coverage_report.passes}, "
            f"unanswered={state.coverage_report.unanswered_count}/"
            f"{len(state.coverage_report.questions)}"
        )
        for q in state.coverage_report.questions:
            mark = "✓" if q.answer_available else "✗"
            parts.append(f"- {mark} {q.question}")
            if not q.answer_available and q.gap_description:
                parts.append(f"  _gap: {q.gap_description}_")

    # Degradation flags
    if state.metadata.citation_provider_degraded:
        parts.append(
            "\n**System note:** citation provider was unavailable; "
            "Classic Baselines may be incomplete. Add a corresponding entry "
            "to `notes`."
        )

    parts.append("\n## Task\n\nProduce the FieldMap JSON now.")

    return "\n".join(parts)


# —————————————————————————————————————————————————————————————
# Header derivation (deterministic helper)
# —————————————————————————————————————————————————————————————


def derive_header_from_state(state: "ExplorationState") -> dict:
    """Build a canonical Header dict directly from state — the LLM must emit
    one matching this; we use this in tests for assertion."""
    intent = state.intent.natural_language
    snippet = intent[:197] + "..." if len(intent) > 200 else intent
    return {
        "intent_snippet": snippet,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_papers_surveyed": state.pool_size,
        "n_queries": len(state.query_log),
        "elapsed_seconds": state.budget.elapsed_seconds,
    }


__all__ = [
    "FieldMap",
    "SynthesisError",
    "synthesize",
    "validate_citations",
    "derive_header_from_state",
]
