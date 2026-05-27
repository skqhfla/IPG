from __future__ import annotations

from abc import ABC, abstractmethod

from core.app_types import Element, ScreenID
from core.config import Settings


class BaseScreenIdBuilder(ABC):
    @abstractmethod
    def build(
        self,
        *,
        settings: Settings,
        elements: list[Element],
        screen_wh: tuple[int, int] | None = None,
        tree_signature: tuple[str, ...] | None = None,
        rotation: int = 0,
    ) -> ScreenID:
        raise NotImplementedError