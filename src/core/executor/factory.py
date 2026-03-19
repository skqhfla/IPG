from __future__ import annotations

from core.executor.action_executor import ActionExecutor
from core.runtime.context import RuntimeContext


def create_executor(ctx: RuntimeContext) -> ActionExecutor:
    """
    RuntimeContext를 기반으로 ActionExecutor를 생성한다.
    """
    return ActionExecutor(
        ctx=ctx,
        logger=ctx.logger,
    )