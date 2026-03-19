from __future__ import annotations

from core.config import ScreenIdKind
from core.detection.screen_id.base import BaseScreenIdBuilder
from core.detection.screen_id.hash_builder import HashScreenIdBuilder
from core.detection.screen_id.layout_bbox_builder import LayoutBBoxScreenIdBuilder
from core.detection.screen_id.layout_tree_builder import LayoutTreeScreenIdBuilder


def create_screen_id_builder(kind: ScreenIdKind) -> BaseScreenIdBuilder:
    if kind == ScreenIdKind.HASH:
        return HashScreenIdBuilder()

    if kind == ScreenIdKind.LAYOUT_BBOX:
        return LayoutBBoxScreenIdBuilder()

    if kind == ScreenIdKind.LAYOUT_TREE:
        return LayoutTreeScreenIdBuilder()

    raise ValueError(f"Unsupported ScreenIdKind: {kind}")