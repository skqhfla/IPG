from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.app_types import Element, Screen
from core.runtime.context import RuntimeContext


Action = dict[str, Any]

@dataclass(slots=True)
class Policy:
    logger: Any = None

    def pick_action(
        self,
        *,
        ctx: RuntimeContext,
        screen: Screen,
        swipe_start_ratio: float = 0.7,
        swipe_end_ratio: float = 0.3,
    ) -> Action | None:

        candidates = self._collect_tap_candidates(screen)

        if candidates:
            element = candidates[0]
            return self._make_tap_action(element)

        if ctx.screen_wh is not None:

            streak = ctx.same_screen_streak
            same_threshold = ctx.settings.traversal.same_screen_threshold
            back_threshold = ctx.settings.traversal.back_threshold

            width, height = ctx.screen_wh

            if streak >= back_threshold:
                return {
                    "type": "back",
                    "why": f"same_screen_streak={streak}_back",
                }

            if streak >= same_threshold:
                return {
                    "type": "swipe",
                    "x1": width // 2,
                    "y1": int(height * swipe_start_ratio),
                    "x2": width // 2,
                    "y2": int(height * swipe_end_ratio),
                    "duration_ms": 250,
                    "why": f"same_screen_streak={streak}_scroll",
                }

        return {
            "type": "back",
            "why": "no_candidates_back",
        }

    def _collect_tap_candidates(self, screen: Screen) -> list[Element]:
        candidates = [
            element
            for element in screen.elements
            if element.is_actionable and not element.executed_events
        ]

        def priority(el: Element) -> tuple[int, int, int]:
            label_rank = {
                "textbutton": 0,
                "button": 0,
                "checkbox": 1,
                "switch": 1,
                "icon": 2,
                "text": 3,
                "textview": 3,
                "imageview": 4,
            }.get(str(getattr(el, "cls", "")).lower(), 5)

            b = el.bbox
            return (label_rank, -int(b.y1), -int(b.x1))

        candidates.sort(key=priority)
        return candidates

    def _make_tap_action(self, element: Element) -> Action:
        return {
            "type": "tap",
            "event_type": "tap",
            "element_id": element.element_id,
            "x": element.bbox.cx,
            "y": element.bbox.cy,
            "element_class": element.cls,
            "element_text": (element.text or "")[:120],
            "element_desc": (element.description or "")[:120],
            "element_resource_id": element.resource_id,
            "element_bounds": list(element.bbox.as_tuple()),
            "element_source": element.source,
            "why": "first_unexecuted_actionable_element",
        }