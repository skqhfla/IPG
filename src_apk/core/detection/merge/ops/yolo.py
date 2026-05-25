#src/core/detection/merge/ops/yolo.py
from __future__ import annotations

from typing import Sequence, Tuple, List, Optional

from core.app_types import Element
from core.detection.merge.ops.common import ensure_bbox, area, contains_px


def find_modal_bounds(
    elements: Sequence[Element],
    screen_wh: Optional[Tuple[int, int]] = None,
) -> Optional:

    screen_area = None
    if screen_wh:
        w, h = screen_wh
        screen_area = w * h

    best = None

    for e in elements:
        if (e.cls or "").lower() != "modal":
            continue

        b = ensure_bbox(e.bbox)
        a = area(b)

        if screen_area and (a / screen_area) < 0.08:
            continue

        if best is None or a > best[0]:
            best = (a, b)

    return best[1] if best else None


def filter_elements_by_modal(
    elements: Sequence[Element],
    screen_wh: Optional[Tuple[int, int]] = None,
) -> List[Element]:

    modal = find_modal_bounds(elements, screen_wh)

    if modal is None:
        return list(elements)

    kept = []

    for e in elements:
        b = ensure_bbox(e.bbox)

        if contains_px(modal, b, pad=2):
            kept.append(e)

    return kept