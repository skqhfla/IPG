#src/core/detection/merge/ops/common.py
from __future__ import annotations

from typing import Tuple, Union, List
from core.app_types import BBox


BBoxLike = Union[BBox, Tuple[int, int, int, int], List[int]]


def ensure_bbox(b: BBoxLike) -> BBox:
    if isinstance(b, BBox):
        return b

    if isinstance(b, (tuple, list)) and len(b) == 4:
        x1, y1, x2, y2 = b
        return BBox(
            x1=int(x1),
            y1=int(y1),
            x2=int(x2),
            y2=int(y2),
        )

    raise TypeError(f"Unsupported bbox type: {type(b)}")


def area(b: BBoxLike) -> int:
    bb = ensure_bbox(b)
    return max(0, bb.x2 - bb.x1) * max(0, bb.y2 - bb.y1)


def center_in(outer: BBox, inner: BBox) -> bool:
    cx = (inner.x1 + inner.x2) // 2
    cy = (inner.y1 + inner.y2) // 2

    return outer.x1 <= cx <= outer.x2 and outer.y1 <= cy <= outer.y2


def contains_px(outer: BBox, inner: BBox, pad: int = 0) -> bool:
    return (
        inner.x1 >= outer.x1 - pad
        and inner.y1 >= outer.y1 - pad
        and inner.x2 <= outer.x2 + pad
        and inner.y2 <= outer.y2 + pad
    )