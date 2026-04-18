"""Explorer main loop.

Wires Planner → Spec → Executor → State updates → Checkpoint.
See docs/onboard-redesign/06-action-system.md section "主循环骨架".

M1 runs with MockPlanner + stub ActionExecutor, proving the loop, spec
arbitration, and checkpoint mechanics work before any LLM/network code lands.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.explore.actions import StopAction
from src.explore.checkpoint import checkpoint_path_for, save_checkpoint
from src.explore.executor import ActionExecutor, ActionResult
from src.explore.planner import Planner
from src.explore.spec import (
    ALL_RULES,
    SpecEvaluator,
    SpecPredicateError,
    Verdict,
)
from src.explore.state import (
    ActionRecord,
    ExplorationState,
)


logger = logging.getLogger(__name__)


class Explorer:
    """The main loop: propose → evaluate → execute → record → checkpoint."""

    def __init__(
        self,
        state: ExplorationState,
        planner: Planner,
        executor: ActionExecutor,
        evaluator: Optional[SpecEvaluator] = None,
        checkpoint_dir: Path = Path("data/explore/state"),
    ):
        self.state = state
        self.planner = planner
        self.executor = executor
        self.evaluator = evaluator or SpecEvaluator(ALL_RULES)
        self.checkpoint_path = checkpoint_path_for(state.metadata.run_id, checkpoint_dir)
        self._start_time = time.monotonic()

    async def run(self) -> ExplorationState:
        """Run the exploration loop until the state reaches a terminal status."""
        last_verdict: Optional[Verdict] = None
        logger.info("Explorer run %s starting", self.state.metadata.run_id)

        try:
            while self.state.metadata.status == "running":
                # Update elapsed
                self.state.budget.elapsed_seconds = time.monotonic() - self._start_time

                # 1. Planner proposes
                action = await self.planner.propose(self.state, last_verdict)

                # 2. Spec evaluates
                try:
                    verdict = self.evaluator.evaluate(action, self.state)
                except SpecPredicateError as e:
                    logger.exception("Spec predicate aborted run: %s", e)
                    self._mark_failed("spec_predicate_error", str(e))
                    break

                # 3. Handle verdict
                if verdict.kind == "block":
                    self._record_blocked(action, verdict)
                    last_verdict = verdict
                    save_checkpoint(self.state, self.checkpoint_path)
                    continue

                if verdict.kind == "warn":
                    logger.warning(
                        "Rule %s warned: %s", verdict.rule_name, verdict.feedback
                    )

                # rewrite / force / allow all lead to execution
                executed_action = action
                original_proposed = None
                if verdict.kind == "rewrite" and verdict.rewritten_action is not None:
                    executed_action = verdict.rewritten_action
                    original_proposed = action
                elif verdict.kind == "force" and verdict.forced_action is not None:
                    executed_action = verdict.forced_action
                    original_proposed = action

                # 4. Execute
                result = await self.executor.execute(executed_action, self.state)
                self._record_executed(
                    executed_action, original_proposed, verdict, result
                )
                last_verdict = None  # clear after successful execution

                save_checkpoint(self.state, self.checkpoint_path)

                # 5. Terminal check: if a StopAction executed successfully, exit
                if isinstance(executed_action, StopAction) and result.success:
                    self.state.metadata.status = "completed"
                    self.state.metadata.termination_reason = (
                        executed_action.claimed_reason
                    )
                    logger.info(
                        "Explorer run %s completed (%s)",
                        self.state.metadata.run_id,
                        executed_action.claimed_reason,
                    )
                    break

        except KeyboardInterrupt:
            logger.warning("Interrupted by user — saving checkpoint")
            self.state.metadata.status = "cancelled"
            self.state.metadata.termination_reason = "user_cancel"

        # Final save
        self.state.metadata.last_updated_at = datetime.now()
        save_checkpoint(self.state, self.checkpoint_path)
        return self.state

    # —————————————————————————————————————————————————————

    def _record_blocked(self, action, verdict: Verdict) -> None:
        record = ActionRecord(
            turn=self.state.turn,  # block doesn't bump turn
            action=action,
            was_executed=False,
            original_proposed_action=None,
            spec_verdict="block",
            spec_feedback=verdict.feedback,
            spec_rules_fired=verdict.all_fired_rules or [verdict.rule_name],
            executed_at=None,
            outcome="not_executed",
            outcome_summary=f"blocked by {verdict.rule_name}",
            duration_ms=0,
        )
        self.state.action_history.append(record)
        logger.info(
            "Action %s BLOCKED by %s: %s",
            action.action_type,
            verdict.rule_name,
            verdict.feedback,
        )

    def _record_executed(
        self,
        executed_action,
        original_proposed,
        verdict: Verdict,
        result: ActionResult,
    ) -> None:
        # Increment turn (this action executed)
        new_turn = self.state.turn + 1
        record = ActionRecord(
            turn=new_turn,
            action=executed_action,
            was_executed=True,
            original_proposed_action=original_proposed,
            spec_verdict=verdict.kind,
            spec_feedback=verdict.feedback,
            spec_rules_fired=verdict.all_fired_rules or [verdict.rule_name],
            executed_at=datetime.now(),
            outcome="success" if result.success else "failed",
            outcome_summary=result.summary,
            duration_ms=result.duration_ms,
            llm_calls=result.llm_calls,
        )
        self.state.action_history.append(record)
        self.state.budget.actions_used += 1
        logger.info(
            "Action %s executed (%s): %s",
            executed_action.action_type,
            verdict.kind,
            result.summary,
        )

    def _mark_failed(self, reason: str, detail: str) -> None:
        self.state.metadata.status = "failed"
        self.state.metadata.termination_reason = f"{reason}: {detail}"
