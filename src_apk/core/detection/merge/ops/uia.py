from __future__ import annotations

from dataclasses import replace
from typing import Sequence, Tuple, List, Dict

from core.app_types import Element
from core.detection.merge.ops.common import ensure_bbox


DROP_LABELS = {
    "framelayout",
    "linearlayout",
    "relativelayout",
    "constraintlayout",
    "coordinatorlayout",
    "viewgroup",
    "view",
}


def bounds_grouping_merge(
    elements: Sequence[Element],
) -> Tuple[Element, ...]:

    filtered = [
        e for e in elements
        if (e.cls or "").lower() not in DROP_LABELS or e.is_scrollable
    ]

    buckets: Dict[Tuple[int, int, int, int], List[Element]] = {}

    for e in filtered:
        b = ensure_bbox(e.bbox)
        key = (b.x1, b.y1, b.x2, b.y2)

        buckets.setdefault(key, []).append(e)

    merged: List[Element] = []

    for group in buckets.values():

        rep = max(
            group,
            key=lambda e: (
                len((e.text or "")),
                len((e.description or "")),
                bool(e.resource_id),
            )
        )

        text = max((e.text or "" for e in group), key=len, default="")
        desc = max((e.description or "" for e in group), key=len, default="")
        any_scrollable = any(e.is_scrollable for e in group)

        merged.append(
            replace(
                rep,
                text=text,
                description=desc,
                is_scrollable=rep.is_scrollable or any_scrollable,
            )
        )

    return tuple(merged)