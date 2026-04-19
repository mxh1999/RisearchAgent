"""Minimal progress dashboard for Explorer.

M2 ships a print-based snapshot after each action (simple, no TUI).
Per Q7 decision, dashboard shows *process metrics only* — no intermediate
conclusions (cluster contents, specific papers) that could mislead user.

Fuller `rich.Live` dashboard can arrive later when the signal:noise ratio
of a full-screen display is worth it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.explore.state import ExplorationState


class Dashboard:
    """Simple per-turn status line printer."""

    def __init__(self, verbose: bool = False, enabled: bool = True):
        self.verbose = verbose
        self.enabled = enabled

    def update(self, state: "ExplorationState") -> None:
        if not self.enabled:
            return

        b = state.budget
        sat = state.new_paper_ratio_last_n_rounds(3)
        cluster_count = (
            len(state.cluster_snapshot.clusters) if state.cluster_snapshot else 0
        )

        line = (
            f"[Explorer] "
            f"t={b.elapsed_seconds:4.0f}s/{b.time_budget_seconds}s  "
            f"act={b.actions_used}/{b.action_budget}  "
            f"pool={state.pool_size}  "
            f"clusters={cluster_count}  "
            f"sat={sat:.2f}  "
            f"reads={b.read_papers_used}/{b.read_paper_budget}"
        )

        print(line, flush=True)

        if self.verbose and state.action_history:
            last = state.action_history[-1]
            print(
                f"         last: {last.action.action_type} "
                f"({'✓' if last.was_executed else '✗'}) "
                f"→ {last.outcome_summary}",
                flush=True,
            )

    def on_terminate(self, state: "ExplorationState") -> None:
        if not self.enabled:
            return
        print(
            f"\n[Explorer] {state.metadata.status}: "
            f"{state.metadata.termination_reason or '—'}  "
            f"turns={state.turn}, pool={state.pool_size}",
            flush=True,
        )
