from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.app_types import Element, Screen
from core.runtime.context import RuntimeContext


Action = dict[str, Any]

# tap 후보에서 제외할 element class. 단순 표시 위주의 텍스트 노드는
# 의미 있는 화면 전환을 만드는 경우가 거의 없고, 클릭 가능 표시(is_actionable)가
# 잡혀도 부모 컨테이너의 라벨일 때가 많아 시도해도 같은 화면에서 noise만 쌓인다.
# - YOLO 경로: "text"
# - UIA 경로: simplify_android_class가 마지막 segment만 남기므로
#   "TextView" / "AppCompatTextView" / "MaterialTextView" 등이 모두 "*TextView"로 들어옴
def _is_tap_excluded_class(cls: str) -> bool:
    s = (cls or "").lower()
    return s == "text" or s.endswith("textview")

@dataclass(slots=True)
class Policy:
    logger: Any = None

    def pick_action(
        self,
        *,
        ctx: RuntimeContext,
        screen: Screen,
        swipe_start_ratio: float = 0.7,
        swipe_end_ratio: float = 0.3,
    ) -> Action | None:

        # 스크롤 swipe 제스처 크기는 overlap_ratio로부터 정한다.
        # advance = 1 - overlap 만큼 viewport를 전진시키므로, 연속 스크롤된
        # 두 viewport는 overlap_ratio 만큼 겹친다 (콘텐츠 누락 방지).
        scroll_start_ratio, scroll_end_ratio = self._scroll_ratios(ctx)

        # 연속 스크롤 상한: tap/back 없이 스크롤만 반복되면(exhausted 판정 실패·
        # screen_id 분절 등으로) 무한 루프가 될 수 있다. 상한 도달 시 스크롤
        # 후보를 모두 건너뛰고 tap/back으로 강제 전환한다.
        max_scrolls = getattr(ctx.settings.traversal, "max_consecutive_scrolls", 12)
        scroll_capped = ctx.consecutive_scroll_count >= max_scrolls
        if scroll_capped and self.logger:
            self.logger.info(
                f"[POLICY] 연속 스크롤 {ctx.consecutive_scroll_count}회 도달 "
                f"(상한 {max_scrolls}) → 스크롤 중단, tap/back 강제 전환"
            )

        # 1순위: 아직 시도해보지 않은 swipe 방향이 있으면 tap보다 먼저 일괄 수행.
        # 처음 진입한 화면에서 scrollable 컨테이너의 모든 방향 정보를 우선 수집한 뒤
        # tap 탐색으로 진행하는 패턴.
        if not scroll_capped:
            untried_swipe = self._pick_untried_scrollable_swipe(
                screen=screen,
                ctx=ctx,
                swipe_start_ratio=scroll_start_ratio,
                swipe_end_ratio=scroll_end_ratio,
            )
            if untried_swipe is not None:
                return untried_swipe

        candidates = self._collect_tap_candidates(screen)

        if candidates:
            element = candidates[0]
            return self._make_tap_action(element)

        # tap 후보 소진 후, 아직 exhausted 아닌 방향이 남아있으면 추가 swipe.
        # (예: down 시도 → 새 content 나옴 → tap → 다시 down 가능)
        if not scroll_capped:
            swipe = self._pick_scrollable_swipe(
                screen=screen,
                ctx=ctx,
                swipe_start_ratio=scroll_start_ratio,
                swipe_end_ratio=scroll_end_ratio,
            )
            if swipe is not None:
                return swipe

        # 현재 화면 회전에 맞춘 실효 wh — landscape에서 device-native portrait wh를
        # 그대로 쓰면 fallback swipe가 화면 밖 좌표가 된다.
        effective_wh = ctx.effective_screen_wh(getattr(screen, "rotation", 0))
        if effective_wh is None:
            effective_wh = ctx.screen_wh

        if effective_wh is not None:

            streak = ctx.same_screen_streak
            same_threshold = ctx.settings.traversal.same_screen_threshold
            back_threshold = ctx.settings.traversal.back_threshold

            width, height = effective_wh

            if streak >= back_threshold:
                return {
                    "type": "back",
                    "why": f"same_screen_streak={streak}_back",
                }

            if streak >= same_threshold:
                return {
                    "type": "swipe",
                    "x1": width // 2,
                    "y1": int(height * swipe_start_ratio),
                    "x2": width // 2,
                    "y2": int(height * swipe_end_ratio),
                    "duration_ms": self._scroll_duration_ms(ctx),
                    "why": f"same_screen_streak={streak}_scroll",
                }

        return {
            "type": "back",
            "why": "no_candidates_back",
        }

    @staticmethod
    def _scroll_ratios(ctx: RuntimeContext) -> tuple[float, float]:
        """overlap_ratio로부터 swipe 제스처의 시작/끝 비율(컨테이너 기준)을 계산."""
        overlap = getattr(ctx.settings.traversal, "scroll_overlap_ratio", 0.3)
        advance = max(0.1, min(0.95, 1.0 - float(overlap)))
        start = 0.5 + advance / 2.0
        end = 0.5 - advance / 2.0
        return start, end

    @staticmethod
    def _scroll_duration_ms(ctx: RuntimeContext) -> int:
        return int(getattr(ctx.settings.traversal, "scroll_swipe_duration_ms", 800))

    def _collect_tap_candidates(self, screen: Screen) -> list[Element]:
        candidates = [
            element
            for element in screen.elements
            if element.is_actionable
            and not element.is_scrollable
            and not element.executed_events
            and not _is_tap_excluded_class(str(getattr(element, "cls", "")))
        ]

        def priority(el: Element) -> tuple[int, int, int]:
            label_rank = {
                "textbutton": 0,
                "button": 0,
                "checkbox": 1,
                "switch": 1,
                "icon": 2,
                "imageview": 4,
            }.get(str(getattr(el, "cls", "")).lower(), 5)

            b = el.bbox
            return (label_rank, -int(b.y1), -int(b.x1))

        candidates.sort(key=priority)
        return candidates

    def _pick_untried_scrollable_swipe(
        self,
        *,
        screen: Screen,
        ctx: RuntimeContext,
        swipe_start_ratio: float,
        swipe_end_ratio: float,
    ) -> Action | None:
        """
        아직 한 번도 시도하지 않은 swipe 방향(directions_tried 미포함)이 있는
        scrollable element를 골라 swipe action 반환.
        없으면 None — 호출자가 tap/back으로 진행.
        """
        return self._pick_swipe_against(
            screen=screen,
            ctx=ctx,
            swipe_start_ratio=swipe_start_ratio,
            swipe_end_ratio=swipe_end_ratio,
            skip=lambda el, d: d in el.swipe_directions_tried,
        )

    def _pick_scrollable_swipe(
        self,
        *,
        screen: Screen,
        ctx: RuntimeContext,
        swipe_start_ratio: float,
        swipe_end_ratio: float,
    ) -> Action | None:
        """
        Exhausted로 마킹되지 않은 모든 방향을 후보로 swipe action 반환.
        (이미 한 번 시도했지만 아직 끝까지 도달하지 않은 방향 포함.)
        """
        return self._pick_swipe_against(
            screen=screen,
            ctx=ctx,
            swipe_start_ratio=swipe_start_ratio,
            swipe_end_ratio=swipe_end_ratio,
            skip=lambda el, d: d in el.swipe_directions_exhausted,
        )

    def _pick_swipe_against(
        self,
        *,
        screen: Screen,
        ctx: RuntimeContext,
        swipe_start_ratio: float,
        swipe_end_ratio: float,
        skip,
    ) -> Action | None:
        scrollables = [
            el for el in screen.elements if el.is_scrollable
        ]
        if not scrollables:
            return None

        directions = tuple(ctx.settings.traversal.swipe_directions)
        if not directions:
            return None

        # 우선순위: 큰 컨테이너부터 (보통 메인 스크롤 영역).
        scrollables.sort(
            key=lambda e: (e.bbox.x2 - e.bbox.x1) * (e.bbox.y2 - e.bbox.y1),
            reverse=True,
        )

        for element in scrollables:
            for direction in directions:
                if skip(element, direction):
                    continue
                return self._make_scrollable_swipe_action(
                    element=element,
                    direction=direction,
                    swipe_start_ratio=swipe_start_ratio,
                    swipe_end_ratio=swipe_end_ratio,
                    duration_ms=self._scroll_duration_ms(ctx),
                )

        return None

    def _make_tap_action(self, element: Element) -> Action:
        return {
            "type": "tap",
            "event_type": "tap",
            "element_id": element.element_id,
            "identity_key": element.identity_key,
            "x": element.bbox.cx,
            "y": element.bbox.cy,
            "element_class": element.cls,
            "element_text": (element.text or "")[:120],
            "element_desc": (element.description or "")[:120],
            "element_resource_id": element.resource_id,
            "element_bounds": list(element.bbox.as_tuple()),
            "element_source": element.source,
            "why": "first_unexecuted_actionable_element",
        }

    def _make_scrollable_swipe_action(
        self,
        *,
        element: Element,
        direction: str,
        swipe_start_ratio: float,
        swipe_end_ratio: float,
        duration_ms: int,
    ) -> Action:
        """
        direction == content scroll direction.
          - "down": content가 아래로 → finger를 아래에서 위로 swipe
          - "up":   content가 위로   → finger를 위에서 아래로 swipe
          - "right": finger 좌향
          - "left":  finger 우향
        bbox 내부 좌표만 사용해 edge gesture 회피.
        """
        bb = element.bbox
        cx = (bb.x1 + bb.x2) // 2
        cy = (bb.y1 + bb.y2) // 2
        w = max(bb.x2 - bb.x1, 1)
        h = max(bb.y2 - bb.y1, 1)

        if direction in ("down", "up"):
            y_start = int(bb.y1 + h * swipe_start_ratio)
            y_end = int(bb.y1 + h * swipe_end_ratio)
            if direction == "down":
                x1, y1, x2, y2 = cx, y_start, cx, y_end
            else:
                x1, y1, x2, y2 = cx, y_end, cx, y_start
        elif direction in ("right", "left"):
            x_start = int(bb.x1 + w * swipe_start_ratio)
            x_end = int(bb.x1 + w * swipe_end_ratio)
            if direction == "right":
                x1, y1, x2, y2 = x_start, cy, x_end, cy
            else:
                x1, y1, x2, y2 = x_end, cy, x_start, cy
        else:
            raise ValueError(f"Unsupported swipe direction: {direction}")

        return {
            "type": "swipe",
            "event_type": "swipe",
            "element_id": element.element_id,
            "identity_key": element.identity_key,
            "direction": direction,
            "is_scroll": True,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "duration_ms": duration_ms,
            "element_class": element.cls,
            "element_resource_id": element.resource_id,
            "element_bounds": list(element.bbox.as_tuple()),
            "element_source": element.source,
            "why": f"scrollable_swipe_dir={direction}",
        }
