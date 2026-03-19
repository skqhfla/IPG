#src/core/app_types/screen.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .element import Element
from .screen_id import ScreenID


@dataclass(slots=True)
class Screen:
    screen_id: ScreenID
    screenshot_path: Path | None = None
    xml_path : Path | None = None
    elements: list[Element] = field(default_factory=list)