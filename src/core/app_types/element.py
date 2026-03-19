from __future__ import annotations

from dataclasses import dataclass, field

from .bbox import BBox
from .event import EventKey


@dataclass(slots=True)
class Element:
    element_id: str
    cls: str
    bbox: BBox
    source: str

    resource_id: str | None = None
    text: str | None = None
    description: str | None = None

    executed_events: set[EventKey] = field(default_factory=set)

    is_actionable: bool = True
    note: str | None = None

    def has_executed(self, event_key: EventKey) -> bool:
        return event_key in self.executed_events

    def mark_executed(self, event_key: EventKey) -> None:
        self.executed_events.add(event_key)