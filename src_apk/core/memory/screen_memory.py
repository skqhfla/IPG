#src/core/memory/screen_memory.py
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from core.app_types import EventKey


@dataclass(frozen=True, slots=True)
class ScreenTransition:
    src_screen_key: str
    event_key: EventKey


class ScreenMemoryStore:
    def __init__(self) -> None:
        self._transitions: dict[str, list[ScreenTransition]] = {}

    def has_screen(self, screen_key: str) -> bool:
        return screen_key in self._transitions

    def get_transitions(self, dst_screen_key: str) -> list[ScreenTransition]:
        return self._transitions.get(dst_screen_key, [])

    def record_transition(
        self,
        dst_screen_key: str,
        src_screen_key: str,
        event_key: EventKey,
    ) -> None:
        entry = ScreenTransition(
            src_screen_key=src_screen_key,
            event_key=event_key,
        )

        bucket = self._transitions.setdefault(dst_screen_key, [])

        if entry not in bucket:
            bucket.append(entry)

    def get_all_transitions(self) -> dict[str, list[ScreenTransition]]:
        return self._transitions

    def iter_transitions(self) -> Iterable[tuple[str, list[ScreenTransition]]]:
        return self._transitions.items()

    def screen_count(self) -> int:
        return len(self._transitions)

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}

        for dst_screen_key, transitions in self._transitions.items():
            result[dst_screen_key] = [
                {
                    "src_screen_key": transition.src_screen_key,
                    "event_key": transition.event_key,
                }
                for transition in transitions
            ]

        return result