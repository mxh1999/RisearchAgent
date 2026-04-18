"""Planner: proposes the next action given current state.

M1 provides a MockPlanner that reads canned actions from a script. The real
LLM-backed planner arrives in M2 per docs/onboard-redesign/08-planner-prompt.md.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.explore.actions import Action
    from src.explore.spec import Verdict
    from src.explore.state import ExplorationState


logger = logging.getLogger(__name__)


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
