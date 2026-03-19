#src/core/traversal/traverser.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.app_types import Screen
from core.runtime.context import RuntimeContext
from core.traversal.policy.policy import Policy


Action = dict[str, Any]


@dataclass(slots=True)
class Traverser:
    logger: Any = None

    policy: Policy = field(default_factory=Policy)

    def __post_init__(self) -> None:
        if hasattr(self.policy, "logger"):
            self.policy.logger = self.logger

    def choose_action(
        self,
        *,
        ctx: RuntimeContext,
        screen: Screen,
    ) -> Action | None:

        action = self.policy.pick_action(
            screen=screen,
            ctx=ctx,
            swipe_start_ratio=ctx.settings.input.swipe_start_ratio,
            swipe_end_ratio=ctx.settings.input.swipe_end_ratio,
        )

        return action