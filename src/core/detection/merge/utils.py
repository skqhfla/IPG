from __future__ import annotations

from core.app_types import BBox, Element


def area(bbox: BBox) -> int:
    return max(0, bbox.x2 - bbox.x1) * max(0, bbox.y2 - bbox.y1)


def intersection_area(a: BBox, b: BBox) -> int:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)

    w = max(0, ix2 - ix1)
    h = max(0, iy2 - iy1)
    return w * h


def iou(a: BBox, b: BBox) -> float:
    inter = intersection_area(a, b)
    if inter <= 0:
        return 0.0

    union = area(a) + area(b) - inter
    if union <= 0:
        return 0.0

    return inter / union


def dedupe_exact(elements: list[Element]) -> list[Element]:
    seen: set[tuple] = set()
    out: list[Element] = []

    for element in elements:
        x1, y1, x2, y2 = element.bbox.as_tuple()
        key = (x1, y1, x2, y2, element.cls, element.source)

        if key in seen:
            continue

        seen.add(key)
        out.append(element)

    return out