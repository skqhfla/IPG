#src/core/memory/packet_memory.py
from __future__ import annotations

from collections.abc import Iterable

from core.app_types import EventKey


class PacketMemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, set[EventKey]] = {}

    def has_screen(self, screen_key: str) -> bool:
        return screen_key in self._data

    def add_event(self, screen_key: str, event_key: EventKey) -> None:
        self._data.setdefault(screen_key, set()).add(event_key)

    def has_event(self, screen_key: str, event_key: EventKey) -> bool:
        return event_key in self._data.get(screen_key, set())

    def get_events(self, screen_key: str) -> set[EventKey]:
        return self._data.get(screen_key, set())

    def get_all_events(self) -> dict[str, set[EventKey]]:
        return self._data

    def iter_events(self) -> Iterable[tuple[str, set[EventKey]]]:
        return self._data.items()

    def screen_count(self) -> int:
        return len(self._data)

    def total_event_count(self) -> int:
        return sum(len(events) for events in self._data.values())

    def to_dict(self) -> dict[str, dict[str, list[str]]]:
        return {
            screen_key: {
                "events": sorted(events),
            }
            for screen_key, events in self._data.items()
        }