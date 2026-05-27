from __future__ import annotations

import hashlib

from core.app_types import Element, ScreenID
from core.config import Settings
from core.detection.screen_id.base import BaseScreenIdBuilder
from core.detection.screen_id.hash_builder import HashScreenIdBuilder


class LayoutTreeScreenIdBuilder(BaseScreenIdBuilder):
    """
    XML hierarchy의 canonical subtree-hash multiset을 직접 해싱한다.
    형제 순서가 흔들려도 안정적이고, 깊이 모든 층의 부분구조를 포착해
    RN 라우터처럼 같은 activity 안에서 콘텐츠만 갈리는 화면을 분리한다.

    elements/screen_wh는 무시한다 — 트리 구조 그 자체가 시그니처.
    tree_signature가 비어 있으면(예: YOLO-only, XML dump 실패, 카메라 surface
    위 a11y 빈 응답, 시스템 다이얼로그) HashScreenIdBuilder로 폴백해 element
    bbox+class 해시로 화면을 분리한다 — 그러지 않으면 빈-트리 화면이 전부
    같은 ID로 collapse되어 카메라 라이브뷰와 결제 시트가 한 묶음이 된다.
    폴백 ID에는 `fb_` 접두어를 붙여 일반 트리 ID와 구분한다.
    """

    _fallback = HashScreenIdBuilder()

    def build(
        self,
        *,
        settings: Settings,
        elements: list[Element],
        screen_wh: tuple[int, int] | None = None,
        tree_signature: tuple[str, ...] | None = None,
        rotation: int = 0,
    ) -> ScreenID:
        if not tree_signature:
            fb = self._fallback.build(
                settings=settings,
                elements=elements,
                screen_wh=screen_wh,
                tree_signature=tree_signature,
                rotation=rotation,
            )
            return ScreenID(value=f"fb_{fb.value}")

        # 회전 변형은 같은 activity여도 layout이 달라지므로 별도 screen_id로 분리한다.
        raw = f"r{rotation % 4}|" + "|".join(tree_signature)
        value = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return ScreenID(value=value)
