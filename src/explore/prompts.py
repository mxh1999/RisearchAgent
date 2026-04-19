"""Prompt templates for the Explorer's Planner.

See docs/onboard-redesign/08-planner-prompt.md for the design.

The system prompt is stable across all runs and benefits from Gemini's
prompt cache (not explicitly enabled in M2; full prompt each call).
The user-prompt rendering is data-driven from ExplorationState.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.explore.spec import Verdict
    from src.explore.state import ExplorationState


SYSTEM_PROMPT = """\
# You are the Explorer Planner

You are the decision-making component of an autonomous research Explorer.
Your job is to propose the next action that advances the exploration of a
research field toward a complete, well-evidenced field map.

## Your Operating Context

- The Explorer surveys a research field based on the user's intent.
- You run for ~10-15 minutes with a fixed action budget.
- Your output drives the next tool call (search, fetch, read, etc).
- A separate layer (Spec) validates your proposals; if blocked, you'll see
  feedback in the context and must adjust.

## Your Principles

1. **Breadth first.** Survey 100-300 abstracts before any deep read.
2. **Evidence over intuition.** Every action must cite specific state evidence.
3. **Let structure emerge.** Don't force the user's intent into preset sub-areas.
4. **Don't waste deep reads.** read_paper is capped at 3/run.
5. **Stop when saturated.** Low pool growth + coverage audit passing = ready.

## Available Actions

### search
Issue an ArXiv query. Broad early; targeted later (cluster / classic / benchmark).
Good: `search(query="SLAM classical baselines", date_range=("2018-01-01","2021-12-31"),
source_tag="classic_lookup")` when a cluster lacks classics.
Bad (will be blocked after pool>50): `search(query="navigation")` — too broad.

### search_by_author
Structured author search. Use when an author dominates a cluster.
Good: `search_by_author(author_name="Wang L.", max_results=10)`.

### fetch_citations
Expand via references (backward) or cited_by (forward) of a seed paper.

### fetch_related
Semantic-Scholar recommendation for a paper.

### cluster_refresh
Re-cluster the pool. Use when pool grew significantly or assignments feel stale.
(Automatically forced by spec after +15 papers.)

### skim_abstract
Extract benchmark/method/keyword from an abstract (Flash). Target noise papers
or cluster edges.

### read_paper
Full 3-pass deep read (expensive, 3/run). Only on hub papers whose benchmarks
are ambiguous from the abstract alone.

### coverage_audit
Self-audit: can coverage questions be answered from state? Run before stop.

### stop
Request termination. Spec validates:
- Pool saturated (new_paper_ratio < 10% over last 3 rounds)
- Coverage report has unanswered_count == 0
- Otherwise blocked.

## Output Contract

Output strictly valid JSON. Fields are **flat** — do NOT nest under "args".
Put `action_type`, `reasoning`, and all action-specific fields at the top level.
Emit nothing before or after the JSON object.

### Per-action JSON shapes

**search**
```
{"action_type": "search", "query": "...", "categories": ["cs.RO"],
 "max_results": 20, "date_range": ["2019-01-01","2021-12-31"],
 "sort_by": "relevance", "source_tag": "classic_lookup",
 "targeted_cluster_slug": null, "reasoning": "..."}
```
- source_tag must be one of: user_intent_rewrite | llm_generated |
  cluster_targeted | benchmark_seeded | classic_lookup
- sort_by: "relevance" or "date"
- date_range is optional; omit or use null if not needed
- targeted_cluster_slug is optional; only set when source_tag == "cluster_targeted"

**search_by_author**
```
{"action_type": "search_by_author", "author_name": "Wang L.",
 "max_results": 15, "reasoning": "..."}
```

**fetch_citations**
```
{"action_type": "fetch_citations", "arxiv_id": "2401.12345",
 "direction": "references", "max_results": 20, "reasoning": "..."}
```
- direction: "cited_by" | "references" | "both"
- arxiv_id must be a real id from the state's paper_pool

**fetch_related**
```
{"action_type": "fetch_related", "arxiv_id": "2401.12345",
 "max_results": 10, "reasoning": "..."}
```

**cluster_refresh**
```
{"action_type": "cluster_refresh", "force": false, "reasoning": "..."}
```

**skim_abstract**
```
{"action_type": "skim_abstract", "arxiv_id": "2401.12345", "reasoning": "..."}
```

**read_paper**
```
{"action_type": "read_paper", "arxiv_id": "2401.12345", "reasoning": "..."}
```

**coverage_audit**
```
{"action_type": "coverage_audit", "reasoning": "..."}
```

**stop**
```
{"action_type": "stop", "claimed_reason": "saturated", "reasoning": "..."}
```
- claimed_reason: "saturated" | "coverage_complete" | "budget_exhausted"

### Reasoning Quality Rules

Your `reasoning` MUST include:
1. A specific observation (slug, arxiv_id, benchmark name, or a numeric value
   like pool_size, saturation, cluster.size).
2. The gap or opportunity it reveals.
3. Why your chosen action addresses it.

**Good:**
"Cluster vln-ce has size=12 but year_range=[2023, 2025], missing classics.
Searching 2019-2021 VLN baselines via classic_lookup targets this gap."

**Bad (DO NOT):**
"Let's explore more." / "This seems like a good direction." / "Continuing."

## Spec Constraints (Be Aware)

- Max 60 actions, max 3 read_paper, max 15 min total.
- Don't propose an action identical to your previous action.
- After pool > 50, search must be targeted_cluster_slug set OR source_tag
  is one of classic_lookup / benchmark_seeded.
- Stop requires saturation AND coverage audit passing.
- Same query as last 3 searches will be blocked.

If your previous proposal was blocked, a Verdict block appears at the top
of the dynamic context with the rule and feedback. Read it and change
angle accordingly.
"""


def build_dynamic_context(
    state: "ExplorationState",
    last_verdict: Optional["Verdict"] = None,
) -> str:
    """Render the per-turn dynamic context.

    Returns a single string appended to SYSTEM_PROMPT for the LLM call.
    """
    parts: list[str] = []

    # Last Verdict — top priority
    if last_verdict is not None and last_verdict.kind in ("block", "rewrite", "force"):
        parts.append(_render_verdict(last_verdict))

    # User refine feedback
    if state.feedback:
        parts.append(f"## User Feedback\n\n{state.feedback}\n")

    parts.append(_render_intent(state))
    parts.append(_render_budget(state))
    parts.append(_render_saturation(state))
    parts.append(_render_cluster_snapshot(state))
    parts.append(_render_counters(state))
    parts.append(_render_coverage(state))
    parts.append(_render_recent_history(state, n=10))

    parts.append("## Task\n\nPropose the next action as JSON.")

    return "\n\n".join(p for p in parts if p)


# —————————————————————————————————————————————————————————————
# Section renderers
# —————————————————————————————————————————————————————————————


def _render_verdict(v: "Verdict") -> str:
    lines = [f"## ⚠️  Last Verdict: {v.kind.upper()}"]
    lines.append(f"**Rule:** `{v.rule_name}`")
    if v.feedback:
        lines.append(f"**Feedback:** {v.feedback}")
    if v.all_fired_rules and len(v.all_fired_rules) > 1:
        lines.append(f"**All rules that fired:** {', '.join(v.all_fired_rules)}")
    return "\n\n".join(lines)


def _render_intent(state) -> str:
    lines = [f"## Intent\n\n{state.intent.natural_language}"]
    if state.intent.seed_arxiv_ids:
        lines.append("\n**Seed papers:**")
        for aid in state.intent.seed_arxiv_ids:
            v = state.intent.seed_validation.get(aid)
            if v:
                tag = "✓ anchor" if v.used_as_anchor else f"? match={v.match_score:.2f}"
                lines.append(f"- `{aid}` ({tag})")
            else:
                lines.append(f"- `{aid}`")
    return "\n".join(lines)


def _render_budget(state) -> str:
    b = state.budget
    return (
        "## Budget\n\n"
        f"| Field | Used | Limit |\n"
        f"| --- | --- | --- |\n"
        f"| Elapsed | {b.elapsed_seconds:.0f}s | {b.time_budget_seconds}s |\n"
        f"| Actions | {b.actions_used} | {b.action_budget} |\n"
        f"| read_paper | {b.read_papers_used} | {b.read_paper_budget} |\n"
        f"| Pool size | {state.pool_size} | — |"
    )


def _render_saturation(state) -> str:
    from src.explore.spec import SATURATION_RATIO_THRESHOLD, SATURATION_WINDOW

    ratio = state.new_paper_ratio_last_n_rounds(SATURATION_WINDOW)
    return (
        "## Saturation\n\n"
        f"new_paper_ratio over last {SATURATION_WINDOW} queries: **{ratio:.2f}**\n"
        f"Target: < {SATURATION_RATIO_THRESHOLD:.2f} for stop to be allowed."
    )


def _render_cluster_snapshot(state) -> str:
    if state.cluster_snapshot is None or not state.cluster_snapshot.clusters:
        return "## Cluster Snapshot\n\n_No clusters yet (pool may be too small, or cluster_refresh not run)._"

    snap = state.cluster_snapshot
    lines = [f"## Cluster Snapshot (after turn {snap.generated_after_turn})\n"]
    lines.append("| slug | size | year_range | top benchmarks | representative |")
    lines.append("| --- | --- | --- | --- | --- |")
    for c in snap.clusters:
        benches = ", ".join(c.shared_benchmarks[:2]) or "—"
        if c.representative_paper_ids:
            rep_id = c.representative_paper_ids[0]
            rep_paper = state.paper_pool.get(rep_id)
            rep = f"{rep_id}: {rep_paper.title[:60]}..." if rep_paper else rep_id
        else:
            rep = "—"
        lines.append(
            f"| `{c.slug}` | {c.size} | {c.year_range[0]}-{c.year_range[1]} "
            f"| {benches} | {rep} |"
        )
    if snap.noise_paper_ids:
        lines.append(f"\nNoise: {len(snap.noise_paper_ids)} papers")
    return "\n".join(lines)


def _render_counters(state) -> str:
    c = state.counters
    parts = ["## Counters (top 10)\n"]

    def fmt(counter: dict, label: str) -> str:
        if not counter:
            return f"**{label}:** _(empty)_"
        items = sorted(counter.items(), key=lambda x: -len(x[1]))[:10]
        body = ", ".join(f"{k} ({len(v)})" for k, v in items)
        extra = len(counter) - 10
        suffix = f" _(and {extra} more)_" if extra > 0 else ""
        return f"**{label}:** {body}{suffix}"

    parts.append(fmt(c.benchmark_counter, "Benchmarks"))
    parts.append(fmt(c.author_counter, "Authors"))
    parts.append(fmt(c.venue_counter, "Years/Venues"))
    return "\n".join(parts)


def _render_coverage(state) -> str:
    if state.coverage_report is None:
        return "## Coverage Report\n\n_No audit run yet._"
    cr = state.coverage_report
    lines = [f"## Coverage Report (after turn {cr.generated_after_turn})"]
    lines.append(f"Passes: **{cr.passes}** (unanswered: {cr.unanswered_count})\n")
    lines.append("| Question | Answered? | Gap |")
    lines.append("| --- | --- | --- |")
    for q in cr.questions:
        gap = q.gap_description or "—"
        lines.append(f"| {q.question} | {'✓' if q.answer_available else '✗'} | {gap} |")
    return "\n".join(lines)


def _render_recent_history(state, n: int = 10) -> str:
    if not state.action_history:
        return "## Recent Action History\n\n_No actions yet._"
    recent = state.action_history[-n:]
    lines = [f"## Recent Action History (last {len(recent)})\n"]
    for r in recent:
        args = _compact_args(r.action)
        marker = "✓" if r.was_executed else "✗"
        verdict = r.spec_verdict
        lines.append(
            f"{marker} [turn {r.turn}] {r.action.action_type}{args} "
            f"→ {r.outcome_summary}  "
            f"_(verdict: {verdict})_"
        )
    return "\n".join(lines)


def _compact_args(action) -> str:
    t = action.action_type
    if t == "search":
        pieces = [f'query="{action.query[:40]}"']
        if action.targeted_cluster_slug:
            pieces.append(f'target={action.targeted_cluster_slug}')
        pieces.append(f'src={action.source_tag}')
        return f"({', '.join(pieces)})"
    if t == "search_by_author":
        return f"(author={action.author_name})"
    if t in ("fetch_citations", "fetch_related", "skim_abstract", "read_paper"):
        return f"({action.arxiv_id})"
    if t == "stop":
        return f"(reason={action.claimed_reason})"
    return "()"
