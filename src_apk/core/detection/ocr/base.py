from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.app_types import BBox


@dataclass(frozen=True, slots=True)
class OCRItem:
    bbox: BBox
    text: str
    confidence: float
    engine: str


class OCREngine(Protocol):
    name: str

    def read(self, *, image_path: str) -> list[OCRItem]:
        ...