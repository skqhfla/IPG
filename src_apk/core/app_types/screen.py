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
    # a11y dump의 <hierarchy> 메타 — 화면 동일성 매칭에 사용.
    window_id: int | None = None
    activity: str | None = None