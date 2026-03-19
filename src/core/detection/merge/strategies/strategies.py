from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from core.app_types import Element
from core.detection.merge.base import MergeStrategy
from core.detection.merge.utils import dedupe_exact, iou


@dataclass(frozen=True, slots=True)
class ConcatMerge(MergeStrategy):
    name: str = "concat"

    def merge(
        self,
        *,
        uia: Sequence[Element],
        model: Sequence[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> Sequence[Element]:
        return tuple(list(uia) + list(model))


@dataclass(frozen=True, slots=True)
class ExactDedupeMerge(MergeStrategy):
    """
    엄격 중복 제거:
    - bbox + cls + source가 완전히 같을 때만 제거
    """
    name: str = "dedupe_exact"

    def merge(
        self,
        *,
        uia: Sequence[Element],
        model: Sequence[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> Sequence[Element]:
        merged = list(uia) + list(model)
        return tuple(dedupe_exact(merged))


@dataclass(frozen=True, slots=True)
class IoUPriorityMerge(MergeStrategy):
    """
    IoU 기반 merge
    - bbox IoU >= threshold 이면 우선순위 쪽만 남김
    - 기본 우선순위: uiautomator > yolo
    """
    threshold: float = 0.6
    prefer_source: str = "uiautomator"
    name: str = "iou_priority"

    logger: Any = None
    debug: bool = False

    def merge(
        self,
        *,
        uia: Sequence[Element],
        model: Sequence[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> Sequence[Element]:
        if self.prefer_source == "uiautomator":
            preferred = list(uia)
            other = list(model)
        elif self.prefer_source == "yolo":
            preferred = list(model)
            other = list(uia)
        else:
            raise ValueError(f"Unsupported prefer_source: {self.prefer_source}")

        kept: list[Element] = []
        kept.extend(preferred)

        for element in other:
            if any(iou(element.bbox, kept_item.bbox) >= self.threshold for kept_item in kept):
                continue
            kept.append(element)

        return tuple(kept)