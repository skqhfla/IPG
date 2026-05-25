#src/core/app_types/event.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .event_types import EventType


EventKey = str


@dataclass(frozen=True, slots=True)
class Event:
    type: EventType
    target_id: str | None = None
    params: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @classmethod
    def from_params(
        cls,
        event_type: EventType,
        target_id: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> "Event":
        if not params:
            return cls(type=event_type, target_id=target_id)

        normalized = tuple(
            sorted((str(k), cls._stringify_param(v)) for k, v in params.items())
        )
        return cls(type=event_type, target_id=target_id, params=normalized)

    @staticmethod
    def _stringify_param(value: object) -> str:
        if value is None:
            return "none"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def to_key(self) -> EventKey:
        base = self.type.value

        if self.target_id:
            base += f"@{self.target_id}"

        if self.params:
            param_str = ",".join(f"{k}={v}" for k, v in self.params)
            base += f"|{param_str}"

        return base

    def __str__(self) -> str:
        return self.to_key()