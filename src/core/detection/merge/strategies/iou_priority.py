#src/core/detection/merge/strategies/iou_priority.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.app_types import Element
from core.detection.merge.base import MergeStrategy
from core.detection.merge.ops.common import ensure_bbox
from core.detection.merge.ops.uia import bounds_grouping_merge
from core.detection.merge.ops.yolo import filter_elements_by_modal
from core.detection.merge.utils import iou


@dataclass(frozen=True, slots=True)
class IoUPriorityMerge(MergeStrategy):
    """
    IoU-based merge strategy.

    - Apply UIAutomator-specific preprocessing to `uia`
    - Apply YOLO-specific preprocessing to `model`
    - If IoU >= threshold, keep only the preferred source
    - Default priority: uiautomator > yolo
    """
    threshold: float = 0.6
    prefer_source: str = "uiautomator"
    name: str = "iou_priority"

    def merge(
        self,
        *,
        uia: Sequence[Element],
        model: Sequence[Element],
        screen_wh: tuple[int, int] | None = None,
    ) -> Sequence[Element]:
        if screen_wh is None:
            raise ValueError("screen_wh is required for IoUPriorityMerge")

        # 1) UIAutomator-specific preprocessing
        uia_processed = bounds_grouping_merge(uia)

        # 2) YOLO-specific preprocessing
        model_processed = filter_elements_by_modal(
            model,
            screen_wh=screen_wh,
        )

        # 3) Select preferred source
        if self.prefer_source == "uiautomator":
            preferred = list(uia_processed)
            other = list(model_processed)
        elif self.prefer_source == "yolo":
            preferred = list(model_processed)
            other = list(uia_processed)
        else:
            raise ValueError(f"Unsupported prefer_source: {self.prefer_source}")

        # 4) IoU-based deduplication
        kept: list[Element] = list(preferred)

        for element in other:
            element_bbox = ensure_bbox(element.bbox)

            overlapped = any(
                iou(element_bbox, ensure_bbox(kept_item.bbox)) >= self.threshold
                for kept_item in kept
            )

            if overlapped:
                continue

            kept.append(element)

        return tuple(kept)