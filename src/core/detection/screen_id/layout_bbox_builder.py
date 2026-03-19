from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional, Set

from core.app_types import Element, ScreenID
from core.config import Settings
from core.detection.screen_id.base import BaseScreenIdBuilder


@dataclass(frozen=True, slots=True)
class NBox:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class LayoutElem:
    cls: str
    box: NBox


class LayoutBBoxScreenIdBuilder(BaseScreenIdBuilder):
    def build(
        self,
        *,
        settings: Settings,
        elements: list[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> ScreenID:
        if screen_wh is None:
            raise ValueError("screen_wh is required for LAYOUT_BBOX")

        exclude_labels = self._get_exclude_labels(settings)

        sig = self._build_layout_signature(
            elements=elements,
            screen_wh=screen_wh,
            exclude_labels=exclude_labels,
        )
        raw = self._serialize_layout_signature(sig)
        value = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return ScreenID(value=value)

    def _normalize_bounds(
        self,
        bbox,
        screen_wh: tuple[int, int],
    ) -> NBox:
        w, h = screen_wh
        if w <= 0 or h <= 0:
            raise ValueError(f"Invalid screen_wh={screen_wh}")

        x1 = bbox.x1 / w
        y1 = bbox.y1 / h
        x2 = bbox.x2 / w
        y2 = bbox.y2 / h

        x_lo, x_hi = (x1, x2) if x1 <= x2 else (x2, x1)
        y_lo, y_hi = (y1, y2) if y1 <= y2 else (y2, y1)

        x_lo = min(1.0, max(0.0, x_lo))
        y_lo = min(1.0, max(0.0, y_lo))
        x_hi = min(1.0, max(0.0, x_hi))
        y_hi = min(1.0, max(0.0, y_hi))

        return NBox(x_lo, y_lo, x_hi, y_hi)

    def _build_layout_signature(
        self,
        *,
        elements: list[Element],
        screen_wh: tuple[int, int],
        exclude_labels: Optional[Set[str]] = None,
    ) -> list[LayoutElem]:
        exclude_norm = {s.strip().lower() for s in (exclude_labels or set())}

        sig: list[LayoutElem] = []
        for e in elements:
            cls = self._get_element_label(e).strip()

            if cls.lower() in exclude_norm:
                continue

            sig.append(
                LayoutElem(
                    cls=cls,
                    box=self._normalize_bounds(e.bbox, screen_wh),
                )
            )

        sig.sort(key=lambda x: (x.cls, x.box.y1, x.box.x1, x.box.y2, x.box.x2))
        return sig

    def _serialize_layout_signature(self, sig: list[LayoutElem]) -> str:
        parts: list[str] = []
        for item in sig:
            parts.append(
                f"{item.cls}|"
                f"{item.box.x1:.4f},{item.box.y1:.4f},"
                f"{item.box.x2:.4f},{item.box.y2:.4f}"
            )
        return "||".join(parts)

    def _get_element_label(self, element: Element) -> str:
        cls_name = getattr(element, "cls", None)
        if cls_name is not None and str(cls_name).strip():
            return str(cls_name).strip()

        return ""

    def _get_exclude_labels(self, settings: Settings) -> set[str]:
        exclude_labels = getattr(settings.screen_id, "exclude_labels", None)

        result = {"uppertaskbar"}

        if exclude_labels:
            result.update(str(x).strip().lower() for x in exclude_labels)

        return result