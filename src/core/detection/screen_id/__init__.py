from __future__ import annotations

from core.app_types import Element, ScreenID
from core.config import Settings
from core.detection.screen_id.factory import create_screen_id_builder


def build_screen_id(
    settings: Settings,
    elements: list[Element],
    screen_wh: tuple[int, int] | None = None,
) -> ScreenID:
    builder = create_screen_id_builder(settings.screen_id.kind)
    return builder.build(
        settings=settings,
        elements=elements,
        screen_wh=screen_wh,
    )