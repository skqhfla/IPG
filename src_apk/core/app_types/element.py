from __future__ import annotations

from dataclasses import dataclass, field

from .bbox import BBox
from .event import EventKey


@dataclass(slots=True)
class Element:
    element_id: str
    cls: str
    bbox: BBox
    source: str

    resource_id: str | None = None
    text: str | None = None
    description: str | None = None

    executed_events: set[EventKey] = field(default_factory=set)

    is_actionable: bool = True
    is_scrollable: bool = False
    swipe_directions_tried: set[str] = field(default_factory=set)
    swipe_directions_exhausted: set[str] = field(default_factory=set)

    note: str | None = None

    @property
    def identity_key(self) -> str:
        """
        스크롤로 위치(bbox)가 바뀌어도 동일 element를 식별하기 위한 키.

        positional element_id(`el_0003`)는 detection마다 재부여되므로
        화면을 스크롤하면 같은 버튼이 다른 id를 받는다. identity_key는
        content 기반이라 스크롤 offset이 달라도 안정적이다.

        우선순위: (class + resource-id + text + content-desc).
        라벨이 전혀 없는 element는 식별 불가하므로 bbox를 포함한다
        (offset마다 키가 달라지지만, 서로 다른 무명 element를 잘못
        합치는 것보다 안전하다).
        """
        parts: list[str] = [self.cls or "?"]
        if self.resource_id:
            parts.append(f"rid={self.resource_id}")
        text = (self.text or "").strip()
        if text:
            parts.append(f"text={text}")
        desc = (self.description or "").strip()
        if desc:
            parts.append(f"desc={desc}")
        if len(parts) > 1:
            return "|".join(parts)

        x1, y1, x2, y2 = self.bbox.as_tuple()
        return f"anon|{parts[0]}|{x1},{y1},{x2},{y2}"

    def has_executed(self, event_key: EventKey) -> bool:
        return event_key in self.executed_events

    def mark_executed(self, event_key: EventKey) -> None:
        self.executed_events.add(event_key)

    def mark_swipe_tried(self, direction: str) -> None:
        self.swipe_directions_tried.add(direction)

    def mark_swipe_exhausted(self, direction: str) -> None:
        self.swipe_directions_tried.add(direction)
        self.swipe_directions_exhausted.add(direction)