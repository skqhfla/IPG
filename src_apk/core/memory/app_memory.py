
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

    각 스크롤 viewport가 별도의 screen_id를 받는 설계이므로, 이 record는
    "이 viewport에서 현재 보이는 element"만 담는다. detection 때마다
    재방문 screen에서는 기존 record가 갱신되고, 더 이상 보이지 않는
    identity_key는 prune된다.

    스크롤로 도달한 새 screen은 직전 source viewport의 같은 identity_key
    record로부터 executed_events 만 상속받아 중복 실행을 막는다 — 이는
    AppMemoryStore.inherit_executed_from 에서 수행한다.

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

        match_threshold > 0이면, 등록 전에 visible-only tree_signature
        기반 Jaccard 매칭으로 같은 viewport(=같은 screen_id)인지 판정한다.
        같은 viewport를 재방문하면 기존 screen_id를 재사용하고, 다른
        viewport(스크롤로 도달한 새 화면)는 신규 screen_id를 받는다.

        등록 시 _element_memory[screen_key]는 현재 viewport에 있는
        identity_key 집합으로 재구성된다 — 더 이상 보이지 않는 record는
        prune된다(같은 screen을 재방문하면 자연 회복). 기존 record의
        executed/swipe 마크는 identity_key가 여전히 보이면 유지된다.
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
        self._rebuild_viewport_memory(screen_key, screen.elements)
        return screen

    def upsert_screen(self, screen: Screen) -> None:
        """
        loader 등에서 사용. 기존 Screen 객체는 유지하되, element 메모리는
        identity_key 단위로 흡수한다.
        """
        screen_key = self.make_screen_key(screen)
        if screen_key not in self._screens:
            self._screens[screen_key] = screen
        self._rebuild_viewport_memory(screen_key, screen.elements)

    def inherit_executed_from(
        self,
        *,
        dst_screen_key: str,
        src_screen_key: str,
    ) -> None:
        """
        스크롤로 도달한 dst가 src의 executed_events 를 identity_key 매칭으로
        흡수한다. swipe_directions_tried/exhausted 는 viewport-local 상태이므로
        상속하지 않는다 (각 viewport는 자신의 swipe 가능성을 독립적으로 판단).

        호출 시점은 dst가 _rebuild_viewport_memory 로 갱신된 직후. dst의
        record set 에만 영향을 주며 element 객체의 executed_events 는
        record set 과 reference-bound 이므로 mutation 이 곧바로 보인다.
        """
        if dst_screen_key == src_screen_key:
            return
        src_recs = self._element_memory.get(src_screen_key, {})
        dst_recs = self._element_memory.get(dst_screen_key, {})
        if not src_recs or not dst_recs:
            return
        for identity_key, dst_rec in dst_recs.items():
            src_rec = src_recs.get(identity_key)
            if src_rec is None or not src_rec.executed_events:
                continue
            dst_rec.executed_events.update(src_rec.executed_events)

    def _rebuild_viewport_memory(
        self,
        screen_key: str,
        elements,
    ) -> None:
        """
        screen_key 의 element 메모리를 현재 viewport elements 로 재구성.

        - 현재 보이는 identity_key 의 record 만 유지/생성.
        - 기존 record 가 있으면 메타데이터를 갱신하고 executed/swipe set 는
          그대로 보존(같은 viewport 재방문 시 누적 마크가 살아남는다).
        - 보이지 않게 된 identity_key 의 record 는 drop — JSON dump 와 policy
          모두 "현재 보이는" element 만 보게 된다.
        """
        prev_recs = self._element_memory.get(screen_key, {})
        new_recs: dict[str, ElementRecord] = {}
        for element in elements:
            rec = self._hydrate_into(prev_recs, new_recs, element)
            element.executed_events = rec.executed_events
            element.swipe_directions_tried = rec.swipe_directions_tried
            element.swipe_directions_exhausted = rec.swipe_directions_exhausted
            if rec.note:
                element.note = rec.note
        self._element_memory[screen_key] = new_recs

    def _hydrate_into(
        self,
        prev_recs: dict[str, ElementRecord],
        new_recs: dict[str, ElementRecord],
        element: Element,
    ) -> ElementRecord:
        identity_key = element.identity_key
        existing = prev_recs.get(identity_key)
        if existing is not None:
            existing.element_id = element.element_id
            existing.cls = element.cls
            existing.bbox = element.bbox.as_tuple()
            existing.source = element.source
            existing.resource_id = element.resource_id
            existing.text = element.text
            existing.description = element.description
            existing.is_actionable = element.is_actionable
            existing.is_scrollable = element.is_scrollable
            if element.note and not existing.note:
                existing.note = element.note
            new_recs[identity_key] = existing
            return existing

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
        new_recs[identity_key] = rec
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
        screen별로 직렬화. 각 screen 은 하나의 viewport 이므로 elements는
        "이 viewport에서 마지막 detection 때 보였던 element record" 들이다.
        스크롤로 다른 viewport에서 보였던 element는 그 viewport의 별도
        screen_id 항목에 들어간다.
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
                "package": screen.package,
                "rotation": screen.rotation,
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
