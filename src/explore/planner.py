"""Planner: proposes the next action given current state.

Two implementations:
  - MockPlanner: returns pre-scripted actions, used for orchestrator tests
  - LLMPlanner: real Gemini-backed planner per docs/onboard-redesign/08

LLMPlanner contract:
  - System prompt is stable (cached by Gemini transparently).
  - Dynamic context is rendered from ExplorationState each turn.
  - Output is strict JSON, validated via pydantic discriminated union.
  - Schema violation is fatal (Q8) — raises LLMPlannerError, orchestrator
    treats as structural failure and aborts with state saved.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from pydantic import TypeAdapter, ValidationError

from src.explore.actions import Action
from src.explore.prompts import SYSTEM_PROMPT, build_dynamic_context

if TYPE_CHECKING:
    from src.explore.spec import Verdict
    from src.explore.state import ExplorationState
    from src.llm.gemini_client import GeminiClient


logger = logging.getLogger(__name__)


_ACTION_ADAPTER: TypeAdapter = TypeAdapter(Action)


class LLMPlannerError(RuntimeError):
    """Raised when LLM output can't be parsed into a valid Action.

    Per Q8 policy (no-retry on structural errors) this is fatal: orchestrator
    should save state + diagnostics + exit.
    """

    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


class Planner(ABC):
    """Abstract planner interface."""

    @abstractmethod
    async def propose(
        self,
        state: "ExplorationState",
        last_verdict: "Verdict | None" = None,
    ) -> "Action":
        """Propose the next action.

        Args:
            state: current exploration state
            last_verdict: if the previous proposal was blocked/rewritten,
                          the verdict so the planner can see the feedback

        Returns:
            A concrete Action subclass instance (validated by pydantic).
        """
        raise NotImplementedError


class MockPlanner(Planner):
    """Returns pre-scripted actions in order.

    Used by M1 to validate the main loop without involving an LLM. When the
    script runs out, raises StopIteration.
    """

    def __init__(self, script: list["Action"]):
        self._script = list(script)
        self._index = 0

    async def propose(
        self,
        state: "ExplorationState",
        last_verdict: "Verdict | None" = None,
    ) -> "Action":
        if self._index >= len(self._script):
            raise RuntimeError(
                f"MockPlanner script exhausted after {self._index} actions. "
                f"Script must cover the full run until StopAction."
            )
        action = self._script[self._index]
        self._index += 1
        logger.debug(
            "MockPlanner proposing action %d/%d: %s",
            self._index,
            len(self._script),
            action.action_type,
        )
        return action

    @property
    def consumed(self) -> int:
        return self._index


class LLMPlanner(Planner):
    """Gemini-backed planner using the 08 prompt template.

    Model choice defaults to reader_model (Pro for production tier). Pass an
    explicit model name to override (e.g. Flash for dev tier, cheaper T1 tests).
    """

    def __init__(
        self,
        llm: "GeminiClient",
        *,
        model: Optional[str] = None,
    ):
        self.llm = llm
        self.model = model or llm.config.reader_model

    async def propose(
        self,
        state: "ExplorationState",
        last_verdict: Optional["Verdict"] = None,
    ) -> Action:
        dynamic = build_dynamic_context(state, last_verdict)
        prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{dynamic}"

        logger.debug(
            "[planner] calling %s (prompt=%d chars)", self.model, len(prompt)
        )

        raw = await self.llm.generate(prompt, model=self.model, json_mode=True)

        try:
            action = _ACTION_ADAPTER.validate_json(raw)
        except ValidationError as e:
            logger.error("[planner] malformed action JSON:\n%s\n---\n%s", e, raw)
            raise LLMPlannerError(
                f"Planner output failed schema validation: {e}",
                raw_output=raw,
            ) from e

        logger.info(
            "[planner] proposed: %s (reasoning=%r)",
            action.action_type,
            action.reasoning[:80],
        )
        return action
