#src/core/app_types/event_types.py
from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    TAP = "tap"
    LONG_TAP = "long_tap"
    SWIPE = "swipe"
    INPUT = "input"
    BACK = "back"
    HOME = "home"
    SCHEDULER = "scheduler"

    @property
    def is_navigation(self) -> bool:
        return self in {EventType.BACK, EventType.HOME}

    @property
    def is_ui_action(self) -> bool:
        return self in {
            EventType.TAP,
            EventType.LONG_TAP,
            EventType.SWIPE,
            EventType.INPUT,
            EventType.SCHEDULER,
        }