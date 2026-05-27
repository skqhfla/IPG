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
    # XML <hierarchy package="..."> — 실제 foreground 윈도우의 패키지.
    # 타겟 외 화면이 dump됐을 때 등록을 차단하는 게이트의 source-of-truth.
    package: str | None = None
    # 디스플레이 회전 (0/1/2/3 = 0°/90°/180°/270°). bbox/screencap이 이 회전 기준이라
    # normalize·event 좌표 계산 시 effective screen_wh를 swap해야 한다.
    rotation: int = 0
    # 트리 기반 화면 매칭용 canonical subtree-hash multiset.
    # detector가 채워두면 match_screen이 재사용하고, None이면 호출자가
    # xml_path에서 lazy 재계산한다 (loader 경로 등).
    tree_signature: tuple[str, ...] = field(default_factory=tuple)