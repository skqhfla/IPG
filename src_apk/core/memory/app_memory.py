
#src/core/memory/app_memory.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.app_types import Element, EventKey, Screen
from core.memory.screen_match import match_screen


@dataclass(slots=True)
class ElementRecord:
    """
    (screen_key, identity_key) 단위로 영속되는 element 메모리.

    Screen.elements는 detection마다 통째로 교체된다(스크롤 시 viewport가
    바뀌므로). 반면 이 record는 화면 단위로 누적 유지되어, 같은 element가
    스크롤로 사라졌다 다시 나타나도 executed/swipe 기록을 잃지 않는다.

    bbox 등 메타데이터는 "마지막으로 본 시점" 기준으로 갱신된다 — 따라서
    탭 좌표로 직접 쓰면 안 되고, 실제 action은 항상 현재 viewport의
    fresh Element로 수행해야 한다(stale bbox 방지).
    """
    identity_key: str
    element_id: str
    cls: str
    bbox: tuple[int, int, int, int]
    source: str
    resource_id: str | None = None
    text: str | None = None
    description: str | None = None
    is_actionable: bool = True
    is_scrollable: bool = False
    note: str | None = None
    executed_events: set[EventKey] = field(default_factory=set)
    swipe_directions_tried: set[str] = field(default_factory=set)
    swipe_directions_exhausted: set[str] = field(default_factory=set)


class AppMemoryStore:
    def __init__(self) -> None:
        self._screens: dict[str, Screen] = {}
        self._snapshots: dict[str, set[str]] = {}
        # screen_key -> identity_key -> ElementRecord
        self._element_memory: dict[str, dict[str, ElementRecord]] = {}

    @staticmethod
    def make_screen_key(screen: Screen) -> str:
        return screen.screen_id.to_key()

    def has_screen(self, screen_key: str) -> bool:
        return screen_key in self._screens

    def get_screen(self, screen_key: str) -> Screen | None:
        return self._screens.get(screen_key)

    def get_all_screens(self) -> dict[str, Screen]:
        return self._screens

    def iter_screens(self) -> Iterable[tuple[str, Screen]]:
        return self._screens.items()

    def screen_count(self) -> int:
        return len(self._screens)

    def add_snapshot(self, screen_key: str, snapshot_id: str) -> None:
        self._snapshots.setdefault(screen_key, set()).add(snapshot_id)

    def get_snapshots(self, screen_key: str) -> set[str]:
        return self._snapshots.get(screen_key, set())

    # -------------------------------------------------
    # screen / element 등록 (hydration)
    # -------------------------------------------------

    def get_or_add_screen(
        self,
        screen: Screen,
        *,
        match_threshold: float = 0.0,
    ) -> Screen:
        """
        detection 결과 Screen을 canonical로 등록한다.

        match_threshold > 0이면, 등록 전에 구조 기반 매칭(window_id+activity
        버킷 + resource-id Jaccard)으로 기존 화면과 같은 화면인지 판정해
        같으면 그 screen_id를 재사용한다. 스크롤·로딩 스피너·탭 전환으로
        layout 해시가 달라져도 같은 화면이면 하나로 묶인다.

        동일 screen_key가 이미 있으면 elements를 최신 viewport로 교체한다.
        element별 누적 메모리는 _element_memory에 identity_key 단위로
        보존되며, 등록 시 새 element 객체에 그 메모리를 다시 바인딩한다.
        """
        if match_threshold > 0.0:
            matched_key = match_screen(
                candidate=screen,
                existing=self._screens,
                threshold=match_threshold,
            )
            if matched_key is not None:
                screen.screen_id = self._screens[matched_key].screen_id

        screen_key = self.make_screen_key(screen)
        self._screens[screen_key] = screen
        for element in screen.elements:
            self._hydrate_element(screen_key, element)
        return screen

    def upsert_screen(self, screen: Screen) -> None:
        """
        loader 등에서 사용. 기존 Screen 객체는 유지하되, element 메모리는
        identity_key 단위로 흡수한다.
        """
        screen_key = self.make_screen_key(screen)
        if screen_key not in self._screens:
            self._screens[screen_key] = screen
        for element in screen.elements:
            self._hydrate_element(screen_key, element)

    def _hydrate_element(self, screen_key: str, element: Element) -> ElementRecord:
        """
        element를 (screen_key, identity_key)의 영속 record와 동기화한다.

        - record가 없으면 element 현재 상태로 새로 만든다.
        - record가 있으면 메타데이터(bbox 등)를 최신으로 갱신한다.
        - 그 후 element의 executed/swipe set을 record의 set으로 '참조 교체'한다.
          이렇게 하면 이후 element.mark_*() 호출이 곧바로 record에 반영되고,
          detection으로 element 객체가 새로 만들어져도 메모리가 이어진다.
        """
        recs = self._element_memory.setdefault(screen_key, {})
        identity_key = element.identity_key
        rec = recs.get(identity_key)

        if rec is None:
            rec = ElementRecord(
                identity_key=identity_key,
                element_id=element.element_id,
                cls=element.cls,
                bbox=element.bbox.as_tuple(),
                source=element.source,
                resource_id=element.resource_id,
                text=element.text,
                description=element.description,
                is_actionable=element.is_actionable,
                is_scrollable=element.is_scrollable,
                note=element.note,
                executed_events=set(element.executed_events),
                swipe_directions_tried=set(element.swipe_directions_tried),
                swipe_directions_exhausted=set(element.swipe_directions_exhausted),
            )
            recs[identity_key] = rec
        else:
            rec.element_id = element.element_id
            rec.cls = element.cls
            rec.bbox = element.bbox.as_tuple()
            rec.source = element.source
            rec.resource_id = element.resource_id
            rec.text = element.text
            rec.description = element.description
            rec.is_actionable = element.is_actionable
            rec.is_scrollable = element.is_scrollable
            if element.note and not rec.note:
                rec.note = element.note

        element.executed_events = rec.executed_events
        element.swipe_directions_tried = rec.swipe_directions_tried
        element.swipe_directions_exhausted = rec.swipe_directions_exhausted
        if rec.note:
            element.note = rec.note
        return rec

    # -------------------------------------------------
    # element 조회 (현재 viewport 기준)
    # -------------------------------------------------

    def get_elements(self, screen_key: str) -> list[Element]:
        screen = self.get_screen(screen_key)
        if screen is None:
            return []
        return screen.elements

    def get_actionable_elements(self, screen_key: str) -> list[Element]:
        screen = self.get_screen(screen_key)
        if screen is None:
            return []
        return [element for element in screen.elements if element.is_actionable]

    def get_element(self, screen_key: str, element_id: str) -> Element | None:
        screen = self.get_screen(screen_key)
        if screen is None:
            return None

        for element in screen.elements:
            if element.element_id == element_id:
                return element
        return None

    def get_unexecuted_actionable_elements(
        self,
        screen_key: str,
    ) -> list[Element]:
        """
        아직 어떤 event도 수행하지 않은 actionable element들만 반환.
        """
        screen = self.get_screen(screen_key)
        if screen is None:
            return []

        result: list[Element] = []
        for element in screen.elements:
            if not element.is_actionable:
                continue
            if element.executed_events:
                continue
            result.append(element)
        return result

    # -------------------------------------------------
    # 메모리 마킹 (identity_key 단위 — stale element_id 비의존)
    # -------------------------------------------------

    def _record(
        self,
        screen_key: str,
        identity_key: str,
    ) -> ElementRecord | None:
        return self._element_memory.get(screen_key, {}).get(identity_key)

    def mark_event_executed(
        self,
        screen_key: str,
        identity_key: str,
        event_key: EventKey,
    ) -> None:
        rec = self._record(screen_key, identity_key)
        if rec is not None:
            rec.executed_events.add(event_key)

    def mark_swipe_tried(
        self,
        screen_key: str,
        identity_key: str,
        direction: str,
    ) -> None:
        rec = self._record(screen_key, identity_key)
        if rec is not None:
            rec.swipe_directions_tried.add(direction)

    def mark_swipe_exhausted(
        self,
        screen_key: str,
        identity_key: str,
        direction: str,
    ) -> None:
        rec = self._record(screen_key, identity_key)
        if rec is not None:
            rec.swipe_directions_tried.add(direction)
            rec.swipe_directions_exhausted.add(direction)

    def has_executed_event(
        self,
        screen_key: str,
        identity_key: str,
        event_key: EventKey,
    ) -> bool:
        rec = self._record(screen_key, identity_key)
        if rec is None:
            return False
        return event_key in rec.executed_events

    # -------------------------------------------------
    # 직렬화
    # -------------------------------------------------

    def to_dict(self) -> dict[str, dict]:
        """
        screen별로 직렬화. elements는 현재 viewport가 아니라 그 화면에서
        지금까지 본 모든 element record(스크롤로 발견된 것 포함)를 누적해
        내보낸다.
        """
        result: dict[str, dict] = {}

        for screen_key, screen in self._screens.items():
            recs = self._element_memory.get(screen_key, {})

            tried_dirs: set[str] = set()
            exhausted_dirs: set[str] = set()
            for rec in recs.values():
                tried_dirs.update(rec.swipe_directions_tried)
                exhausted_dirs.update(rec.swipe_directions_exhausted)

            result[screen_key] = {
                "screen_id": screen.screen_id.to_key(),
                "window_id": screen.window_id,
                "activity": screen.activity,
                "snapshots": sorted(self._snapshots.get(screen_key, set())),
                "screenshot_path": (
                    str(screen.screenshot_path) if screen.screenshot_path else None
                ),
                "xml_path": str(screen.xml_path) if screen.xml_path else None,
                "scrolls": {
                    "directions_tried": sorted(tried_dirs),
                    "directions_exhausted": sorted(exhausted_dirs),
                },
                "elements": [
                    {
                        "element_id": rec.element_id,
                        "identity_key": rec.identity_key,
                        "class": rec.cls,
                        "bbox": list(rec.bbox),
                        "source": rec.source,
                        "resource_id": rec.resource_id,
                        "text": rec.text,
                        "description": rec.description,
                        "executed_events": sorted(rec.executed_events),
                        "is_actionable": rec.is_actionable,
                        "is_scrollable": rec.is_scrollable,
                        "swipe_directions_tried": sorted(rec.swipe_directions_tried),
                        "swipe_directions_exhausted": sorted(
                            rec.swipe_directions_exhausted
                        ),
                        "note": rec.note,
                    }
                    for rec in recs.values()
                ],
            }

        return result
