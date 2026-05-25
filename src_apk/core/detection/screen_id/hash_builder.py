from __future__ import annotations

import hashlib

from core.app_types import Element, ScreenID
from core.config import Settings
from core.detection.screen_id.base import BaseScreenIdBuilder


class HashScreenIdBuilder(BaseScreenIdBuilder):
    def build(
        self,
        *,
        settings: Settings,
        elements: list[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> ScreenID:
        rows: list[tuple[str, int, int, int, int]] = []

        for element in elements:
            x1, y1, x2, y2 = element.bbox.as_tuple()
            cls_name = str(getattr(element, "cls", "") or "")
            rows.append((cls_name, x1, y1, x2, y2))

        rows.sort(key=lambda x: (x[0], x[2], x[1], x[4], x[3]))

        raw = "||".join(
            f"{cls_name}|{x1},{y1},{x2},{y2}"
            for cls_name, x1, y1, x2, y2 in rows
        )

        value = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return ScreenID(value=value)