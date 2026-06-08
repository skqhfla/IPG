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
        # 같은 bounds로 겹친 노드들(라벨 TextView + 클릭 가능 부모 등) 중
        # 하나라도 visible이면 사용자에겐 visible. 보수적으로 OR.
        any_visible = any(e.is_visible_to_user for e in group)

        merged.append(
            replace(
                rep,
                text=text,
                description=desc,
                is_scrollable=rep.is_scrollable or any_scrollable,
                is_visible_to_user=any_visible,
            )
        )

    return tuple(merged)