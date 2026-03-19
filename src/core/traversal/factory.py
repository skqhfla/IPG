from __future__ import annotations

from core.runtime.context import RuntimeContext
from core.traversal.traverser import Traverser


def create_traverser(ctx: RuntimeContext) -> Traverser:
    return Traverser(
        logger=ctx.logger,
    )