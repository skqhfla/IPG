from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScreenID:
    value: str

    def to_key(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value