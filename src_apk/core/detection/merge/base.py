#src/core/detection/models/base.py
from __future__ import annotations

from typing import Protocol, Sequence

from core.app_types import Element


class MergeStrategy(Protocol):
    name: str

    def merge(
        self,
        *,
        uia: Sequence[Element],
        model: Sequence[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> Sequence[Element]:
        ...